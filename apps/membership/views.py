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


# =============================================================================
# MEMBER PACKAGE VIEW
# =============================================================================

class MemberPackageActions:
    """Action handlers for MemberPackage."""
    actions = {
        'activate':   lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_active', True),
        'deactivate': lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_active', False),
        'highlight':  lambda self, req, pk: self._toggle_flag(MemberPackage, pk, 'is_highlighted'),
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
        msg = 'highlighted' if field == 'is_highlighted' and value else 'unhighlighted' if field == 'is_highlighted' else 'activated' if field == 'is_active' and value else 'deactivated'
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
        packages = MemberPackage.objects.filter(is_active=True, is_highlighted=True).order_by('display_order', 'name')
        serializer = MemberPackagePublicSerializer(packages, many=True)
        return Response(serializer.data)


class PublicPackageRetrieveAPIView(APIView):
    """GET /api/v1/membership/public/packages/{pk}/ — public retrieve a package."""
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            package = MemberPackage.objects.get(pk=pk, is_active=True, is_highlighted=True)
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
        serializer = MemberPublicSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = serializer.save()
        return Response(MemberSerializer(member).data, status=status.HTTP_201_CREATED)


# =============================================================================
# PAYMENT VIEW
# =============================================================================

class PaymentView(ModelCRUDView):
    """Handles all Payment operations."""
    feature_key = 'members'
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