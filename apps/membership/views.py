"""Tenant-scoped membership API views.

Handles all member and package lifecycle operations including:
- Member CRUD, invite, activate/deactivate, soft delete
- Package CRUD, activate/deactivate, soft delete, highlight
- Public self-registration from landing page
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Q
from django.db import transaction
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django_filters.rest_framework import DjangoFilterBackend
from django_tenants.utils import schema_context
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse
import logging
import uuid
import secrets
import csv
import io
import os

from .models import Member, MemberPackage, Payment, Attendance, GymClass, GymSchedule
from .services.class_catalog import ClassCatalogService, MandatoryTrainerRequired, ClassCatalogServiceError
from apps.billing.serializers import PaymentSerializer
from .serializers import (
    MemberSerializer,
    MemberPublicSerializer,
    MemberPackageSerializer,
    MemberPackagePublicSerializer,
    MemberMinimalSerializer,
    AttendanceSerializer,
    GymClassSerializer,
    GymScheduleSerializer,
    UnifiedClassSerializer,
    UnifiedScheduleSerializer,
)
from utils.base_view import ModelCRUDView
from utils.list_mixins import BranchScopedListMixin, SearchFilterSortPaginationMixin
from utils.limits import branch_capacity_exceeded, total_capacity_exceeded
from utils.tenancy_helpers import (
    get_branch_manager_scope_ids as _branch_manager_scope_ids,
    scope_queryset_by_branch_access,
)
from apps.access.permissions import HasFeatureMethodPermission
from apps.crm.email_delivery import resolve_tenant_mail_route
from apps.gym_branch.models import Branch
from apps.tenancy.models import PaymentGateway
from apps.billing.models import TenantPaymentGateway, PaymentTransaction
from apps.billing.services import get_gateway

logger = logging.getLogger(__name__)


_MEMBER_IMPORT_ALLOWED_EXTENSIONS = {'.csv', '.xls', '.xlsx', '.xlx'}


def _normalize_import_header(value):
    return str(value or '').strip().lower().replace(' ', '_').replace('-', '_')


def _coerce_str(value):
    if value is None:
        return ''
    return str(value).strip()


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    normalized = _coerce_str(value).lower()
    if normalized in {'1', 'true', 'yes', 'y', 'active'}:
        return True
    if normalized in {'0', 'false', 'no', 'n', 'inactive'}:
        return False
    return None


def _as_row_dict(headers, values):
    payload = {}
    for index, header in enumerate(headers):
        if not header:
            continue
        payload[header] = values[index] if index < len(values) else None
    return payload


def _read_member_import_rows(uploaded):
    filename = uploaded.name or ''
    ext = os.path.splitext(filename.lower())[1]
    if ext not in _MEMBER_IMPORT_ALLOWED_EXTENSIONS:
        raise ValueError('Only CSV, XLS, XLX, and XLSX files are supported.')

    raw = uploaded.read()
    rows = []

    if ext == '.csv':
        text = raw.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError('CSV header row is missing.')
        for index, row in enumerate(reader, start=2):
            normalized = {_normalize_import_header(k): v for k, v in (row or {}).items()}
            rows.append((index, normalized))
        return rows

    if ext in {'.xlsx', '.xlx'}:
        try:
            import openpyxl
        except ImportError as exc:
            raise ValueError('XLSX import dependency is missing (openpyxl).') from exc

        workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        raw_headers = next(iterator, None)
        if not raw_headers:
            raise ValueError('Spreadsheet header row is missing.')
        headers = [_normalize_import_header(v) for v in raw_headers]
        for index, values in enumerate(iterator, start=2):
            rows.append((index, _as_row_dict(headers, list(values or []))))
        return rows

    try:
        import xlrd
    except ImportError as exc:
        raise ValueError('XLS import dependency is missing (xlrd).') from exc

    workbook = xlrd.open_workbook(file_contents=raw)
    sheet = workbook.sheet_by_index(0)
    if sheet.nrows < 1:
        raise ValueError('Spreadsheet header row is missing.')
    headers = [_normalize_import_header(v) for v in sheet.row_values(0)]
    for row_idx in range(1, sheet.nrows):
        values = sheet.row_values(row_idx)
        rows.append((row_idx + 1, _as_row_dict(headers, values)))
    return rows


def _row_pick(row, keys):
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _resolve_package_id(raw_value, package_name_map):
    if raw_value is None:
        return None
    as_text = _coerce_str(raw_value)
    if not as_text:
        return None
    if as_text.isdigit():
        return int(as_text)
    return package_name_map.get(as_text.lower())


def _resolve_branch_id(raw_value, branch_name_map):
    if raw_value is None:
        return None
    as_text = _coerce_str(raw_value)
    if not as_text:
        return None
    if as_text.isdigit():
        return int(as_text)
    return branch_name_map.get(as_text.lower())


def _build_member_invite_url(request, token: str) -> str:
    return f"{request.scheme}://{request.get_host()}/register?token={token}"


def _send_member_invitation_email(member: Member, request, invited_by=None, force_new_token: bool = False) -> str | None:
    """Prepare invitation token and send invitation email. Returns invite URL if sent."""
    if not member.email:
        return None

    now = timezone.now()
    has_valid_token = bool(
        member.invitation_token
        and member.invitation_expires_at
        and member.invitation_expires_at > now
    )

    if force_new_token or not has_valid_token:
        member.invitation_token = secrets.token_urlsafe(48)
        member.invitation_sent_at = now
        member.invitation_expires_at = now + timedelta(days=7)

    if invited_by is not None:
        member.invited_by = invited_by

    member.is_active = False
    member.save(update_fields=[
        'invitation_token', 'invitation_sent_at', 'invitation_expires_at',
        'invited_by', 'is_active',
    ])

    invite_url = _build_member_invite_url(request, member.invitation_token)
    company_name = getattr(getattr(request, 'tenant', None), 'name', None) or 'our gym'
    invited_by_name = (
        getattr(invited_by, 'full_name', None) or getattr(invited_by, 'email', None)
        if invited_by is not None else None
    )

    context = {
        'member_name': member.full_name or '',
        'invited_by_name': invited_by_name,
        'company_name': company_name,
        'invitation_url': invite_url,
        'expires_at': member.invitation_expires_at,
    }
    html_body = render_to_string('membership/emails/member_invitation_email.html', context)
    fallback_text = (
        f"Hi {member.full_name or 'there'},\n\n"
        f"You have been invited to complete your member registration at {company_name}. "
        f"Use the link below to verify your invitation and set your password:\n\n"
        f"{invite_url}\n\n"
        f"This link expires on {member.invitation_expires_at}."
    )
    tenant = getattr(request, 'tenant', None) or getattr(invited_by, 'tenant', None)
    from_email, connection = resolve_tenant_mail_route(tenant)
    email = EmailMultiAlternatives(
        subject=f"Complete your member registration at {company_name}",
        body=fallback_text,
        from_email=from_email,
        to=[member.email],
        connection=connection,
    )
    email.attach_alternative(html_body, 'text/html')

    try:
        email.send(fail_silently=False)
    except Exception as first_exc:
        fallback_email = EmailMultiAlternatives(
            subject=f"Complete your member registration at {company_name}",
            body=fallback_text,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@gym.local'),
            to=[member.email],
        )
        fallback_email.attach_alternative(html_body, 'text/html')
        try:
            fallback_email.send(fail_silently=False)
        except Exception as fallback_exc:
            logger.error(
                "Member invitation email send failed: primary=%s fallback=%s member_id=%s",
                first_exc,
                fallback_exc,
                member.id,
            )
            raise

    return invite_url


def _is_gateway_credentials_complete(gateway: PaymentGateway, credentials: dict) -> bool:
    required_keys = [
        field.get('key')
        for field in (gateway.config_schema or [])
        if field.get('required') and field.get('key')
    ]
    return all(str((credentials or {}).get(key, '')).strip() for key in required_keys)


def _build_tenant_backend_base_url(request) -> str:
    fallback = request.build_absolute_uri('/').rstrip('/')
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return fallback

    primary_domain = tenant.domains.filter(is_primary=True).values_list('domain', flat=True).first()
    if not primary_domain:
        return fallback

    backend_base = (getattr(settings, 'BACKEND_BASE_URL', '') or '').strip().rstrip('/')
    if not backend_base:
        return f"{request.scheme}://{primary_domain}"

    parsed = urlparse(backend_base)
    scheme = parsed.scheme or request.scheme
    port_suffix = f":{parsed.port}" if parsed.port and ':' not in primary_domain else ''
    return f"{scheme}://{primary_domain}{port_suffix}"


# =============================================================================
# MEMBER PACKAGE VIEW
# =============================================================================

class MemberPackageActions:
    """Action handlers for MemberPackage."""
    actions = {
        'activate':   lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_active', True),
        'deactivate':  lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_active', False),
        'publish':     lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_published', True),
        'unpublish':   lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_published', False),
        'highlight':   lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_highlighted'),
    }

    def _toggle_flag(self, model, pk, field, value=None):
        try:
            obj = model.objects.get(pk=pk)
        except model.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if value is None:
            value = not getattr(obj, field)
        setattr(obj, field, value)
        obj.save(update_fields=[field])
        if field == 'is_highlighted':
            msg = 'highlighted' if value else 'unhighlighted'
        elif field == 'is_published':
            msg = 'published' if value else 'unpublished'
        else:
            msg = 'activated' if value else 'deactivated'
        return Response({'message': msg, field: value})


class MemberPackageView(SearchFilterSortPaginationMixin, MemberPackageActions, ModelCRUDView):
    """Handles all MemberPackage operations and actions."""
    feature_key = 'members.packages'
    queryset = MemberPackage.objects.all().order_by('display_order', 'name')
    serializer_class = MemberPackageSerializer
    permission_classes = [HasFeatureMethodPermission]
    filterset_fields = ['is_active', 'is_published', 'is_highlighted', 'package_type']
    search_fields = ['name', 'description']
    ordering_fields = ['id', 'display_order', 'name', 'price', 'created_at']
    ordering = ['id']


# =============================================================================
# MEMBER VIEW
# =============================================================================

class MemberActions:
    """Action handlers for Member."""
    actions = {
        'activate':   lambda self, req, pk: self._toggle_flag(Member, pk, 'is_active', True),
        'deactivate': lambda self, req, pk: self._toggle_flag(Member, pk, 'is_active', False),
        'restore':    lambda self, req, pk: self._restore(pk),
        'resend_invitation': lambda self, req, pk: self._resend_invitation(req, pk),
    }

    def _scope_members_queryset(self, include_deleted=False):
        base_qs = Member.all_objects if include_deleted else Member.objects
        scope_ids = _branch_manager_scope_ids(getattr(self.request, 'user', None))
        if scope_ids is None:
            return base_qs
        if not scope_ids:
            return base_qs.none()
        return base_qs.filter(branch_id__in=scope_ids)

    def _toggle_flag(self, model, pk, field, value):
        try:
            obj = self._scope_members_queryset().get(pk=pk)
        except model.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        setattr(obj, field, value)
        obj.save(update_fields=[field])
        return Response({'message': 'Activated' if value else 'Deactivated', field: value})

    def _restore(self, pk):
        try:
            member = self._scope_members_queryset(include_deleted=True).get(pk=pk)
        except Member.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not member.is_deleted:
            return Response({'error': 'Member is not deleted'}, status=status.HTTP_400_BAD_REQUEST)
        member.restore()
        return Response({'message': 'Member restored', 'is_deleted': False})

    def _resend_invitation(self, request, pk):
        try:
            member = self._scope_members_queryset().get(pk=pk)
        except Member.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        if not member.email:
            return Response(
                {'detail': 'Member does not have an email address.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not member.invitation_token:
            return Response(
                {'detail': 'Member has already completed registration.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        inviter = (
            request.user
            if getattr(request, 'user', None) and request.user.is_authenticated
            else None
        )
        try:
            invite_url = _send_member_invitation_email(
                member,
                request,
                invited_by=inviter,
                force_new_token=True,
            )
        except Exception as exc:
            return Response(
                {'error': f'Failed to send invitation email: {str(exc)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'message': 'Invitation resent successfully',
            'invitation_sent': bool(invite_url),
            'invite_url': invite_url,
        })


class MemberView(BranchScopedListMixin, MemberActions, ModelCRUDView):
    """Handles all Member operations and actions."""
    feature_key = 'members'
    queryset = Member.objects.select_related('member_package', 'branch').all()
    serializer_class = MemberSerializer
    permission_classes = [HasFeatureMethodPermission]
    branch_scope_field = 'branch_id'
    filterset_fields = ['is_active', 'membership_type', 'payment_status', 'branch', 'member_package']
    search_fields = [
        'full_name',
        'phone_number',
        'email',
        'branch__name',
        'member_package__name',
        'card_id',
        'fingerprint_id',
    ]
    ordering_fields = [
        'id',
        'full_name',
        'phone_number',
        'email',
        'date_of_birth',
        'branch__name',
        'member_package__name',
        'is_active',
        'payment_status',
        'start_date',
        'end_date',
        'created_at',
    ]
    ordering = ['id']

    def get_queryset(self):
        queryset = super().get_queryset()
        return self.scope_branch_queryset(queryset)

    def _create(self, request):
        payload = request.data.copy()
        scope_ids = _branch_manager_scope_ids(request.user)
        if scope_ids is not None:
            if not scope_ids:
                return Response(
                    {'detail': 'No managed branch is configured for this account.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            incoming_branch_id = payload.get('branch_id') or payload.get('branch')
            if incoming_branch_id is None:
                payload['branch'] = scope_ids[0]
            else:
                try:
                    incoming_branch_int = int(incoming_branch_id)
                except (TypeError, ValueError):
                    return Response({'detail': 'Invalid branch selection.'}, status=status.HTTP_400_BAD_REQUEST)
                if incoming_branch_int not in scope_ids:
                    return Response(
                        {'detail': 'You can only create members in your managed branch.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        total_limit_error = total_capacity_exceeded(
            Member.objects,
            'max_users',
            limit_type='members',
        )
        if total_limit_error is not None:
            return Response(total_limit_error, status=status.HTTP_403_FORBIDDEN)

        branch_id = payload.get('branch_id') or payload.get('branch')
        branch_limit_error = branch_capacity_exceeded(
            Member.objects,
            branch_id,
            'max_members_per_branch',
            limit_type='members_per_branch',
        )
        if branch_limit_error is not None:
            return Response(branch_limit_error, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)

        inviter = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None

        try:
            with transaction.atomic():
                instance = serializer.save()
                invite_url = _send_member_invitation_email(
                    instance,
                    request,
                    invited_by=inviter,
                    force_new_token=True,
                )
        except Exception as exc:
            return Response(
                {'error': f'Failed to send invitation email: {str(exc)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        payload = self.get_serializer(instance).data
        payload['invitation_sent'] = bool(invite_url)
        if invite_url:
            payload['invite_url'] = invite_url

        return Response(payload, status=status.HTTP_201_CREATED)


class MemberImportAPIView(APIView):
    """POST /api/v1/membership/members/import/ — import members from CSV/XLS/XLSX."""
    feature_key = 'members'
    permission_classes = [HasFeatureMethodPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response(
                {'detail': "No file provided. Send multipart form data with field name 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed_rows = _read_member_import_rows(uploaded)
        except UnicodeDecodeError:
            return Response({'detail': 'Could not decode the uploaded CSV file.'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not parsed_rows:
            return Response({'detail': 'No data rows found in uploaded file.'}, status=status.HTTP_400_BAD_REQUEST)

        scope_ids = _branch_manager_scope_ids(request.user)
        if scope_ids is not None and not scope_ids:
            return Response(
                {'detail': 'No managed branch is configured for this account.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        package_name_map = {
            p['name'].strip().lower(): p['id']
            for p in MemberPackage.objects.values('id', 'name')
            if p['name']
        }
        branch_name_map = {
            b['name'].strip().lower(): b['id']
            for b in Branch.objects.values('id', 'name')
            if b['name']
        }

        created_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []

        for row_number, row in parsed_rows:
            if not any(_coerce_str(value) for value in row.values()):
                skipped_count += 1
                continue

            phone_number = _coerce_str(_row_pick(row, ['phone_number', 'phone', 'mobile', 'contact_number']))
            if not phone_number:
                errors.append({'row': row_number, 'error': 'phone_number is required.'})
                skipped_count += 1
                continue

            existing = Member.all_objects.filter(phone_number=phone_number).first()

            payload = {
                'phone_number': phone_number,
                'full_name': _coerce_str(_row_pick(row, ['full_name', 'name', 'member_name']))
                or (existing.full_name if existing else phone_number),
            }

            optional_text_fields = {
                'email': ['email', 'mail'],
                'gender': ['gender', 'sex'],
                'date_of_birth': ['date_of_birth', 'dob', 'birth_date'],
                'address': ['address'],
                'membership_type': ['membership_type', 'member_type', 'type'],
                'start_date': ['start_date', 'join_date', 'joining_date'],
                'emergency_contact_name': ['emergency_contact_name', 'emergency_name'],
                'emergency_contact_phone': ['emergency_contact_phone', 'emergency_phone'],
                'notes': ['notes', 'note'],
                'payment_method': ['payment_method'],
                'payment_status': ['payment_status'],
                'card_id': ['card_id'],
                'fingerprint_id': ['fingerprint_id'],
            }

            for field, aliases in optional_text_fields.items():
                value = _row_pick(row, aliases)
                if value is None:
                    continue
                payload[field] = _coerce_str(value)

            membership_type = payload.get('membership_type') or (existing.membership_type if existing else 'monthly')
            membership_type = _coerce_str(membership_type).lower()
            if membership_type not in {'package', 'monthly'}:
                errors.append({'row': row_number, 'error': "membership_type must be 'package' or 'monthly'."})
                skipped_count += 1
                continue
            payload['membership_type'] = membership_type

            package_raw = _row_pick(row, ['member_package_id', 'package_id', 'package', 'member_package'])
            package_id = _resolve_package_id(package_raw, package_name_map)
            if membership_type == 'package':
                if package_id is None and existing and existing.member_package_id:
                    package_id = existing.member_package_id
                if package_id is None:
                    errors.append({'row': row_number, 'error': 'Package membership requires member_package_id or package name.'})
                    skipped_count += 1
                    continue
                payload['member_package_id'] = package_id
            else:
                payload['member_package_id'] = None

            branch_raw = _row_pick(row, ['branch', 'branch_id', 'branch_name'])
            branch_id = _resolve_branch_id(branch_raw, branch_name_map)
            if branch_id is None and scope_ids is not None:
                branch_id = scope_ids[0]
            if branch_id is None and existing and existing.branch_id:
                branch_id = existing.branch_id

            if scope_ids is not None:
                if branch_id is None:
                    branch_id = scope_ids[0]
                if branch_id not in scope_ids:
                    errors.append({'row': row_number, 'error': 'Row branch is outside your managed branch scope.'})
                    skipped_count += 1
                    continue

            if branch_id is not None:
                payload['branch'] = branch_id

            is_active_raw = _row_pick(row, ['is_active', 'active', 'status'])
            is_active = _coerce_bool(is_active_raw) if is_active_raw is not None else None
            if is_active is not None:
                payload['is_active'] = is_active

            if existing is None:
                total_limit_error = total_capacity_exceeded(
                    Member.objects,
                    'max_users',
                    limit_type='members',
                )
                if total_limit_error is not None:
                    errors.append({'row': row_number, 'error': total_limit_error.get('detail', 'Member plan limit exceeded.')})
                    skipped_count += 1
                    continue

                branch_limit_error = branch_capacity_exceeded(
                    Member.objects,
                    branch_id,
                    'max_members_per_branch',
                    limit_type='members_per_branch',
                )
                if branch_limit_error is not None:
                    errors.append({'row': row_number, 'error': branch_limit_error.get('detail', 'Branch member limit exceeded.')})
                    skipped_count += 1
                    continue

            try:
                with transaction.atomic():
                    if existing is None:
                        serializer = MemberSerializer(data=payload)
                    else:
                        if existing.is_deleted:
                            existing.restore()
                        serializer = MemberSerializer(existing, data=payload, partial=True)
                    serializer.is_valid(raise_exception=True)
                    serializer.save()
            except Exception as exc:
                errors.append({'row': row_number, 'error': str(exc)})
                skipped_count += 1
                continue

            if existing is None:
                created_count += 1
            else:
                updated_count += 1

        total_rows = len(parsed_rows)
        result = {
            'total_rows': total_rows,
            'created_count': created_count,
            'updated_count': updated_count,
            'skipped_count': skipped_count,
            'errors': errors[:100],
        }

        if created_count == 0 and updated_count == 0:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


# =============================================================================
# MEMBER LOOKUP (for device linking)
# =============================================================================

class MemberLookupAPIView(APIView):
    """GET /api/v1/membership/members/lookup/?search= — search members for device linking."""
    feature_key = 'members'
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        search = request.query_params.get('search', '')
        members = Member.objects.filter(
            Q(full_name__icontains=search) | Q(phone_number__icontains=search)
        ).order_by('full_name')[:20]
        serializer = MemberMinimalSerializer(members, many=True)
        return Response(serializer.data)


# =============================================================================
# PUBLIC PACKAGES (for landing page)
# =============================================================================

class PublicPackageListAPIView(APIView):
    """GET /api/v1/membership/public/packages/ — public list of published packages."""
    permission_classes = [AllowAny]

    def get(self, request):
        packages = MemberPackage.objects.filter(is_active=True, is_published=True).order_by('-is_highlighted', 'display_order', 'name')
        serializer = MemberPackagePublicSerializer(packages, many=True)
        return Response(serializer.data)


class PublicPackageRetrieveAPIView(APIView):
    """GET /api/v1/membership/public/packages/{pk}/ — public retrieve a package."""
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            package = MemberPackage.objects.get(pk=pk, is_active=True, is_published=True)
        except MemberPackage.DoesNotExist:
            return Response({'error': 'Package not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = MemberPackagePublicSerializer(package)
        return Response(serializer.data)


# =============================================================================
# PUBLIC MEMBER REGISTRATION (from landing page)
# =============================================================================

class PublicMemberRegistrationAPIView(APIView):
    """POST /api/v1/membership/public/register/ — public member self-registration."""
    permission_classes = [AllowAny]

    def post(self, request):
        if not request.data.get('email'):
            return Response({'error': 'Email is required for registration'}, status=status.HTTP_400_BAD_REQUEST)

        start_checkout = str(request.data.get('start_checkout', '')).strip().lower() in ('1', 'true', 'yes')
        gateway_slug = str(request.data.get('gateway_slug', 'sslcommerz')).strip().lower() or 'sslcommerz'

        if start_checkout and gateway_slug != 'sslcommerz':
            return Response(
                {'detail': "Only 'sslcommerz' is supported for public package checkout."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        gateway = None
        tenant_gateway = None
        if start_checkout:
            with schema_context('public'):
                gateway = PaymentGateway.objects.filter(
                    slug=gateway_slug,
                    is_enabled_for_tenants=True,
                ).first()

            if gateway is None:
                return Response(
                    {'detail': f"Gateway '{gateway_slug}' is not enabled by the platform."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            tenant_gateway = TenantPaymentGateway.objects.filter(
                gateway_slug=gateway_slug,
                is_active=True,
            ).first()
            if tenant_gateway is None:
                return Response(
                    {'detail': f"Gateway '{gateway_slug}' is not configured for this gym."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not _is_gateway_credentials_complete(gateway, tenant_gateway.credentials):
                required_keys = [
                    field.get('key')
                    for field in (gateway.config_schema or [])
                    if field.get('required') and field.get('key')
                ]
                missing_keys = [
                    key for key in required_keys
                    if not str((tenant_gateway.credentials or {}).get(key, '')).strip()
                ]
                return Response(
                    {
                        'detail': 'Gateway credentials are incomplete for this gym.',
                        'missing_fields': missing_keys,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = MemberPublicSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        member = None
        invite_url = None
        package_payment = None
        tx = None

        try:
            with transaction.atomic():
                member = serializer.save(is_active=False)
                invite_url = _send_member_invitation_email(
                    member,
                    request,
                    invited_by=None,
                    force_new_token=True,
                )

                if start_checkout:
                    package_payment = (
                        Payment.objects
                        .filter(member=member, payment_type='package')
                        .order_by('-created_at')
                        .first()
                    )
                    if package_payment is None and member.member_package is not None:
                        package_payment = Payment.objects.create(
                            member=member,
                            payment_type='package',
                            amount=member.member_package.price,
                        )

                    if package_payment is None:
                        raise ValueError('Could not prepare package payment for checkout.')

                    package_payment.payment_method = 'sslcommerz'
                    package_payment.payment_status = Payment.STATUS_DUE
                    package_payment.is_paid = False
                    package_payment.save(update_fields=['payment_method', 'payment_status', 'is_paid', 'updated_at'])

                    tran_id = f"PUBREG-{member.id}-{uuid.uuid4().hex[:8].upper()}"
                    tx = PaymentTransaction.objects.create(
                        tran_id=tran_id,
                        gateway_slug=gateway_slug,
                        amount=Decimal(package_payment.amount),
                        currency='BDT',
                        status=PaymentTransaction.STATUS_INIT,
                        source_payment=package_payment,
                        gateway_response={
                            'flow': 'public_member_signup',
                            'member_id': member.id,
                        },
                    )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {'error': f'Failed to send invitation email: {str(exc)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if start_checkout and tx is not None and package_payment is not None and tenant_gateway is not None:
            base = _build_tenant_backend_base_url(request)
            prefix = f"{base}/api/v1/billing/payments"
            success_url = f"{prefix}/success/"
            fail_url = f"{prefix}/fail/"
            cancel_url = f"{prefix}/cancel/"
            ipn_url = f"{prefix}/ipn/"

            svc = get_gateway(
                gateway_slug,
                tenant_gateway.credentials,
                tenant_gateway.is_sandbox,
                success_url=success_url,
                fail_url=fail_url,
                cancel_url=cancel_url,
                ipn_url=ipn_url,
            )

            try:
                result = svc.initiate(tx)
            except ValueError as exc:
                tx.status = PaymentTransaction.STATUS_FAILED
                tx.gateway_response = {
                    'flow': 'public_member_signup',
                    'member_id': member.id,
                    'error': str(exc),
                }
                tx.save(update_fields=['status', 'gateway_response', 'updated_at'])
                return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

            tx.status = PaymentTransaction.STATUS_PENDING
            tx.gateway_response = {
                'flow': 'public_member_signup',
                'member_id': member.id,
                'raw': result.get('raw', {}),
            }
            tx.save(update_fields=['status', 'gateway_response', 'updated_at'])

            return Response({
                'message': 'Registration received. Redirecting to secure checkout.',
                'member_id': member.id,
                'invitation_sent': bool(invite_url),
                'invite_url': invite_url,
                'gateway_url': result['gateway_url'],
                'tran_id': tx.tran_id,
            }, status=status.HTTP_201_CREATED)

        return Response({
            'message': 'Registration received. Please check your email to verify and set password.',
            'member_id': member.id,
            'invitation_sent': bool(invite_url),
            'invite_url': invite_url,
        }, status=status.HTTP_201_CREATED)


# =============================================================================
# MEMBER ANALYTICS
# =============================================================================

class MemberAnalyticsAPIView(APIView):
    """GET /api/v1/membership/members/analytics/ — member stats for overview dashboard."""
    feature_key = 'members'
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        from django.db.models import Count, Q
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        today = now.date()
        in_7_days = today + timedelta(days=7)
        month_start = today.replace(day=1)

        base_qs = scope_queryset_by_branch_access(
            Member.objects.all(),
            request.user,
            branch_field='branch_id',
            branch_filter_id=request.query_params.get('branch'),
        )

        total = base_qs.count()
        active = base_qs.filter(is_active=True, end_date__gte=today).count()
        expired = base_qs.filter(end_date__lt=today).count()
        expiring_soon = base_qs.filter(end_date__gte=today, end_date__lte=in_7_days).count()
        new_this_month = base_qs.filter(created_at__date__gte=month_start).count()

        # Trend: last month new members
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)
        last_month_end = month_start - timedelta(days=1)
        new_last_month = base_qs.filter(
            created_at__date__gte=last_month_start,
            created_at__date__lte=last_month_end
        ).count()

        # Gender distribution
        gender_dist = {
            'male': base_qs.filter(gender='male').count(),
            'female': base_qs.filter(gender='female').count(),
            'other': base_qs.exclude(gender__in=['male', 'female', '']).count(),
        }

        # Package distribution
        package_dist = (
            base_qs
            .values('member_package__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        package_dist_dict = {p['member_package__name'] or 'No Package': p['count'] for p in package_dist}

        return Response({
            'total': total, 'active': active, 'expired': expired, 'expiring_soon': expiring_soon,
            'new_this_month': new_this_month, 'new_last_month': new_last_month,
            'gender_dist': gender_dist, 'package_dist': package_dist_dict,
        })


# =============================================================================
# MEMBER INVITATION
# =============================================================================

class InviteMemberAPIView(APIView):
    """POST /api/v1/membership/members/invite/ — send invitation email to a prospective member."""
    feature_key = 'members'
    permission_classes = [HasFeatureMethodPermission]

    def post(self, request):
        email = request.data.get('email')
        full_name = request.data.get('full_name', '')
        phone_number = request.data.get('phone_number')
        member_package_id = request.data.get('member_package_id')
        branch_id = request.data.get('branch_id') or request.data.get('branch')

        scope_ids = _branch_manager_scope_ids(request.user)
        if scope_ids is not None:
            if not scope_ids:
                return Response(
                    {'detail': 'No managed branch is configured for this account.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if branch_id is None:
                branch_id = scope_ids[0]
            else:
                try:
                    branch_id_int = int(branch_id)
                except (TypeError, ValueError):
                    return Response({'detail': 'Invalid branch selection.'}, status=status.HTTP_400_BAD_REQUEST)
                if branch_id_int not in scope_ids:
                    return Response(
                        {'detail': 'You can only invite members to your managed branch.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                branch_id = branch_id_int

        if not email:
            return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not phone_number:
            return Response({'error': 'Phone number is required'}, status=status.HTTP_400_BAD_REQUEST)

        total_limit_error = total_capacity_exceeded(
            Member.objects,
            'max_users',
            limit_type='members',
        )
        if total_limit_error is not None:
            return Response(total_limit_error, status=status.HTTP_403_FORBIDDEN)

        # Enforce per-branch member limit for the tenant's current plan.
        limit_error = branch_capacity_exceeded(
            Member.objects, branch_id, 'max_members_per_branch'
            , limit_type='members_per_branch'
        )
        if limit_error is not None:
            return Response(limit_error, status=status.HTTP_403_FORBIDDEN)

        # Check for existing member with same phone or email
        if Member.objects.filter(phone_number=phone_number).exists():
            return Response({'error': 'A member with this phone number already exists'}, status=status.HTTP_400_BAD_REQUEST)
        if email and Member.objects.filter(email=email).exists():
            return Response({'error': 'A member with this email already exists'}, status=status.HTTP_400_BAD_REQUEST)

        # Check for existing pending invitation
        existing = Member.objects.filter(
            phone_number=phone_number,
            invitation_token__isnull=False,
            invitation_expires_at__gt=timezone.now(),
        ).first()
        if existing:
            return Response({'error': 'An invitation has already been sent to this phone number'}, status=status.HTTP_400_BAD_REQUEST)

        inviter = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None

        try:
            with transaction.atomic():
                member = Member.objects.create(
                    full_name=full_name or email.split('@')[0],
                    phone_number=phone_number,
                    email=email,
                    member_package_id=member_package_id,
                    branch_id=branch_id,
                    is_active=False,
                )
                invite_url = _send_member_invitation_email(
                    member,
                    request,
                    invited_by=inviter,
                    force_new_token=True,
                )
        except Exception as exc:
            return Response({'error': f'Failed to send email: {str(exc)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'message': 'Invitation sent successfully',
            'member_id': member.id,
            'invite_url': invite_url,
        }, status=status.HTTP_201_CREATED)


class VerifyInvitationAPIView(APIView):
    """POST /api/v1/membership/public/verify-invitation/ — verify invitation token."""
    permission_classes = [AllowAny]

    def post(self, request):
        from django.utils import timezone
        token = request.data.get('token')
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            member = Member.objects.get(invitation_token=token)
        except Member.DoesNotExist:
            return Response({'error': 'Invalid or expired token'}, status=status.HTTP_404_NOT_FOUND)

        if not member.invitation_expires_at or member.invitation_expires_at < timezone.now():
            return Response({'error': 'This invitation link has expired'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'valid': True,
            'member_id': member.id,
            'full_name': member.full_name,
            'email': member.email,
            'phone_number': member.phone_number,
            'package': member.member_package.name if member.member_package else None,
        })


class CompleteMemberRegistrationAPIView(APIView):
    """POST /api/v1/membership/public/complete-registration/ — set password and activate member."""
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        password = request.data.get('password')
        full_name = request.data.get('full_name')

        if not token or not password:
            return Response({'error': 'Token and password are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            member = Member.objects.get(invitation_token=token)
        except Member.DoesNotExist:
            return Response({'error': 'Invalid or expired token'}, status=status.HTTP_404_NOT_FOUND)

        if not member.invitation_expires_at or member.invitation_expires_at < timezone.now():
            return Response({'error': 'Invitation has expired'}, status=status.HTTP_400_BAD_REQUEST)

        if not member.email:
            return Response({'error': 'Invited member does not have an email address'}, status=status.HTTP_400_BAD_REQUEST)

        tenant = getattr(getattr(member, 'invited_by', None), 'tenant', None) or getattr(request, 'tenant', None)
        if tenant is None:
            return Response({'error': 'Could not determine tenant for this invitation'}, status=status.HTTP_400_BAD_REQUEST)

        # Create auth User for member
        from apps.identity.models import User

        if User.objects.filter(email=member.email).exists():
            return Response({'error': 'A user account with this email already exists'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Create user account
            user = User.objects.create(
                email=member.email,
                full_name=full_name or member.full_name,
                role='student',
                tenant=tenant,
                email_verified=True,
                password_set_at=timezone.now(),
            )
            user.set_password(password)
            user.save()

            # Activate member
            member.invitation_token = None
            member.invitation_sent_at = None
            member.invitation_expires_at = None
            member.invited_by = None
            member.is_active = True
            if full_name:
                member.full_name = full_name
            member.save(update_fields=[
                'invitation_token', 'invitation_sent_at', 'invitation_expires_at',
                'invited_by', 'is_active', 'full_name',
            ])

        try:
            from apps.reminder.utils import create_notification
            # Broadcast to admins: a new member joined
            create_notification(
                notification_type='member_onboarded',
                title=f'New member joined: {member.full_name or member.email}',
                actor_name=member.full_name or '',
                actor_email=member.email or '',
                target_type='member',
                target_id=str(member.id),
            )
            # Personal to the new member: welcome message
            create_notification(
                notification_type='welcome_member',
                title=f'Welcome, {member.full_name or member.email}!',
                message='Your gym membership is now active. Start exploring your dashboard.',
                recipient=user,
                target_type='member',
                target_id=str(member.id),
            )
        except Exception:
            pass  # Notifications are best-effort

        return Response({'message': 'Registration completed successfully', 'member_id': member.id})


# =============================================================================
# PAYMENT VIEW
# =============================================================================

class PaymentView(BranchScopedListMixin, ModelCRUDView):
    """Handles all Payment operations."""
    feature_key = 'payments'
    queryset = Payment.objects.select_related('member', 'member__member_package', 'member__branch').all().order_by('id')
    serializer_class = PaymentSerializer
    permission_classes = [HasFeatureMethodPermission]
    branch_scope_field = 'member__branch_id'

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant"] = getattr(self.request, "tenant", None)
        context["actor"] = self.request.user
        return context
    filterset_fields = ['payment_type', 'payment_method', 'payment_status', 'member']
    search_fields = ['member__full_name', 'member__phone_number', 'member__email', 'invoice_no', 'note']
    ordering_fields = [
        'id',
        'payment_date',
        'amount',
        'member__full_name',
        'member__phone_number',
        'member__email',
        'member__member_package__name',
        'payment_method',
        'payment_status',
        'created_at',
    ]
    ordering = ['id']

    def get_queryset(self):
        queryset = super().get_queryset()
        from_date = self.request.query_params.get('from_date')
        to_date = self.request.query_params.get('to_date')

        if from_date:
            queryset = queryset.filter(payment_date__date__gte=from_date)
        if to_date:
            queryset = queryset.filter(payment_date__date__lte=to_date)

        return queryset


# =============================================================================
# MEMBER SELF-SERVICE: MY SUBSCRIPTION
# =============================================================================

class MemberMySubscriptionAPIView(APIView):
    """GET /api/v1/membership/my-subscription/ — returns the authenticated member's
    own subscription details and payment history. Accessible by student/member role."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.core.exceptions import ObjectDoesNotExist
        try:
            member = request.user.member
        except ObjectDoesNotExist:
            return Response(
                {'detail': 'No member profile linked to this account.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        member_data = MemberSerializer(member).data
        payments = Payment.objects.filter(member=member, is_deleted=False).order_by('-payment_date')
        payments_data = PaymentSerializer(payments, many=True).data

        return Response({
            'member': member_data,
            'payments': payments_data,
        })


# =============================================================================
# ATTENDANCE VIEW
# =============================================================================

class AttendanceView(BranchScopedListMixin, ModelCRUDView):
    """Handles all Attendance operations."""
    feature_key = 'attendance'
    queryset = Attendance.objects.select_related('member', 'member__branch').all().order_by('id')
    serializer_class = AttendanceSerializer
    permission_classes = [HasFeatureMethodPermission]
    branch_scope_field = 'member__branch_id'
    filterset_fields = ['entry_method', 'member']
    search_fields = ['member__full_name', 'device_id']
    ordering_fields = ['id', 'check_in_time', 'check_out_time', 'member__full_name', 'created_at']
    ordering = ['id']


# =============================================================================
# PAYMENT ANALYTICS VIEW
# =============================================================================

class PaymentAnalyticsAPIView(APIView):
    """GET /membership/payments/analytics/?period=today|weekly|monthly"""
    permission_classes = [HasFeatureMethodPermission]
    feature_key = 'payments'

    def get(self, request):
        from django.db.models import Sum, Count
        from django.utils.timezone import now
        from datetime import timedelta, date as dt_date
        from decimal import Decimal

        period = request.query_params.get('period', 'monthly').lower()
        today = now().date()

        if period == 'today':
            start = today
        elif period == 'weekly':
            start = today - timedelta(days=7)
        elif period == 'monthly':
            start = today.replace(day=1)
        else:
            start = today.replace(day=1)

        qs = scope_queryset_by_branch_access(
            Payment.objects.filter(payment_date__date__gte=start, is_deleted=False),
            request.user,
            branch_field='member__branch_id',
            branch_filter_id=request.query_params.get('branch'),
        )

        total_collected = qs.filter(payment_status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        total_due = qs.filter(payment_status='due').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        total_partial = qs.filter(payment_status='partial').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        transaction_count = qs.count()

        # Previous period for trend
        delta = (today - start).days or 1
        prev_start = start - timedelta(days=delta)
        prev_qs = scope_queryset_by_branch_access(
            Payment.objects.filter(payment_date__date__gte=prev_start, payment_date__date__lt=start, is_deleted=False),
            request.user,
            branch_field='member__branch_id',
            branch_filter_id=request.query_params.get('branch'),
        )
        prev_collected = prev_qs.filter(payment_status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        if prev_collected > 0:
            trend_pct = round(float((total_collected - prev_collected) / prev_collected * 100), 1)
        else:
            trend_pct = 0.0

        # Payment method breakdown
        method_qs = qs.values('payment_method').annotate(total=Sum('amount'), count=Count('id'))
        payment_methods = [
            {'method': r['payment_method'], 'total': float(r['total'] or 0), 'count': r['count']}
            for r in method_qs
        ]

        # Package breakdown
        pkg_qs = qs.values('member__member_package__name').annotate(total=Sum('amount'), count=Count('id'))
        package_breakdown = [
            {'package': r['member__member_package__name'] or 'No Package', 'total': float(r['total'] or 0), 'count': r['count']}
            for r in pkg_qs
        ]

        # Revenue trend bars
        revenue_trend = self._build_revenue_trend(period, today)

        # Overdue member count
        overdue_count = Member.objects.filter(
            is_deleted=False, is_active=True,
            end_date__lt=today
        ).count()

        return Response({
            'period': period,
            'total_collected': float(total_collected),
            'total_due': float(total_due),
            'total_partial': float(total_partial),
            'transaction_count': transaction_count,
            'trend_pct': trend_pct,
            'overdue_count': overdue_count,
            'payment_methods': payment_methods,
            'package_breakdown': package_breakdown,
            'revenue_trend': revenue_trend,
        })

    def _build_revenue_trend(self, period, today):
        from django.db.models import Sum
        from datetime import timedelta
        from decimal import Decimal

        results = []
        if period == 'today':
            for hour in [6, 9, 12, 15, 18, 21]:
                label = f"{hour}{'a' if hour < 12 else 'p'}"
                qs = Payment.objects.filter(
                    payment_date__date=today,
                    payment_date__hour__gte=hour,
                    payment_date__hour__lt=hour + 3,
                    payment_status='paid', is_deleted=False,
                )
                total = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
                results.append({'label': label, 'value': float(total)})
        elif period == 'weekly':
            for i in range(7):
                d = today - timedelta(days=6 - i)
                qs = Payment.objects.filter(payment_date__date=d, payment_status='paid', is_deleted=False)
                total = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
                results.append({'label': d.strftime('%a'), 'value': float(total)})
        else:
            import calendar
            year, month = today.year, today.month
            num_months = 12
            for m in range(1, num_months + 1):
                qs = Payment.objects.filter(payment_date__year=year, payment_date__month=m, payment_status='paid', is_deleted=False)
                total = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
                results.append({'label': calendar.month_abbr[m], 'value': float(total)})
        return results


# =============================================================================
# GYM CLASS + SCHEDULE VIEWS
# =============================================================================

class GymClassView(ModelCRUDView):
    """CRUD for gym-level class catalog. GET/POST /membership/gym-classes/ etc."""
    feature_key = 'classes'
    queryset = GymClass.objects.filter(is_deleted=False).select_related(
        'trainer_profile__user', 'trainer_class'
    ).order_by('name')
    serializer_class = GymClassSerializer
    permission_classes = [HasFeatureMethodPermission]

    def _catalog_service(self, request):
        return ClassCatalogService(user=request.user)

    def _create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            instance = self._catalog_service(request).create_gym_class_from_admin(serializer.validated_data)
        except MandatoryTrainerRequired as exc:
            return Response({'trainer_profile': [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except ClassCatalogServiceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def _update(self, pk, request, partial):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            updated = self._catalog_service(request).update_gym_class_from_admin(instance, serializer.validated_data)
        except MandatoryTrainerRequired as exc:
            return Response({'trainer_profile': [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except ClassCatalogServiceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(updated).data)


class GymScheduleView(ModelCRUDView):
    """CRUD for weekly gym schedule. GET/POST /membership/gym-schedules/ etc."""
    feature_key = 'classes'
    queryset = GymSchedule.objects.filter(is_deleted=False).select_related(
        'gym_class', 'trainer_profile__user', 'trainer_schedule'
    ).order_by('day_of_week', 'start_time')
    serializer_class = GymScheduleSerializer
    permission_classes = [HasFeatureMethodPermission]

    def _catalog_service(self, request):
        return ClassCatalogService(user=request.user)

    def _create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            instance = self._catalog_service(request).create_gym_schedule_from_admin(serializer.validated_data)
        except MandatoryTrainerRequired as exc:
            return Response({'trainer_profile': [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except ClassCatalogServiceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)


class UnifiedClassListAPIView(APIView):
    """GET /membership/unified-classes/ — merged tenant class catalog."""
    feature_key = 'classes'
    permission_classes = [IsAuthenticated, HasFeatureMethodPermission]

    def get(self, request):
        classes = GymClass.objects.filter(is_deleted=False).select_related(
            'trainer_profile__user', 'trainer_class'
        ).order_by('name')
        serializer = UnifiedClassSerializer(classes, many=True)
        return Response(serializer.data)


class UnifiedScheduleListAPIView(APIView):
    """GET /membership/unified-schedules/ — merged tenant schedule timetable."""
    feature_key = 'classes'
    permission_classes = [IsAuthenticated, HasFeatureMethodPermission]

    def get(self, request):
        schedules = GymSchedule.objects.filter(is_deleted=False).select_related(
            'gym_class__trainer_class', 'trainer_profile__user', 'trainer_schedule'
        ).order_by('day_of_week', 'start_time')
        serializer = UnifiedScheduleSerializer(schedules, many=True)
        return Response(serializer.data)


# =============================================================================
# PUBLIC GYM CLASS + SCHEDULE (for landing page)
# =============================================================================

class PublicGymClassListAPIView(APIView):
    """GET /api/v1/membership/public/gym-classes/ — public list of active classes."""
    permission_classes = [AllowAny]

    def get(self, request):
        classes = GymClass.objects.filter(
            is_active=True,
            is_deleted=False,
            is_published=True,
        ).select_related('trainer_profile__user', 'trainer_class').order_by('name')
        serializer = UnifiedClassSerializer(classes, many=True)
        return Response(serializer.data)


class PublicGymScheduleListAPIView(APIView):
    """GET /api/v1/membership/public/gym-schedules/ — public schedules for landing page."""
    permission_classes = [AllowAny]

    def get(self, request):
        schedules = GymSchedule.objects.filter(
            is_deleted=False,
            is_published=True,
            is_active=True,
        ).select_related('gym_class__trainer_class', 'trainer_profile__user').order_by('day_of_week', 'start_time')
        serializer = UnifiedScheduleSerializer(schedules, many=True)
        return Response(serializer.data)