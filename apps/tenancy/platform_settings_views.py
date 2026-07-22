"""
Platform Admin settings views — public schema only.

These views expose the same Settings panel endpoints that tenant-schema
users hit via apps.dashboard, but backed by public-schema singleton
models so Platform Admin users can manage their own gym profile,
preferences, and notification settings without touching tenant data.

Public branding (AllowAny) mirrors the tenant PublicGymBrandingView URL.
Authenticated gym-profile GET is available to any logged-in platform user;
mutations still require platform.settings edit.
"""
import os
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.settings_views import serialize_gym_branding
from utils.cache_helpers import PUBLIC_BRANDING_TTL, get_cached_value, public_branding_key

from .models import (
    PlatformGymPreferences,
    PlatformGymProfile,
    PlatformNotificationPreferences,
)
from .permissions import IsPlatformFeaturePermission
from .serializers import (
    PlatformGymPreferencesSerializer,
    PlatformGymProfileSerializer,
    PlatformNotificationPreferencesSerializer,
)

_SETTINGS_VIEW = IsPlatformFeaturePermission.require("platform.settings", "view")
_SETTINGS_EDIT = IsPlatformFeaturePermission.require("platform.settings", "edit")

_UPLOAD_ALLOWED_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
}
_UPLOAD_MAX_SIZE_MB = 100


# ---------------------------------------------------------------
# Public Gym Branding (public schema)
# ---------------------------------------------------------------

class PlatformPublicGymBrandingView(APIView):
    """GET /api/v1/cms/public/site-settings/ — public read of platform branding."""

    permission_classes = [AllowAny]

    def get(self, request):
        schema_name = connection.schema_name

        def load():
            profile = PlatformGymProfile.objects.filter(pk=1).first()
            return serialize_gym_branding(profile)

        payload = get_cached_value(
            public_branding_key(schema_name),
            PUBLIC_BRANDING_TTL,
            load,
        )
        return Response({**payload, "discount_enabled": False})


# ---------------------------------------------------------------
# Gym Profile
# ---------------------------------------------------------------

class PlatformGymProfileView(APIView):
    """GET / PATCH the Platform Admin's gym profile (public schema singleton)."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            # Branding/timezone consumers (Sidebar, useTimezone) need read access
            # for every authenticated platform role — not only settings editors.
            return [IsAuthenticated()]
        return [_SETTINGS_EDIT()]

    def _obj(self):
        obj, _ = PlatformGymProfile.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(PlatformGymProfileSerializer(self._obj()).data)

    def patch(self, request):
        serializer = PlatformGymProfileSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------
# Gym Preferences
# ---------------------------------------------------------------

class PlatformGymPreferencesView(APIView):
    """GET / PATCH the Platform Admin's display preferences (public schema singleton)."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [_SETTINGS_VIEW()]
        return [_SETTINGS_EDIT()]

    def _obj(self):
        obj, _ = PlatformGymPreferences.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(PlatformGymPreferencesSerializer(self._obj()).data)

    def patch(self, request):
        serializer = PlatformGymPreferencesSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------

class PlatformNotificationPreferencesView(APIView):
    """GET / PATCH Platform Admin notification preferences (public schema singleton)."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [_SETTINGS_VIEW()]
        return [_SETTINGS_EDIT()]

    def _obj(self):
        obj, _ = PlatformNotificationPreferences.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(PlatformNotificationPreferencesSerializer(self._obj()).data)

    def patch(self, request):
        serializer = PlatformNotificationPreferencesSerializer(
            self._obj(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------
# File Upload (logo, etc.)
# ---------------------------------------------------------------

class PlatformFileUploadView(APIView):
    """POST — accept a file upload for Platform Admin (logo, assets, etc.)."""

    permission_classes = [_SETTINGS_EDIT]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response(
                {"error": "No file provided. Send a multipart field named 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if uploaded.content_type not in _UPLOAD_ALLOWED_MIME_TYPES:
            return Response(
                {"error": f"Unsupported file type '{uploaded.content_type}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_bytes = _UPLOAD_MAX_SIZE_MB * 1024 * 1024
        if uploaded.size > max_bytes:
            return Response(
                {"error": f"File too large. Maximum allowed size is {_UPLOAD_MAX_SIZE_MB} MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        original_ext = os.path.splitext(uploaded.name)[-1].lower()
        unique_name = f"{uuid.uuid4().hex}{original_ext}"
        save_path = os.path.join('uploads', unique_name)

        saved_name = default_storage.save(save_path, ContentFile(uploaded.read()))

        storage_url = default_storage.url(saved_name)
        if storage_url.startswith('http://') or storage_url.startswith('https://'):
            file_url = storage_url
        else:
            file_url = storage_url

        return Response({"file_url": file_url}, status=status.HTTP_201_CREATED)
