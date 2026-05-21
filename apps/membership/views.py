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
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from datetime import timedelta
import secrets

from .models import Member, MemberPackage, Payment, Attendance, GymClass, GymSchedule
from .serializers import (
    MemberSerializer,
    MemberPublicSerializer,
    MemberPackageSerializer,
    MemberPackagePublicSerializer,
    MemberMinimalSerializer,
    PaymentSerializer,
    AttendanceSerializer,
    GymClassSerializer,
    GymScheduleSerializer,
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
    email = EmailMultiAlternatives(
        subject=f"Complete your member registration at {company_name}",
        body=fallback_text,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@gym.local'),
        to=[member.email],
    )
    email.attach_alternative(html_body, 'text/html')
    email.send(fail_silently=False)
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

        qs = Payment.objects.filter(payment_date__date__gte=start, is_deleted=False)

        total_collected = qs.filter(payment_status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        total_due = qs.filter(payment_status='due').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        total_partial = qs.filter(payment_status='partial').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        transaction_count = qs.count()

        # Previous period for trend
        delta = (today - start).days or 1
        prev_start = start - timedelta(days=delta)
        prev_qs = Payment.objects.filter(payment_date__date__gte=prev_start, payment_date__date__lt=start, is_deleted=False)
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
    queryset = GymClass.objects.filter(is_deleted=False).order_by('name')
    serializer_class = GymClassSerializer
    permission_classes = [HasFeatureMethodPermission]


class GymScheduleView(ModelCRUDView):
    """CRUD for weekly gym schedule. GET/POST /membership/gym-schedules/ etc."""
    feature_key = 'classes'
    queryset = GymSchedule.objects.filter(is_deleted=False).order_by('day_of_week', 'start_time')
    serializer_class = GymScheduleSerializer
    permission_classes = [HasFeatureMethodPermission]


# =============================================================================
# PUBLIC GYM CLASS + SCHEDULE (for landing page)
# =============================================================================

class PublicGymClassListAPIView(APIView):
    """GET /api/v1/membership/public/gym-classes/ — public list of active classes."""
    permission_classes = [AllowAny]

    def get(self, request):
        classes = GymClass.objects.filter(is_active=True, is_deleted=False).order_by('name')
        serializer = GymClassSerializer(classes, many=True)
        return Response(serializer.data)


class PublicGymScheduleListAPIView(APIView):
    """GET /api/v1/membership/public/gym-schedules/ — public schedules for landing page."""
    permission_classes = [AllowAny]

    def get(self, request):
        schedules = GymSchedule.objects.filter(is_deleted=False).order_by('day_of_week', 'start_time')
        serializer = GymScheduleSerializer(schedules, many=True)
        return Response(serializer.data)