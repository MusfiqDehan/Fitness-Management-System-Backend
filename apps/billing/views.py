"""Billing API views.

- Platform package endpoints (`/billing/packages`, `/billing/features`) are
    intended for public-schema platform admin usage and are gated by
    `platform.packages` permissions.
- Platform gateway endpoints (`/billing/gateways`) are platform admin only,
    gated by `platform.billing` permissions.
- Tenant payment endpoints (`/billing/payments/*`) run on tenant schemas and
    are gated by tenant feature permission key `payments`.
- Tenant gateway config endpoints (`/billing/payments/gateways/*`) run on
    tenant schemas and are gated by `payments.gateways`.
"""
import os
import uuid
from functools import lru_cache
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import AllowAny
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from apps.access.permissions import HasFeatureMethodPermission
from apps.membership.models import Member, Payment
from apps.tenancy.models import (
    Feature,
    PaymentGateway,
    PlatformPackage,
    PlatformPackageFeature,
    PlatformPricingConfig,
)
from apps.tenancy.permissions import IsPlatformFeaturePermission
from utils.base_view import ModelCRUDView

from .models import TenantPaymentGateway, PaymentTransaction
from .serializers import (
    AvailableGatewaySerializer,
    FeatureSerializer,
    PackageFeatureBulkSerializer,
    PackageSerializer,
    PaymentGatewaySerializer,
    PaymentInitiateSerializer,
    PaymentMemberOptionSerializer,
    PaymentSerializer,
    PaymentTransactionSerializer,
    PlatformPricingConfigSerializer,
    TenantPaymentGatewaySerializer,
)
from .services import get_gateway


@lru_cache(maxsize=1)
def _get_invoice_fonts() -> tuple[str, str]:
    """Return (regular, bold) fonts, preferring modern sans-serif TTFs."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        (
            "DejaVuSans",
            "DejaVuSans-Bold",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
        (
            "NotoSans",
            "NotoSans-Bold",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ),
    ]

    for regular_name, bold_name, regular_path, bold_path in candidates:
        if not (os.path.exists(regular_path) and os.path.exists(bold_path)):
            continue
        try:
            if regular_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(regular_name, regular_path))
            if bold_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            return regular_name, bold_name
        except Exception:
            continue

    return "Helvetica", "Helvetica-Bold"


def _pdf_clean_text(value) -> str:
    return " ".join(str(value or "-").split()) or "-"


def _pdf_shorten_text(pdf, value, max_width, font_name, font_size) -> str:
    text = _pdf_clean_text(value)
    if pdf.stringWidth(text, font_name, font_size) <= max_width:
        return text

    ellipsis = "..."
    trimmed = text
    while trimmed:
        trimmed = trimmed[:-1].rstrip()
        candidate = f"{trimmed}{ellipsis}"
        if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            return candidate

    return ellipsis


def _pdf_wrap_text(pdf, value, max_width, font_name, font_size, max_lines=2):
    text = _pdf_clean_text(value)
    words = text.split(" ")
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = word
        else:
            lines.append(_pdf_shorten_text(pdf, word, max_width, font_name, font_size))
            current = ""

    if current:
        lines.append(current)

    if max_lines and len(lines) > max_lines:
        visible = lines[: max_lines - 1]
        visible.append(
            _pdf_shorten_text(
                pdf,
                " ".join(lines[max_lines - 1 :]),
                max_width,
                font_name,
                font_size,
            )
        )
        return visible

    return [
        _pdf_shorten_text(pdf, line, max_width, font_name, font_size)
        for line in lines
    ]


def _pdf_draw_lines(
    pdf,
    x,
    top_y,
    lines,
    font_name,
    font_size,
    fill_color,
    line_height,
):
    pdf.setFillColor(fill_color)
    pdf.setFont(font_name, font_size)
    cursor_y = top_y
    for line in lines:
        pdf.drawString(x, cursor_y, line)
        cursor_y -= line_height


def _render_payment_invoice_pdf(payment: Payment, tenant_name: str, generated_by: str) -> bytes:
    # Lazy import keeps startup resilient if dependency installation is pending.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    width, height = A4
    left = 20 * mm
    right = width - (20 * mm)
    top = height - (20 * mm)

    invoice_no = payment.invoice_no or f"INV-{payment.id:06d}"
    member = payment.member
    package_name = member.member_package.name if member.member_package else "General"
    amount = f"TK. {Decimal(payment.amount):,.2f}"
    payment_date = timezone.localtime(payment.payment_date).strftime("%d %b %Y, %I:%M %p")
    member_name = _pdf_clean_text(member.full_name or "Unknown Member")
    member_phone = _pdf_clean_text(member.phone_number)
    generated_by_name = _pdf_clean_text(generated_by or "System")
    tenant_label = _pdf_clean_text(tenant_name or "Fithive")
    payment_item = payment.get_payment_type_display()
    payment_method = payment.get_payment_method_display()
    payment_status = payment.get_payment_status_display()
    notes = _pdf_clean_text(payment.note or "No additional notes.")

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    regular_font, bold_font = _get_invoice_fonts()

    brand_black = colors.HexColor("#101010")
    brand_yellow = colors.HexColor("#FFC733")
    brand_yellow_soft = colors.HexColor("#FFF3C4")
    brand_surface = colors.white
    brand_surface_warm = colors.HexColor("#FFF9EE")
    border_color = colors.HexColor("#E8D39A")
    text_main = colors.HexColor("#171717")
    text_muted = colors.HexColor("#6B6558")

    def draw_field(
        x,
        top_y,
        label,
        value,
        width,
        value_font=None,
        value_size=10,
        max_lines=1,
    ):
        current_value_font = value_font or bold_font
        pdf.setFillColor(text_muted)
        pdf.setFont(regular_font, 8.4)
        pdf.drawString(x, top_y, label.upper())
        lines = _pdf_wrap_text(pdf, value, width, current_value_font, value_size, max_lines=max_lines)
        _pdf_draw_lines(
            pdf,
            x,
            top_y - (4.8 * mm),
            lines,
            current_value_font,
            value_size,
            text_main,
            4.2 * mm,
        )

    pdf.setFillColor(brand_surface)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)

    pdf.setFillColor(brand_black)
    pdf.rect(0, height - (48 * mm), width, 48 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_yellow)
    pdf.rect(0, height - (6 * mm), width, 6 * mm, fill=1, stroke=0)

    pdf.setFillColor(colors.white)
    pdf.setFont(bold_font, 22)
    pdf.drawString(
        left,
        top - (8 * mm),
        _pdf_shorten_text(pdf, tenant_label, right - left - (70 * mm), bold_font, 22),
    )
    pdf.setFont(regular_font, 10)
    pdf.drawString(left, top - (15 * mm), "Payment Invoice")
    pdf.setFont(regular_font, 9)
    pdf.drawString(
        left,
        top - (22 * mm),
        _pdf_shorten_text(pdf, invoice_no, right - left - (70 * mm), regular_font, 9),
    )

    badge_x = right - (58 * mm)
    pdf.setFillColor(brand_yellow)
    pdf.roundRect(badge_x, top - (18 * mm), 58 * mm, 12 * mm, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_black)
    pdf.setFont(bold_font, 10)
    pdf.drawCentredString(badge_x + (29 * mm), top - (10.8 * mm), "MANUAL PAYMENT")
    pdf.setFillColor(colors.white)
    pdf.setFont(regular_font, 9)
    pdf.drawRightString(right, top - (24 * mm), payment_date)

    info_top = top - (40 * mm)
    info_height = 54 * mm
    info_width = right - left
    content_x = left + (6 * mm)
    content_width = info_width - (12 * mm)
    column_gap = 10 * mm
    column_width = (content_width - column_gap) / 2
    right_column_x = content_x + column_width + column_gap

    pdf.setFillColor(brand_surface_warm)
    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(1)
    pdf.roundRect(left, info_top - info_height, info_width, info_height, 4 * mm, fill=1, stroke=1)
    pdf.setStrokeColor(brand_yellow)
    pdf.setLineWidth(2)
    pdf.line(left + (6 * mm), info_top - (6 * mm), right - (6 * mm), info_top - (6 * mm))

    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 11)
    pdf.drawString(content_x, info_top - (11 * mm), "Invoice Details")

    row_one_y = info_top - (18 * mm)
    row_two_y = info_top - (31 * mm)
    row_three_y = info_top - (44 * mm)
    draw_field(content_x, row_one_y, "Invoice No", invoice_no, column_width)
    draw_field(right_column_x, row_one_y, "Payment Date", payment_date, column_width, value_font=regular_font)
    draw_field(content_x, row_two_y, "Member", member_name, column_width)
    draw_field(
        right_column_x,
        row_two_y,
        "Generated By",
        generated_by_name,
        column_width,
        value_font=regular_font,
        value_size=9.5,
        max_lines=1,
    )
    draw_field(content_x, row_three_y, "Contact", member_phone, column_width, value_font=regular_font)
    draw_field(right_column_x, row_three_y, "Package", package_name, column_width, value_font=regular_font, max_lines=1)

    summary_top = info_top - info_height - (12 * mm)
    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 11)
    pdf.drawString(left, summary_top, "Charge Summary")

    table_top = summary_top - (6 * mm)
    table_width = right - left
    item_col = 72 * mm
    method_col = 36 * mm
    status_col = 34 * mm
    amount_col = table_width - item_col - method_col - status_col
    col_one_end = left + item_col
    col_two_end = col_one_end + method_col
    col_three_end = col_two_end + status_col
    header_height = 10 * mm
    row_line_height = 4.2 * mm

    item_lines = _pdf_wrap_text(pdf, payment_item, item_col - (8 * mm), bold_font, 10, max_lines=2)
    method_lines = _pdf_wrap_text(pdf, payment_method, method_col - (6 * mm), regular_font, 9.5, max_lines=2)
    status_lines = _pdf_wrap_text(pdf, payment_status, status_col - (6 * mm), bold_font, 9.5, max_lines=2)
    body_line_count = max(len(item_lines), len(method_lines), len(status_lines), 1)
    body_height = max(15 * mm, (body_line_count * row_line_height) + (6 * mm))
    total_height = 11 * mm
    table_height = header_height + body_height + total_height
    table_bottom = table_top - table_height
    body_bottom = table_top - header_height - body_height

    pdf.setFillColor(brand_surface)
    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(1)
    pdf.roundRect(left, table_bottom, table_width, table_height, 4 * mm, fill=1, stroke=1)

    pdf.setFillColor(brand_black)
    pdf.roundRect(left, table_top - header_height, table_width, header_height, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(bold_font, 9)
    pdf.drawString(left + (4 * mm), table_top - (6.5 * mm), "Item")
    pdf.drawString(col_one_end + (3 * mm), table_top - (6.5 * mm), "Method")
    pdf.drawString(col_two_end + (3 * mm), table_top - (6.5 * mm), "Status")
    pdf.drawRightString(right - (4 * mm), table_top - (6.5 * mm), "Amount")

    pdf.setStrokeColor(border_color)
    pdf.line(left, table_top - header_height, right, table_top - header_height)
    pdf.line(left, body_bottom, right, body_bottom)
    pdf.line(col_one_end, table_top - header_height, col_one_end, body_bottom)
    pdf.line(col_two_end, table_top - header_height, col_two_end, body_bottom)
    pdf.line(col_three_end, table_top - header_height, col_three_end, body_bottom)

    body_text_top = table_top - header_height - (4.5 * mm)
    _pdf_draw_lines(pdf, left + (4 * mm), body_text_top, item_lines, bold_font, 10, text_main, row_line_height)
    _pdf_draw_lines(pdf, col_one_end + (3 * mm), body_text_top, method_lines, regular_font, 9.5, text_main, row_line_height)
    _pdf_draw_lines(pdf, col_two_end + (3 * mm), body_text_top, status_lines, bold_font, 9.5, text_main, row_line_height)
    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 10)
    pdf.drawRightString(
        right - (4 * mm),
        body_text_top,
        _pdf_shorten_text(pdf, amount, amount_col - (5 * mm), bold_font, 10),
    )

    pdf.setFillColor(brand_yellow_soft)
    pdf.rect(left, table_bottom, table_width, total_height, fill=1, stroke=0)
    pdf.setFillColor(brand_black)
    pdf.setFont(bold_font, 11)
    pdf.drawString(left + (4 * mm), table_bottom + (4 * mm), "Total")
    pdf.drawRightString(right - (4 * mm), table_bottom + (4 * mm), amount)

    notes_top = table_bottom - (12 * mm)
    notes_width = right - left
    notes_lines = _pdf_wrap_text(pdf, notes, notes_width - (12 * mm), regular_font, 10, max_lines=4)
    notes_height = max(24 * mm, (len(notes_lines) * (4.6 * mm)) + (12 * mm))

    pdf.setFillColor(brand_surface_warm)
    pdf.setStrokeColor(border_color)
    pdf.roundRect(left, notes_top - notes_height, notes_width, notes_height, 4 * mm, fill=1, stroke=1)
    pdf.setFillColor(text_muted)
    pdf.setFont(regular_font, 8.5)
    pdf.drawString(left + (6 * mm), notes_top - (7 * mm), "NOTES")
    _pdf_draw_lines(pdf, left + (6 * mm), notes_top - (12.5 * mm), notes_lines, regular_font, 10, text_main, 4.6 * mm)

    pdf.setFillColor(brand_black)
    pdf.rect(0, 0, width, 18 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_yellow)
    pdf.rect(0, 18 * mm, width, 2 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(regular_font, 9)
    pdf.drawCentredString(width / 2, 7.5 * mm, "Thank you for your payment. This invoice is system-generated.")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


PACKAGE_VIEW_PERMS = [
    IsPlatformFeaturePermission.require("platform.packages", "view"),
]
PACKAGE_EDIT_PERMS = [
    IsPlatformFeaturePermission.require("platform.packages", "edit"),
]


class FeatureListAPIView(APIView):
    """GET /api/v1/billing/features/ — list all known features."""

    permission_classes = PACKAGE_VIEW_PERMS

    def get(self, request):
        features = Feature.objects.all().order_by("sort_order", "key")
        return Response(FeatureSerializer(features, many=True).data)


class PlatformPricingConfigAPIView(APIView):
    """GET / PATCH /api/v1/billing/pricing-config/ — platform-wide pricing defaults."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [perm() for perm in PACKAGE_VIEW_PERMS]
        return [perm() for perm in PACKAGE_EDIT_PERMS]

    def get(self, request):
        return Response(PlatformPricingConfigSerializer(PlatformPricingConfig.get_instance()).data)

    def patch(self, request):
        instance = PlatformPricingConfig.get_instance()
        serializer = PlatformPricingConfigSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PackageListCreateAPIView(APIView):
    """GET / POST /api/v1/billing/packages/."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [perm() for perm in PACKAGE_EDIT_PERMS]
        return [perm() for perm in PACKAGE_VIEW_PERMS]

    def get(self, request):
        packages = (
            PlatformPackage.objects.all()
            .prefetch_related("package_features__feature")
            .order_by("sort_order", "price_monthly")
        )
        return Response(PackageSerializer(packages, many=True).data)

    def post(self, request):
        serializer = PackageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            package = serializer.save()
        return Response(
            PackageSerializer(package).data,
            status=status.HTTP_201_CREATED,
        )


class PackageDetailAPIView(APIView):
    """GET / PATCH / PUT / DELETE /api/v1/billing/packages/{pk}/."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [perm() for perm in PACKAGE_VIEW_PERMS]
        return [perm() for perm in PACKAGE_EDIT_PERMS]

    def _get_object(self, pk):
        return get_object_or_404(
            PlatformPackage.objects.prefetch_related("package_features__feature"),
            pk=pk,
        )

    def get(self, request, pk):
        return Response(PackageSerializer(self._get_object(pk)).data)

    def patch(self, request, pk):
        package = self._get_object(pk)
        serializer = PackageSerializer(package, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            package = serializer.save()
        return Response(PackageSerializer(package).data)

    def put(self, request, pk):
        package = self._get_object(pk)
        serializer = PackageSerializer(package, data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            package = serializer.save()
        return Response(PackageSerializer(package).data)

    def delete(self, request, pk):
        package = self._get_object(pk)
        package.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PackageFeaturesAPIView(APIView):
    """GET / PUT /api/v1/billing/packages/{pk}/features/.

    Manage which features a package includes. Idempotent bulk replacement.
    """

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [perm() for perm in PACKAGE_VIEW_PERMS]
        return [perm() for perm in PACKAGE_EDIT_PERMS]

    def get(self, request, pk):
        package = get_object_or_404(PlatformPackage, pk=pk)
        return Response({
            "package_id": package.id,
            "feature_ids": list(
                package.package_features.filter(is_enabled=True)
                .values_list("feature_id", flat=True)
            ),
        })

    def put(self, request, pk):
        package = get_object_or_404(PlatformPackage, pk=pk)
        serializer = PackageFeatureBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted = set(serializer.validated_data["feature_ids"])
        with transaction.atomic():
            existing = {
                pf.feature_id: pf
                for pf in package.package_features.all()
            }
            for fid in wanted:
                pf = existing.get(fid)
                if pf is None:
                    PlatformPackageFeature.objects.create(
                        package=package, feature_id=fid, is_enabled=True
                    )
                elif not pf.is_enabled:
                    pf.is_enabled = True
                    pf.save(update_fields=["is_enabled"])
            for fid, pf in existing.items():
                if fid not in wanted and pf.is_enabled:
                    pf.is_enabled = False
                    pf.save(update_fields=["is_enabled"])
        return Response({"status": "ok", "feature_count": len(wanted)})


class PaymentAPIView(ModelCRUDView):
    """Tenant payment CRUD under /api/v1/billing/payments/."""

    feature_key = 'payments'
    queryset = Payment.objects.select_related('member', 'member__member_package').all().order_by('-payment_date')
    serializer_class = PaymentSerializer
    permission_classes = [HasFeatureMethodPermission]

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['payment_type', 'payment_method', 'payment_status', 'member']
    search_fields = ['member__full_name', 'member__phone_number', 'member__email', 'invoice_no', 'note']
    ordering_fields = ['payment_date', 'amount', 'member__full_name', 'created_at']
    ordering = ['-payment_date']


class PaymentMemberListAPIView(APIView):
    """Member options for Add Payment form."""

    feature_key = 'payments'
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        members = Member.objects.select_related('member_package').all().order_by('full_name')
        return Response(PaymentMemberOptionSerializer(members, many=True).data)


class PaymentStatsAPIView(APIView):
    """Payment summary cards for dashboard payments page."""

    feature_key = 'payments'
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        payments = Payment.objects.all()

        totals = payments.aggregate(
            total_collected=Sum('amount', filter=Q(payment_status=Payment.STATUS_PAID)),
            total_due=Sum('amount', filter=Q(payment_status=Payment.STATUS_DUE)),
            partial_collected=Sum('amount', filter=Q(payment_status=Payment.STATUS_PARTIAL)),
            transaction_count=Count('id'),
            overdue_members=Count('member', filter=Q(payment_status=Payment.STATUS_DUE), distinct=True),
            partial_members=Count('member', filter=Q(payment_status=Payment.STATUS_PARTIAL), distinct=True),
        )

        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_month_start = (month_start - timedelta(days=1)).replace(day=1)

        current_month_collected = payments.filter(
            payment_status=Payment.STATUS_PAID,
            payment_date__gte=month_start,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        previous_month_collected = payments.filter(
            payment_status=Payment.STATUS_PAID,
            payment_date__gte=previous_month_start,
            payment_date__lt=month_start,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        if previous_month_collected > 0:
            trend_percent = float(
                ((current_month_collected - previous_month_collected) / previous_month_collected) * 100
            )
        elif current_month_collected > 0:
            trend_percent = 100.0
        else:
            trend_percent = 0.0

        return Response({
            'total_collected': float(totals['total_collected'] or 0),
            'total_due': float(totals['total_due'] or 0),
            'partial_collected': float(totals['partial_collected'] or 0),
            'transaction_count': totals['transaction_count'] or 0,
            'overdue_members': totals['overdue_members'] or 0,
            'partial_members': totals['partial_members'] or 0,
            'trend_percent': round(trend_percent, 2),
        })


class PDFRenderer(BaseRenderer):
    media_type = 'application/pdf'
    format = 'pdf'
    charset = None
    render_style = 'binary'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b''
        if isinstance(data, bytes):
            return data
        return str(data).encode('utf-8')


class PaymentInvoicePdfAPIView(APIView):
    """Generate branded PDF invoice for manual payments."""

    feature_keys = ['payments', 'payments.invoices']
    permission_classes = [HasFeatureMethodPermission]
    renderer_classes = [PDFRenderer, JSONRenderer]

    def get(self, request, pk):
        payment = get_object_or_404(
            Payment.objects.select_related('member', 'member__member_package'),
            pk=pk,
        )

        if payment.payment_method != 'cash':
            return Response(
                {'detail': 'PDF invoice is available for manual (cash) payments only.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant_name = getattr(getattr(request, 'tenant', None), 'name', None) or 'Fithive Gym'
        generated_by = getattr(request.user, 'full_name', '') or getattr(request.user, 'email', 'System')

        pdf_bytes = _render_payment_invoice_pdf(payment, tenant_name, generated_by)
        invoice_no = payment.invoice_no or f"INV-{payment.id:06d}"
        filename = f"invoice-{invoice_no}.pdf"
        disposition = 'attachment' if request.query_params.get('download') == '1' else 'inline'

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
        return response


def _render_subscription_invoice_pdf(invoice, generated_by: str) -> bytes:
    """Generate a branded PDF for a TenantSubscriptionInvoice (SaaS billing)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from apps.tenancy.models import TenantSubscriptionInvoice

    width, height = A4
    left = 20 * mm
    right = width - (20 * mm)
    top = height - (20 * mm)

    invoice_ref = f"SUB-{invoice.id:06d}"
    tenant_name = _pdf_clean_text(invoice.tenant.name if invoice.tenant else "-")
    package_name = _pdf_clean_text(invoice.package_name or invoice.package_slug or "-")
    amount_str = f"{invoice.currency} {invoice.amount:,.2f}"
    created_at = timezone.localtime(invoice.created_at).strftime("%d %b %Y, %I:%M %p")
    generated_by_name = _pdf_clean_text(generated_by or "System")
    gateway_label = _pdf_clean_text(invoice.gateway_slug)
    transaction_id = _pdf_clean_text(invoice.tran_id)

    def fmt_dt(dt):
        if dt is None:
            return "-"
        return timezone.localtime(dt).strftime("%d %b %Y")

    period = f"{fmt_dt(invoice.period_start)} – {fmt_dt(invoice.period_end)}"

    status_label = {
        TenantSubscriptionInvoice.STATUS_SUCCESS: "Success",
        TenantSubscriptionInvoice.STATUS_PENDING: "Pending",
        TenantSubscriptionInvoice.STATUS_FAILED: "Failed",
        TenantSubscriptionInvoice.STATUS_CANCELLED: "Cancelled",
        TenantSubscriptionInvoice.STATUS_TRIAL: "Trial",
    }.get(invoice.status, invoice.status.title())

    regular_font, bold_font = _get_invoice_fonts()

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    brand_black = colors.HexColor("#101010")
    brand_yellow = colors.HexColor("#FFC733")
    brand_yellow_soft = colors.HexColor("#FFF3C4")
    brand_surface = colors.white
    brand_surface_warm = colors.HexColor("#FFF9EE")
    border_color = colors.HexColor("#E8D39A")
    text_main = colors.HexColor("#171717")
    text_muted = colors.HexColor("#6B6558")

    def draw_field(
        x,
        top_y,
        label,
        value,
        block_width,
        value_font=None,
        value_size=9.6,
        max_lines=1,
    ):
        current_value_font = value_font or bold_font
        pdf.setFillColor(text_muted)
        pdf.setFont(regular_font, 8.4)
        pdf.drawString(x, top_y, label.upper())
        lines = _pdf_wrap_text(pdf, value, block_width, current_value_font, value_size, max_lines=max_lines)
        _pdf_draw_lines(
            pdf,
            x,
            top_y - (4.8 * mm),
            lines,
            current_value_font,
            value_size,
            text_main,
            4.2 * mm,
        )

    pdf.setFillColor(brand_surface)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)

    pdf.setFillColor(brand_black)
    pdf.rect(0, height - (48 * mm), width, 48 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_yellow)
    pdf.rect(0, height - (6 * mm), width, 6 * mm, fill=1, stroke=0)

    pdf.setFillColor(colors.white)
    pdf.setFont(bold_font, 22)
    pdf.drawString(
        left,
        top - (8 * mm),
        _pdf_shorten_text(pdf, tenant_name, right - left - (72 * mm), bold_font, 22),
    )
    pdf.setFont(regular_font, 10)
    pdf.drawString(left, top - (15 * mm), "Subscription Invoice")
    pdf.setFont(regular_font, 9)
    pdf.drawString(left, top - (22 * mm), invoice_ref)

    badge_x = right - (62 * mm)
    pdf.setFillColor(brand_yellow)
    pdf.roundRect(badge_x, top - (18 * mm), 62 * mm, 12 * mm, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_black)
    pdf.setFont(bold_font, 10)
    pdf.drawCentredString(badge_x + (31 * mm), top - (10.8 * mm), "SUBSCRIPTION PAYMENT")
    pdf.setFillColor(colors.white)
    pdf.setFont(regular_font, 9)
    pdf.drawRightString(right, top - (24 * mm), created_at)

    info_top = top - (40 * mm)
    info_height = 54 * mm
    info_width = right - left
    content_x = left + (6 * mm)
    content_width = info_width - (12 * mm)
    column_gap = 10 * mm
    column_width = (content_width - column_gap) / 2
    right_column_x = content_x + column_width + column_gap

    pdf.setFillColor(brand_surface_warm)
    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(1)
    pdf.roundRect(left, info_top - info_height, info_width, info_height, 4 * mm, fill=1, stroke=1)
    pdf.setStrokeColor(brand_yellow)
    pdf.setLineWidth(2)
    pdf.line(left + (6 * mm), info_top - (6 * mm), right - (6 * mm), info_top - (6 * mm))

    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 11)
    pdf.drawString(content_x, info_top - (11 * mm), "Invoice Details")

    row_one_y = info_top - (18 * mm)
    row_two_y = info_top - (31 * mm)
    row_three_y = info_top - (44 * mm)

    draw_field(content_x, row_one_y, "Invoice Ref", invoice_ref, column_width)
    draw_field(right_column_x, row_one_y, "Date", created_at, column_width, value_font=regular_font)
    draw_field(content_x, row_two_y, "Tenant / Gym", tenant_name, column_width)
    draw_field(
        right_column_x,
        row_two_y,
        "Generated By",
        generated_by_name,
        column_width,
        value_font=regular_font,
        max_lines=1,
    )
    draw_field(content_x, row_three_y, "Gateway", gateway_label, column_width, value_font=regular_font)
    draw_field(right_column_x, row_three_y, "Transaction ID", transaction_id, column_width, value_font=regular_font)

    summary_top = info_top - info_height - (12 * mm)
    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 11)
    pdf.drawString(left, summary_top, "Charge Summary")

    table_top = summary_top - (6 * mm)
    table_width = right - left
    package_col = 54 * mm
    period_col = 56 * mm
    status_col = 24 * mm
    amount_col = table_width - package_col - period_col - status_col
    col_one_end = left + package_col
    col_two_end = col_one_end + period_col
    col_three_end = col_two_end + status_col
    header_height = 10 * mm
    row_line_height = 4.2 * mm

    package_lines = _pdf_wrap_text(pdf, package_name, package_col - (8 * mm), bold_font, 10, max_lines=2)
    period_lines = _pdf_wrap_text(pdf, period, period_col - (6 * mm), regular_font, 9.4, max_lines=2)
    status_lines = _pdf_wrap_text(pdf, status_label, status_col - (6 * mm), bold_font, 9.4, max_lines=2)
    body_line_count = max(len(package_lines), len(period_lines), len(status_lines), 1)
    body_height = max(15 * mm, (body_line_count * row_line_height) + (6 * mm))
    total_height = 11 * mm
    table_height = header_height + body_height + total_height
    table_bottom = table_top - table_height
    body_bottom = table_top - header_height - body_height

    pdf.setFillColor(brand_surface)
    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(1)
    pdf.roundRect(left, table_bottom, table_width, table_height, 4 * mm, fill=1, stroke=1)

    pdf.setFillColor(brand_black)
    pdf.roundRect(left, table_top - header_height, table_width, header_height, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(bold_font, 9)
    pdf.drawString(left + (4 * mm), table_top - (6.5 * mm), "Package")
    pdf.drawString(col_one_end + (3 * mm), table_top - (6.5 * mm), "Period")
    pdf.drawString(col_two_end + (3 * mm), table_top - (6.5 * mm), "Status")
    pdf.drawRightString(right - (4 * mm), table_top - (6.5 * mm), "Amount")

    pdf.setStrokeColor(border_color)
    pdf.line(left, table_top - header_height, right, table_top - header_height)
    pdf.line(left, body_bottom, right, body_bottom)
    pdf.line(col_one_end, table_top - header_height, col_one_end, body_bottom)
    pdf.line(col_two_end, table_top - header_height, col_two_end, body_bottom)
    pdf.line(col_three_end, table_top - header_height, col_three_end, body_bottom)

    body_text_top = table_top - header_height - (4.5 * mm)
    _pdf_draw_lines(pdf, left + (4 * mm), body_text_top, package_lines, bold_font, 10, text_main, row_line_height)
    _pdf_draw_lines(pdf, col_one_end + (3 * mm), body_text_top, period_lines, regular_font, 9.4, text_main, row_line_height)
    _pdf_draw_lines(pdf, col_two_end + (3 * mm), body_text_top, status_lines, bold_font, 9.4, text_main, row_line_height)
    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 10)
    pdf.drawRightString(
        right - (4 * mm),
        body_text_top,
        _pdf_shorten_text(pdf, amount_str, amount_col - (5 * mm), bold_font, 10),
    )

    pdf.setFillColor(brand_yellow_soft)
    pdf.rect(left, table_bottom, table_width, total_height, fill=1, stroke=0)
    pdf.setFillColor(brand_black)
    pdf.setFont(bold_font, 11)
    pdf.drawString(left + (4 * mm), table_bottom + (4 * mm), "Total")
    pdf.drawRightString(right - (4 * mm), table_bottom + (4 * mm), amount_str)

    pdf.setFillColor(brand_black)
    pdf.rect(0, 0, width, 18 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_yellow)
    pdf.rect(0, 18 * mm, width, 2 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(regular_font, 9)
    pdf.drawCentredString(
        width / 2,
        7.5 * mm,
        "This is a system-generated subscription invoice. Thank you for choosing Fitssort.",
    )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class SubscriptionInvoicePdfView(APIView):
    """GET /api/v1/billing/subscription/invoices/<pk>/invoice/

    Tenant-facing: returns the PDF for one of the calling tenant's own
    TenantSubscriptionInvoice records.  Reads from the public schema.
    """

    feature_keys = ['payments']
    permission_classes = [HasFeatureMethodPermission]
    renderer_classes = [PDFRenderer, JSONRenderer]

    def get(self, request, pk):
        from apps.tenancy.models import TenantSubscriptionInvoice
        from django_tenants.utils import get_public_schema_name

        tenant = getattr(request, 'tenant', None)
        public_schema = get_public_schema_name()
        with schema_context(public_schema):
            invoice = get_object_or_404(
                TenantSubscriptionInvoice.objects.select_related('tenant'),
                pk=pk,
                tenant=tenant,
            )
            generated_by = getattr(request.user, 'full_name', '') or getattr(request.user, 'email', 'System')
            pdf_bytes = _render_subscription_invoice_pdf(invoice, generated_by)
            invoice_ref = f"SUB-{invoice.id:06d}"

        filename = f"subscription-invoice-{invoice_ref}.pdf"
        disposition = 'attachment' if request.query_params.get('download') == '1' else 'inline'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
        return response


class PlatformSubscriptionInvoicePdfView(APIView):
    """GET /api/v1/billing/subscription/payments/<pk>/invoice/

    Platform-admin facing: returns a PDF for any TenantSubscriptionInvoice.
    """

    permission_classes = [IsPlatformFeaturePermission.require("platform.payments", "view")]
    renderer_classes = [PDFRenderer, JSONRenderer]

    def get(self, request, pk):
        from apps.tenancy.models import TenantSubscriptionInvoice

        invoice = get_object_or_404(
            TenantSubscriptionInvoice.objects.select_related('tenant'),
            pk=pk,
        )
        generated_by = getattr(request.user, 'full_name', '') or getattr(request.user, 'email', 'System')
        pdf_bytes = _render_subscription_invoice_pdf(invoice, generated_by)
        invoice_ref = f"SUB-{invoice.id:06d}"

        filename = f"subscription-invoice-{invoice_ref}.pdf"
        disposition = 'attachment' if request.query_params.get('download') == '1' else 'inline'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
        return response


# ===============================================================
# Platform admin: Payment Gateway management (public schema)
# ===============================================================

GATEWAY_VIEW_PERMS = [IsPlatformFeaturePermission.require("platform.billing", "view")]
GATEWAY_EDIT_PERMS = [IsPlatformFeaturePermission.require("platform.billing", "edit")]


class PaymentGatewayListAPIView(APIView):
    """GET / POST /api/v1/billing/gateways/ — platform admin."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [perm() for perm in GATEWAY_EDIT_PERMS]
        return [perm() for perm in GATEWAY_VIEW_PERMS]

    def get(self, request):
        gateways = PaymentGateway.objects.all().order_by("sort_order", "name")
        return Response(PaymentGatewaySerializer(gateways, many=True).data)

    def post(self, request):
        serializer = PaymentGatewaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        gateway = serializer.save()
        return Response(PaymentGatewaySerializer(gateway).data, status=status.HTTP_201_CREATED)


class PaymentGatewayDetailAPIView(APIView):
    """GET / PATCH / DELETE /api/v1/billing/gateways/<slug>/ — platform admin."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [perm() for perm in GATEWAY_VIEW_PERMS]
        return [perm() for perm in GATEWAY_EDIT_PERMS]

    def _get_object(self, slug):
        return get_object_or_404(PaymentGateway, slug=slug)

    def get(self, request, slug):
        return Response(PaymentGatewaySerializer(self._get_object(slug)).data)

    def patch(self, request, slug):
        gateway = self._get_object(slug)
        serializer = PaymentGatewaySerializer(gateway, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        gateway = serializer.save()
        return Response(PaymentGatewaySerializer(gateway).data)

    def delete(self, request, slug):
        self._get_object(slug).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaymentGatewayToggleAPIView(APIView):
    """POST /api/v1/billing/gateways/<slug>/toggle/ — flip is_enabled_for_tenants."""

    permission_classes = GATEWAY_EDIT_PERMS

    def post(self, request, slug):
        gateway = get_object_or_404(PaymentGateway, slug=slug)
        gateway.is_enabled_for_tenants = not gateway.is_enabled_for_tenants
        gateway.save(update_fields=["is_enabled_for_tenants", "updated_at"])
        return Response(PaymentGatewaySerializer(gateway).data)


class PaymentGatewaySetDefaultView(APIView):
    """POST /api/v1/billing/gateways/<slug>/set-default-subscription/

    Marks one gateway as the default for SaaS subscription billing.
    Clears the flag on all other gateways atomically.
    """

    permission_classes = GATEWAY_EDIT_PERMS

    def post(self, request, slug):
        gateway = get_object_or_404(PaymentGateway, slug=slug)
        with transaction.atomic():
            PaymentGateway.objects.exclude(slug=slug).update(is_default_for_subscriptions=False)
            gateway.is_default_for_subscriptions = True
            gateway.save(update_fields=["is_default_for_subscriptions", "updated_at"])
        return Response(PaymentGatewaySerializer(gateway).data)


class PlatformSubscriptionPaymentsView(APIView):
    """GET /api/v1/billing/subscription/payments/ — platform-admin payment overview.

    Returns all TenantSubscriptionInvoice records across all tenants along with
    aggregate stats (total revenue, count by status).  Gated by the
    `platform.payments` platform module permission.
    """

    permission_classes = [IsPlatformFeaturePermission.require("platform.payments", "view")]

    def get(self, request):
        from apps.tenancy.models import TenantSubscriptionInvoice, Tenant
        from .serializers import TenantSubscriptionInvoiceSerializer

        # Build queryset with tenant info denormalised
        invoices_qs = (
            TenantSubscriptionInvoice.objects
            .select_related("tenant")
            .order_by("-created_at")
        )

        # Optional filter params
        status_filter = request.GET.get("status", "").strip()
        search = request.GET.get("search", "").strip()
        if status_filter:
            invoices_qs = invoices_qs.filter(status=status_filter)
        if search:
            invoices_qs = invoices_qs.filter(
                Q(tenant__name__icontains=search)
                | Q(tran_id__icontains=search)
                | Q(package_name__icontains=search)
            )

        invoices = list(invoices_qs)

        # Aggregate stats
        all_invoices = TenantSubscriptionInvoice.objects.all()
        total_revenue = (
            all_invoices.filter(status=TenantSubscriptionInvoice.STATUS_SUCCESS)
            .aggregate(total=Sum("amount"))["total"] or 0
        )
        count_by_status = {
            row["status"]: row["count"]
            for row in all_invoices.values("status").annotate(count=Count("id"))
        }
        unique_paying_tenants = (
            all_invoices.filter(status=TenantSubscriptionInvoice.STATUS_SUCCESS)
            .values("tenant_id").distinct().count()
        )

        serialized = TenantSubscriptionInvoiceSerializer(invoices, many=True).data
        # Attach tenant name to each item
        rows = []
        for inv, data in zip(invoices, serialized):
            row = dict(data)
            row["tenant_name"] = inv.tenant.name if inv.tenant else ""
            row["tenant_schema"] = inv.tenant.schema_name if inv.tenant else ""
            rows.append(row)

        return Response({
            "stats": {
                "total_revenue": str(total_revenue),
                "total_payments": all_invoices.count(),
                "successful_payments": count_by_status.get(TenantSubscriptionInvoice.STATUS_SUCCESS, 0),
                "failed_payments": count_by_status.get(TenantSubscriptionInvoice.STATUS_FAILED, 0),
                "pending_payments": count_by_status.get(TenantSubscriptionInvoice.STATUS_PENDING, 0),
                "unique_paying_tenants": unique_paying_tenants,
            },
            "results": rows,
        })


# ===============================================================
# Subscription payment callbacks (public schema)
# These are called by SSLCommerz after a tenant subscription payment.
# ===============================================================

def _process_subscription_callback(request, *, tran_id=None):
    """Shared handler for subscription success/fail/cancel POST callbacks.

    Returns (invoice, redirect_url) so the caller can redirect the browser.
    """
    from apps.tenancy.models import TenantSubscriptionInvoice

    public_frontend = getattr(settings, "PUBLIC_FRONTEND_URL", "") or getattr(settings, "FRONTEND_BASE_URL", "")

    if tran_id is None:
        tran_id = request.POST.get("tran_id") or request.GET.get("tran_id", "")

    if not tran_id:
        return None, f"{public_frontend}/subscription/fail?reason=missing_tran_id"

    try:
        with transaction.atomic():
            invoice = TenantSubscriptionInvoice.objects.select_for_update().filter(tran_id=tran_id).first()
            if invoice is None:
                return None, f"{public_frontend}/subscription/fail?reason=not_found"

            if invoice.status == TenantSubscriptionInvoice.STATUS_SUCCESS:
                # Already processed — idempotent; rebuild success params
                from urllib.parse import urlencode as _ue
                _tenant = invoice.tenant
                _domain = (
                    _tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first() or ""
                )
                _scheme = getattr(settings, "TENANT_FRONTEND_SCHEME", "http")
                _port = getattr(settings, "TENANT_FRONTEND_PORT", "")
                _host = f"{_domain}:{_port}" if (_domain and _port) else _domain
                _login_url = f"{_scheme}://{_host}/login" if _domain else ""
                _params = _ue({
                    "tran_id": tran_id,
                    "login_url": _login_url,
                    "package": invoice.package_name or invoice.package_slug or "",
                    "amount": str(invoice.amount),
                })
                return invoice, f"{public_frontend}/subscription/success?{_params}"

            val_id = request.POST.get("val_id") or request.GET.get("val_id", "")
            new_status = TenantSubscriptionInvoice.STATUS_FAILED

            if val_id:
                try:
                    gw = PaymentGateway.objects.filter(slug=invoice.gateway_slug).first()
                    if gw:
                        creds = gw.platform_credentials or {}
                        svc = get_gateway(
                            invoice.gateway_slug,
                            credentials=creds,
                            is_sandbox=gw.is_sandbox,
                            success_url="",
                            fail_url="",
                            cancel_url="",
                            ipn_url="",
                        )
                        result = svc.validate(val_id)
                        invoice.gateway_response = result
                        invoice.val_id = val_id
                        if result.get("status") == "VALID":
                            new_status = TenantSubscriptionInvoice.STATUS_SUCCESS
                            invoice.validated_at = timezone.now()
                except Exception:
                    pass

            invoice.status = new_status
            invoice.save(update_fields=["status", "val_id", "validated_at", "gateway_response", "updated_at"])

            # On success, activate the tenant subscription
            if new_status == TenantSubscriptionInvoice.STATUS_SUCCESS:
                tenant = invoice.tenant
                tenant.is_trial = False
                tenant.status = "active"
                tenant.subscription_start = timezone.now()
                tenant.subscription_end = invoice.period_end
                tenant.save(update_fields=["is_trial", "status", "subscription_start", "subscription_end", "updated_at"])

    except Exception:
        return None, f"{public_frontend}/subscription/fail?reason=error"

    if new_status == TenantSubscriptionInvoice.STATUS_SUCCESS:
        from urllib.parse import urlencode
        tenant = invoice.tenant
        tenant_domain = (
            tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first() or ""
        )
        scheme = getattr(settings, "TENANT_FRONTEND_SCHEME", "http")
        port = getattr(settings, "TENANT_FRONTEND_PORT", "")
        if tenant_domain:
            host = f"{tenant_domain}:{port}" if port else tenant_domain
            login_url = f"{scheme}://{host}/login"
        else:
            login_url = ""
        params = urlencode({
            "tran_id": tran_id,
            "login_url": login_url,
            "package": invoice.package_name or invoice.package_slug or "",
            "amount": str(invoice.amount),
        })
        return invoice, f"{public_frontend}/subscription/success?{params}"
    return invoice, f"{public_frontend}/subscription/fail?tran_id={tran_id}"


class SubscriptionPaymentIPNView(APIView):
    """POST /api/v1/billing/subscription/ipn/ — SSLCommerz IPN for subscription billing."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _process_subscription_callback(request)
        return Response({"status": "ok"})


class SubscriptionPaymentSuccessView(APIView):
    """GET|POST /api/v1/billing/subscription/success/ — SSLCommerz success redirect."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        _, redirect_url = _process_subscription_callback(request, tran_id=request.GET.get("tran_id"))
        return redirect(redirect_url)

    def post(self, request):
        _, redirect_url = _process_subscription_callback(request)
        return redirect(redirect_url)


class SubscriptionPaymentFailView(APIView):
    """GET|POST /api/v1/billing/subscription/fail/ — SSLCommerz fail redirect."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        public_frontend = getattr(settings, "PUBLIC_FRONTEND_URL", "") or getattr(settings, "FRONTEND_BASE_URL", "")
        tran_id = request.GET.get("tran_id", "")
        _process_subscription_callback(request, tran_id=tran_id)
        return redirect(f"{public_frontend}/subscription/fail?tran_id={tran_id}")

    def post(self, request):
        tran_id = request.POST.get("tran_id", "")
        public_frontend = getattr(settings, "PUBLIC_FRONTEND_URL", "") or getattr(settings, "FRONTEND_BASE_URL", "")
        _process_subscription_callback(request, tran_id=tran_id)
        return redirect(f"{public_frontend}/subscription/fail?tran_id={tran_id}")


class SubscriptionPaymentCancelView(APIView):
    """GET|POST /api/v1/billing/subscription/cancel/ — SSLCommerz cancel redirect."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        public_frontend = getattr(settings, "PUBLIC_FRONTEND_URL", "") or getattr(settings, "FRONTEND_BASE_URL", "")
        tran_id = request.GET.get("tran_id", "")
        from apps.tenancy.models import TenantSubscriptionInvoice
        TenantSubscriptionInvoice.objects.filter(
            tran_id=tran_id,
            status=TenantSubscriptionInvoice.STATUS_PENDING,
        ).update(status=TenantSubscriptionInvoice.STATUS_CANCELLED)
        return redirect(f"{public_frontend}/subscription/cancel?tran_id={tran_id}")

    def post(self, request):
        public_frontend = getattr(settings, "PUBLIC_FRONTEND_URL", "") or getattr(settings, "FRONTEND_BASE_URL", "")
        tran_id = request.POST.get("tran_id", "")
        from apps.tenancy.models import TenantSubscriptionInvoice
        TenantSubscriptionInvoice.objects.filter(
            tran_id=tran_id,
            status=TenantSubscriptionInvoice.STATUS_PENDING,
        ).update(status=TenantSubscriptionInvoice.STATUS_CANCELLED)
        return redirect(f"{public_frontend}/subscription/cancel?tran_id={tran_id}")


class SubscriptionInvoiceListView(APIView):
    """GET /api/v1/billing/subscription/invoices/ — tenant's SaaS subscription invoice history.

    Queries the public schema (where TenantSubscriptionInvoice lives) using the
    current request's tenant identity set by django-tenants middleware.
    """

    feature_key = "payments"
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        from apps.tenancy.models import TenantSubscriptionInvoice
        from django_tenants.utils import get_public_schema_name
        from .serializers import TenantSubscriptionInvoiceSerializer

        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response([])

        public_schema = get_public_schema_name()
        with schema_context(public_schema):
            invoices = (
                TenantSubscriptionInvoice.objects
                .filter(tenant=tenant)
                .order_by("-created_at")
            )
            return Response(TenantSubscriptionInvoiceSerializer(invoices, many=True).data)


# ===============================================================
# Tenant: gateway configuration (tenant schema)
# ===============================================================

class TenantGatewayConfigView(ModelCRUDView):
    """GET / POST / PATCH / DELETE /api/v1/billing/payments/gateways/ (and /<pk>/).

    Manages per-tenant SSLCommerz / other gateway credentials.
    Only slugs that are enabled in the public schema are accepted.
    """

    feature_key = "payments.gateways"
    permission_classes = [HasFeatureMethodPermission]
    queryset = TenantPaymentGateway.objects.all()
    serializer_class = TenantPaymentGatewaySerializer

    def _is_slug_allowed(self, slug: str) -> bool:
        with schema_context("public"):
            return PaymentGateway.objects.filter(slug=slug, is_enabled_for_tenants=True).exists()

    def post(self, request, *args, **kwargs):
        slug = request.data.get("gateway_slug", "")
        if not self._is_slug_allowed(slug):
            return Response(
                {"detail": f"Gateway '{slug}' is not enabled by the platform."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Upsert by slug so tenant admins can safely re-save credentials.
        existing = TenantPaymentGateway.objects.filter(gateway_slug=slug).first()
        if existing is not None:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            return Response(self.get_serializer(instance).data, status=status.HTTP_200_OK)

        return super().post(request, *args, **kwargs)


def _is_gateway_credentials_complete(gateway: PaymentGateway, credentials: dict) -> bool:
    required_keys = [
        field.get("key")
        for field in (gateway.config_schema or [])
        if field.get("required") and field.get("key")
    ]
    return all(str((credentials or {}).get(key, "")).strip() for key in required_keys)


def _build_tenant_backend_base_url(request) -> str:
    """Build a tenant callback base URL using tenant domain and backend scheme/port."""
    fallback = request.build_absolute_uri("/").rstrip("/")
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return fallback

    primary_domain = tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first()
    if not primary_domain:
        return fallback

    backend_base = (getattr(settings, "BACKEND_BASE_URL", "") or "").strip().rstrip("/")
    if not backend_base:
        return f"{request.scheme}://{primary_domain}"

    parsed = urlparse(backend_base)
    scheme = parsed.scheme or request.scheme
    port_suffix = f":{parsed.port}" if parsed.port and ":" not in primary_domain else ""
    return f"{scheme}://{primary_domain}{port_suffix}"


# ===============================================================
# Tenant: available gateways (for AddPaymentDialog dropdown)
# ===============================================================

class AvailableGatewaysView(APIView):
    """GET /api/v1/billing/payments/available-gateways/

    Returns the list of platform-enabled gateways with a flag indicating
    whether this tenant has already configured credentials for each.
    """

    feature_key = "payments"
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        with schema_context("public"):
            enabled_gateways = list(
                PaymentGateway.objects.filter(is_enabled_for_tenants=True)
                .order_by("sort_order", "name")
            )

        configured_rows = {
            row.gateway_slug: row
            for row in TenantPaymentGateway.objects.filter(is_active=True)
        }

        result = [
            {
                "slug": gateway.slug,
                "name": gateway.name,
                "is_configured": (
                    gateway.slug in configured_rows
                    and _is_gateway_credentials_complete(
                        gateway,
                        configured_rows[gateway.slug].credentials,
                    )
                ),
            }
            for gateway in enabled_gateways
        ]
        return Response(AvailableGatewaySerializer(result, many=True).data)


# ===============================================================
# Tenant: initiate online payment
# ===============================================================

class PaymentInitiateView(APIView):
    """POST /api/v1/billing/payments/initiate/

    Creates a PaymentTransaction and returns the gateway redirect URL.
    The frontend immediately redirects the user to gateway_url.
    """

    feature_key = "payments"
    permission_classes = [HasFeatureMethodPermission]

    def post(self, request):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment_id = serializer.validated_data["payment_id"]
        gateway_slug = serializer.validated_data["gateway_slug"]

        payment = get_object_or_404(
            Payment.objects.select_related("member"),
            pk=payment_id,
        )

        try:
            tenant_gw = TenantPaymentGateway.objects.get(gateway_slug=gateway_slug, is_active=True)
        except TenantPaymentGateway.DoesNotExist:
            return Response(
                {"detail": f"Gateway '{gateway_slug}' is not configured for this gym."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with schema_context("public"):
            gateway = PaymentGateway.objects.filter(
                slug=gateway_slug,
                is_enabled_for_tenants=True,
            ).first()

        if gateway is None:
            return Response(
                {"detail": f"Gateway '{gateway_slug}' is not enabled by the platform."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not _is_gateway_credentials_complete(gateway, tenant_gw.credentials):
            required_keys = [
                field.get("key")
                for field in (gateway.config_schema or [])
                if field.get("required") and field.get("key")
            ]
            missing_keys = [
                key for key in required_keys
                if not str((tenant_gw.credentials or {}).get(key, "")).strip()
            ]
            return Response(
                {
                    "detail": "Gateway credentials are incomplete for this gym.",
                    "missing_fields": missing_keys,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        tran_id = f"TXN-{payment.id}-{uuid.uuid4().hex[:8].upper()}"

        # Build absolute callback URLs
        base = _build_tenant_backend_base_url(request)
        prefix = f"{base}/api/v1/billing/payments"
        success_url = f"{prefix}/success/"
        fail_url = f"{prefix}/fail/"
        cancel_url = f"{prefix}/cancel/"
        ipn_url = f"{prefix}/ipn/"

        with transaction.atomic():
            tx = PaymentTransaction.objects.create(
                tran_id=tran_id,
                gateway_slug=gateway_slug,
                amount=payment.amount,
                currency="BDT",
                status=PaymentTransaction.STATUS_INIT,
                source_payment=payment,
            )

        svc = get_gateway(
            gateway_slug,
            tenant_gw.credentials,
            tenant_gw.is_sandbox,
            success_url=success_url,
            fail_url=fail_url,
            cancel_url=cancel_url,
            ipn_url=ipn_url,
        )

        try:
            result = svc.initiate(tx)
        except ValueError as exc:
            tx.status = PaymentTransaction.STATUS_FAILED
            tx.gateway_response = {"error": str(exc)}
            tx.save(update_fields=["status", "gateway_response", "updated_at"])
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        tx.status = PaymentTransaction.STATUS_PENDING
        tx.gateway_response = result.get("raw", {})
        tx.save(update_fields=["status", "gateway_response", "updated_at"])

        return Response({"gateway_url": result["gateway_url"], "tran_id": tran_id})


# ===============================================================
# Tenant: SSLCommerz IPN + browser callbacks
# ===============================================================

def _process_gateway_callback(tran_id: str, val_id: str, raw_amount: str) -> PaymentTransaction | None:
    """Shared logic: validate with SSLCommerz and update transaction + payment.

    Uses select_for_update to prevent IPN/success callback race conditions.
    Returns the updated PaymentTransaction or None if tran_id is not found.
    """
    try:
        with transaction.atomic():
            # Do not join nullable source_payment in a FOR UPDATE query,
            # otherwise PostgreSQL raises NotSupportedError on outer joins.
            tx = PaymentTransaction.objects.select_for_update().get(tran_id=tran_id)
            existing_gateway_response = tx.gateway_response if isinstance(tx.gateway_response, dict) else {}

            # Idempotent: already resolved
            if tx.status in (PaymentTransaction.STATUS_SUCCESS, PaymentTransaction.STATUS_FAILED,
                             PaymentTransaction.STATUS_CANCELLED):
                return tx

            try:
                tenant_gw = TenantPaymentGateway.objects.get(
                    gateway_slug=tx.gateway_slug, is_active=True
                )
            except TenantPaymentGateway.DoesNotExist:
                return tx

            svc = get_gateway(
                tx.gateway_slug,
                tenant_gw.credentials,
                tenant_gw.is_sandbox,
                success_url="", fail_url="", cancel_url="", ipn_url="",
            )

            try:
                validation = svc.validate(val_id)
            except ValueError:
                tx.status = PaymentTransaction.STATUS_FAILED
                tx.save(update_fields=["status", "updated_at"])
                return tx

            gw_status = (validation.get("status") or "").upper()
            is_valid = gw_status == "VALID"

            # Verify amount matches (guard against amount tampering)
            try:
                validated_amount = Decimal(str(validation.get("amount", "0")))
                amount_ok = abs(validated_amount - tx.amount) < Decimal("1.00")
            except Exception:
                amount_ok = False

            if is_valid and amount_ok:
                tx.status = PaymentTransaction.STATUS_SUCCESS
                tx.val_id = val_id
                tx.validated_at = timezone.now()
                tx.gateway_response = {
                    **existing_gateway_response,
                    "validation": validation,
                }
                tx.save(update_fields=["status", "val_id", "validated_at", "gateway_response", "updated_at"])

                if tx.source_payment_id:
                    payment = (
                        Payment.objects
                        .select_for_update()
                        .filter(pk=tx.source_payment_id)
                        .first()
                    )
                    if payment is not None:
                        payment.payment_status = Payment.STATUS_PAID
                        payment.is_paid = True
                        payment.save(update_fields=["payment_status", "is_paid", "updated_at"])
            else:
                tx.status = PaymentTransaction.STATUS_FAILED
                tx.gateway_response = {
                    **existing_gateway_response,
                    "validation": validation,
                }
                tx.save(update_fields=["status", "gateway_response", "updated_at"])

    except PaymentTransaction.DoesNotExist:
        return None

    return tx


def _request_value(request, key: str, default: str = "") -> str:
    """Read callback params from either POST body or querystring."""
    value = request.data.get(key)
    if value in (None, ""):
        value = request.query_params.get(key)
    if value in (None, ""):
        return default
    return str(value)


def _build_tenant_frontend_base_url(request) -> str:
    """Build frontend base URL using tenant primary domain when available."""
    tenant = getattr(request, "tenant", None)
    if tenant is not None and getattr(tenant, "schema_name", "") != get_public_schema_name():
        domain = tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first()
        if domain:
            scheme = (getattr(settings, "TENANT_FRONTEND_SCHEME", "http") or "http").strip().lower()
            port = str(getattr(settings, "TENANT_FRONTEND_PORT", "") or "").strip()
            host = f"{domain}:{port}" if port and ":" not in domain else domain
            return f"{scheme}://{host}".rstrip("/")

    return (
        getattr(settings, "FRONTEND_BASE_URL", "").strip().rstrip("/")
        or getattr(settings, "PUBLIC_FRONTEND_URL", "").strip().rstrip("/")
    )


def _payment_result_redirect_url(request, tx: PaymentTransaction | None, outcome: str, tran_id: str) -> str:
    frontend = _build_tenant_frontend_base_url(request)
    public_frontend = getattr(settings, "PUBLIC_FRONTEND_URL", "").rstrip("/") or frontend

    flow = ""
    if tx is not None and isinstance(tx.gateway_response, dict):
        flow = str(tx.gateway_response.get("flow", "")).strip().lower()

    if flow == "public_member_signup" or tran_id.upper().startswith("PUBREG-"):
        target_base = frontend or public_frontend
        return f"{target_base}/register?payment_status={outcome}&tran_id={tran_id}"

    return f"{frontend}/payments/{outcome}?tran_id={tran_id}"


class PaymentIPNView(APIView):
    """POST /api/v1/billing/payments/ipn/ — SSLCommerz server-to-server IPN.

    Must be AllowAny because SSLCommerz hits it directly without auth headers.
    The transaction is validated against the SSLCommerz API (not just IPN data)
    before any status update is applied.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        tran_id = request.data.get("tran_id", "")
        val_id = request.data.get("val_id", "")
        raw_amount = request.data.get("amount", "0")

        if not tran_id:
            return Response({"detail": "Missing tran_id"}, status=status.HTTP_400_BAD_REQUEST)

        _process_gateway_callback(tran_id, val_id, raw_amount)
        return Response({"status": "received"})


class PaymentSuccessView(APIView):
    """POST /api/v1/billing/payments/success/ — browser redirect after successful payment."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        tran_id = _request_value(request, "tran_id", "")
        val_id = _request_value(request, "val_id", "")
        raw_amount = _request_value(request, "amount", "0")

        tx = _process_gateway_callback(tran_id, val_id, raw_amount)

        return redirect(_payment_result_redirect_url(request, tx, "success", tran_id))


class PaymentFailView(APIView):
    """POST /api/v1/billing/payments/fail/ — browser redirect after failed payment."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        tran_id = _request_value(request, "tran_id", "")
        tx = None

        try:
            with transaction.atomic():
                tx = PaymentTransaction.objects.select_for_update().get(tran_id=tran_id)
                if tx.status == PaymentTransaction.STATUS_PENDING:
                    tx.status = PaymentTransaction.STATUS_FAILED
                    tx.save(update_fields=["status", "updated_at"])
        except PaymentTransaction.DoesNotExist:
            pass

        return redirect(_payment_result_redirect_url(request, tx, "fail", tran_id))


class PaymentCancelView(APIView):
    """POST /api/v1/billing/payments/cancel/ — browser redirect after cancelled payment."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        tran_id = _request_value(request, "tran_id", "")
        tx = None

        try:
            with transaction.atomic():
                tx = PaymentTransaction.objects.select_for_update().get(tran_id=tran_id)
                if tx.status == PaymentTransaction.STATUS_PENDING:
                    tx.status = PaymentTransaction.STATUS_CANCELLED
                    tx.save(update_fields=["status", "updated_at"])
        except PaymentTransaction.DoesNotExist:
            pass

        return redirect(_payment_result_redirect_url(request, tx, "cancel", tran_id))

