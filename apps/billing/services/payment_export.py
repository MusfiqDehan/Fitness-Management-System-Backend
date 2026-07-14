"""Build CSV / XLSX / PDF exports for filtered member payments."""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from django.http import HttpResponse
from rest_framework.exceptions import ValidationError

EXPORT_MAX_ROWS = 10_000
EXPORT_HEADERS = [
    "ID",
    "Member",
    "Phone",
    "Email",
    "Package",
    "Amount",
    "Method",
    "Status",
    "Payment Date",
    "Invoice",
    "Coverage Months",
]


def _row_from_payment(payment) -> list[str]:
    member = payment.member
    package = ""
    if member and member.member_package_id:
        package = getattr(member.member_package, "name", "") or ""
    coverage = ", ".join(payment.coverage_months or [])
    return [
        str(payment.id),
        getattr(member, "full_name", "") or "",
        getattr(member, "phone_number", "") or "",
        getattr(member, "email", "") or "",
        package,
        str(payment.amount),
        payment.get_payment_method_display(),
        payment.get_payment_status_display(),
        payment.payment_date.isoformat() if payment.payment_date else "",
        payment.invoice_no or "",
        coverage,
    ]


def _collect_rows(queryset):
    count = queryset.count()
    if count > EXPORT_MAX_ROWS:
        raise ValidationError(
            {
                "detail": (
                    f"Export exceeds maximum of {EXPORT_MAX_ROWS} rows "
                    f"({count} matched). Narrow filters and try again."
                )
            }
        )
    payments = list(
        queryset.select_related("member", "member__member_package").order_by("id")
    )
    rows = [_row_from_payment(p) for p in payments]
    total = sum((Decimal(str(p.amount)) for p in payments), Decimal("0.00"))
    return rows, total


def build_payment_export_response(queryset, *, fmt: str, filter_label: str = "") -> HttpResponse:
    fmt = (fmt or "csv").lower().strip()
    if fmt not in {"csv", "xlsx", "pdf"}:
        raise ValidationError({"format": "Must be csv, xlsx, or pdf."})

    rows, total = _collect_rows(queryset)
    total_str = f"{total:.2f}"
    label = filter_label or "Filtered payments"

    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_HEADERS)
        writer.writerows(rows)
        writer.writerow([])
        writer.writerow(["TOTAL", "", "", "", "", total_str, "", "", "", "", label])
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="payments-export.csv"'
        return response

    if fmt == "xlsx":
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Payments"
        ws.append(EXPORT_HEADERS)
        for row in rows:
            ws.append(row)
        ws.append([])
        ws.append(["TOTAL", "", "", "", "", total_str, "", "", "", "", label])
        out = io.BytesIO()
        wb.save(out)
        response = HttpResponse(
            out.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="payments-export.xlsx"'
        return response

    # PDF summary
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    width, height = landscape(A4)
    pdf = canvas.Canvas(out, pagesize=landscape(A4))
    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"Payments export — {label}")
    y -= 20
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Rows: {len(rows)}   Total amount: {total_str}")
    y -= 24
    pdf.setFont("Helvetica-Bold", 8)
    header_line = " | ".join(EXPORT_HEADERS[:6])
    pdf.drawString(40, y, header_line)
    y -= 14
    pdf.setFont("Helvetica", 7)
    for row in rows[:200]:
        if y < 40:
            pdf.showPage()
            y = height - 40
            pdf.setFont("Helvetica", 7)
        pdf.drawString(40, y, " | ".join(row[:6]))
        y -= 11
    if len(rows) > 200:
        y -= 10
        pdf.drawString(40, y, f"... and {len(rows) - 200} more rows (see CSV/XLSX for full detail)")
    y -= 20
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, max(y, 40), f"TOTAL: {total_str}")
    pdf.save()
    response = HttpResponse(out.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="payments-export.pdf"'
    return response
