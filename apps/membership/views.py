"""Tenant-scoped membership API views.

Handles all member and package lifecycle operations including:
- Member CRUD, invite, activate/deactivate, soft delete
- Package CRUD, activate/deactivate, soft delete, highlight
- Public self-registration from landing page
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.db.models import Q
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
import secrets

from .models import Member, MemberPackage, Payment, Attendance
from .serializers import (
    MemberSerializer,
    MemberPublicSerializer,
    MemberPackageSerializer,
    MemberPackagePublicSerializer,
    MemberMinimalSerializer,
    PaymentSerializer,
    AttendanceSerializer,
)
from utils.base_view import ModelCRUDView
from apps.access.permissions import HasFeatureMethodPermission


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
    tenant_name = getattr(getattr(request, 'tenant', None), 'name', None) or 'our gym'

    send_mail(
        subject=f"Complete your member registration at {tenant_name}",
        message=(
            f"Hi {member.full_name or 'there'},\n\n"
            f"You have been invited to complete your member registration. "
            f"Use the link below to verify your invitation and set your password:\n\n"
            f"{invite_url}\n\n"
            f"This link expires in 7 days."
        ),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@gym.local'),
        recipient_list=[member.email],
        fail_silently=False,
    )
    return invite_url


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


class MemberPackageView(MemberPackageActions, ModelCRUDView):
    """Handles all MemberPackage operations and actions."""
    feature_key = 'members.packages'
    queryset = MemberPackage.objects.all().order_by('display_order', 'name')
    serializer_class = MemberPackageSerializer
    permission_classes = [HasFeatureMethodPermission]


# =============================================================================
# MEMBER VIEW
# =============================================================================

class MemberActions:
    """Action handlers for Member."""
    actions = {
        'activate':   lambda self, req, pk: self._toggle_flag(Member, pk, 'is_active', True),
        'deactivate': lambda self, req, pk: self._toggle_flag(Member, pk, 'is_active', False),
        'restore':    lambda self, req, pk: self._restore(pk),
    }

    def _toggle_flag(self, model, pk, field, value):
        try:
            obj = model.objects.get(pk=pk)
        except model.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        setattr(obj, field, value)
        obj.save(update_fields=[field])
        return Response({'message': 'Activated' if value else 'Deactivated', field: value})

    def _restore(self, pk):
        try:
            member = Member.all_objects.get(pk=pk)
        except Member.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if not member.is_deleted:
            return Response({'error': 'Member is not deleted'}, status=status.HTTP_400_BAD_REQUEST)
        member.restore()
        return Response({'message': 'Member restored', 'is_deleted': False})


class MemberView(MemberActions, ModelCRUDView):
    """Handles all Member operations and actions."""
    feature_key = 'members'
    serializer_class = MemberSerializer
    permission_classes = [HasFeatureMethodPermission]

    def _create(self, request):
        serializer = self.get_serializer(data=request.data)
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

    def get_queryset(self):
        queryset = Member.objects.all().order_by('-created_at')
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(Q(full_name__icontains=search) | Q(phone_number__icontains=search))
        return queryset


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

        serializer = MemberPublicSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                member = serializer.save(is_active=False)
                invite_url = _send_member_invitation_email(
                    member,
                    request,
                    invited_by=None,
                    force_new_token=True,
                )
        except Exception as exc:
            return Response(
                {'error': f'Failed to send invitation email: {str(exc)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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

        base_qs = Member.objects.all()

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

        if not email:
            return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not phone_number:
            return Response({'error': 'Phone number is required'}, status=status.HTTP_400_BAD_REQUEST)

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

        return Response({'message': 'Registration completed successfully', 'member_id': member.id})


# =============================================================================
# PAYMENT VIEW
# =============================================================================

class PaymentView(ModelCRUDView):
    """Handles all Payment operations."""
    feature_key = 'payments'
    queryset = Payment.objects.all().order_by('-payment_date')
    serializer_class = PaymentSerializer
    permission_classes = [HasFeatureMethodPermission]


# =============================================================================
# ATTENDANCE VIEW
# =============================================================================

class AttendanceView(ModelCRUDView):
    """Handles all Attendance operations."""
    feature_key = 'attendance'
    queryset = Attendance.objects.all().order_by('-check_in_time')
    serializer_class = AttendanceSerializer
    permission_classes = [HasFeatureMethodPermission]