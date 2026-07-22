# identity/views.py
from django.db import connection
from rest_framework import generics, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from django_tenants.utils import get_public_schema_name, schema_context

from apps.access.permissions import HasFeatureMethodPermission
from utils.jwt_revocation import (
    access_token_from_auth_header,
    logout_tokens,
    refresh_token_is_valid,
    user_id_from_refresh,
)

from .models import User
from .serializers import (
    RegisterSerializer,
    UserSerializer,
    CurrentUserSerializer,
    CurrentUserUpdateSerializer,
    EmailOrPhoneTokenObtainPairSerializer,
)


class EmailOrPhoneTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrPhoneTokenObtainPairSerializer


class LogoutAPIView(APIView):
    """Deny access/refresh JTIs so the session cannot be resumed."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh_raw = (request.data.get("refresh") or "").strip()
        if not refresh_raw:
            return Response(
                {"detail": "refresh is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not refresh_token_is_valid(refresh_raw):
            return Response(status=status.HTTP_204_NO_CONTENT)

        access_raw = access_token_from_auth_header(
            request.META.get("HTTP_AUTHORIZATION")
        )
        logout_tokens(access_raw=access_raw, refresh_raw=refresh_raw)

        self._record_logout_audit(request, user_id=user_id_from_refresh(refresh_raw))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _record_logout_audit(self, request, user_id: int | None):
        if user_id is None:
            return
        try:
            from apps.tenancy.models import Tenant, TenantAuditLog
            from apps.tenancy.views import _json_safe
        except ImportError:
            return

        schema = connection.schema_name
        action = (
            "platform.auth.logout"
            if schema == get_public_schema_name()
            else "tenant.auth.logout"
        )
        tenant = None
        actor_email = ""
        if schema != get_public_schema_name():
            tenant = getattr(connection, "tenant", None)
            actor_email = getattr(request.user, "email", "") if request.user.is_authenticated else ""
        else:
            with schema_context(get_public_schema_name()):
                user = User.objects.filter(pk=user_id).first()
                if user is not None:
                    actor_email = user.email or ""
                    if user.tenant_id:
                        tenant = Tenant.objects.filter(pk=user.tenant_id).first()

        if not actor_email and request.user.is_authenticated:
            actor_email = getattr(request.user, "email", "") or ""

        with schema_context(get_public_schema_name()):
            TenantAuditLog.objects.create(
                tenant=tenant,
                actor_email=actor_email,
                actor_id=user_id,
                action=action,
                target_type="user",
                target_id=str(user_id),
                ip_address=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                metadata=_json_safe({"schema": schema}),
            )


# -------------------------------
# User Registration
# Enforces the tenant's max_users limit before creating the account.
# -------------------------------
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        tenant = getattr(connection, 'tenant', None)
        if tenant is not None:
            current_user_count = User.objects.count()
            if current_user_count >= tenant.max_users:
                return Response(
                    {'detail': 'This gym has reached its maximum user limit.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        return super().create(request, *args, **kwargs)


# -------------------------------
# Current Logged-in User
# Includes tenant_schema so the frontend knows which tenant context
# the token was issued under.
# -------------------------------
class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CurrentUserSerializer(request.user)
        data = serializer.data
        data['tenant_schema'] = connection.schema_name
        return Response(data)

    def patch(self, request):
        serializer = CurrentUserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = CurrentUserSerializer(request.user).data
        data['tenant_schema'] = connection.schema_name
        return Response(data, status=status.HTTP_200_OK)


class InstructorListAPIView(GenericAPIView):
    """
    Legacy endpoint — returns instructor users (role='instructor').
    For full trainer profiles (classes, schedules, ratings) use:
    GET /api/v1/trainer/
    """
    feature_key = 'instructors'
    queryset = User.objects.filter(role='instructor', is_active=True)
    serializer_class = UserSerializer
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = [{'id': u.id, 'name': u.email or u.phone} for u in queryset]
        return Response(data)