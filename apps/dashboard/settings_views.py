"""
Settings and Reminders views for the dashboard app.
Imported and wired in views.py via explicit __all__ re-exports.
"""
from datetime import date

from django.db.models import Sum
from django.db import connection
from django.utils import timezone as dj_timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.serializers import CurrentUserSerializer, CurrentUserUpdateSerializer
from apps.membership.models import Member
from utils.cache_helpers import (
    PUBLIC_BRANDING_TTL,
    STATS_TTL,
    get_cached_value,
    invalidate_timezone,
    public_branding_key,
    stats_key,
)

from .models import (
    GymPreferences,
    GymProfile,
    NotificationPreferences,
    Reminder,
    ReminderTemplate,
)
from .serializers import (
    GymPreferencesSerializer,
    GymProfileSerializer,
    NotificationPreferencesSerializer,
    ReminderSerializer,
    ReminderTemplateSerializer,
)


def serialize_gym_branding(profile) -> dict:
    """Normalized public branding payload for either GymProfile or PlatformGymProfile.

    Returns an empty-shaped payload (with the hardcoded default logo dimensions)
    when ``profile`` is None so the frontend can rely on a stable schema.
    """
    if profile is None:
        return {
            "logo_url": "",
            "logo_width": 120,
            "logo_height": 40,
            "company_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "website": "",
            "timezone": "",
            "navbar_pages": [],
            "footer_pages": [],
            "updated_at": None,
        }
    return {
        "logo_url": profile.logo_url or "",
        "logo_width": profile.logo_width or 120,
        "logo_height": profile.logo_height or 40,
        "company_name": profile.gym_name or "",
        "phone": profile.phone or "",
        "email": profile.email or "",
        "address": profile.address or "",
        "website": profile.website or "",
        "timezone": profile.timezone or "",
        "navbar_pages": [],
        "footer_pages": [],
        "updated_at": profile.updated_at,
    }


# ---------------------------------------------------------------
# Settings — Gym Profile
# ---------------------------------------------------------------

class GymProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self):
        obj, _ = GymProfile.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(GymProfileSerializer(self._obj()).data)

    def patch(self, request):
        serializer = GymProfileSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        profile = serializer.instance

        # Sync timezone back to the public-schema Tenant row so the TimezoneMiddleware
        # and PlatformAdmin tenant list both reflect the tenant's chosen timezone.
        current_tenant = getattr(connection, "tenant", None)
        if (
            current_tenant is not None
            and getattr(current_tenant, "schema_name", None) != get_public_schema_name()
        ):
            with schema_context(get_public_schema_name()):
                from apps.tenancy.models import Tenant
                Tenant.objects.filter(id=current_tenant.id).update(timezone=profile.timezone)
            invalidate_timezone(current_tenant.schema_name)

        return Response(serializer.data)


# ---------------------------------------------------------------
# Settings — Notification Preferences
# ---------------------------------------------------------------

class NotificationPreferencesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self):
        obj, _ = NotificationPreferences.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(NotificationPreferencesSerializer(self._obj()).data)

    def patch(self, request):
        serializer = NotificationPreferencesSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------
# Settings — Gym Preferences
# ---------------------------------------------------------------

class GymPreferencesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self):
        obj, _ = GymPreferences.objects.get_or_create(pk=1)
        return obj

    def _resolved_language(self, fallback: str) -> str:
        """Resolve effective tenant language without breaking schema boundaries.

        Priority inside tenant schema:
          1. Tenant.locale (public schema override / synced tenant choice)
          2. PlatformSettings.default_language (public schema fallback)
          3. GymPreferences.language (local fallback)
        """
        current_tenant = getattr(connection, "tenant", None)
        if current_tenant is None:
            return fallback

        schema_name = getattr(current_tenant, "schema_name", None)
        if schema_name == get_public_schema_name():
            return fallback

        locale = (getattr(current_tenant, "locale", "") or "").strip()
        if locale:
            return locale

        with schema_context(get_public_schema_name()):
            from apps.tenancy.models import PlatformSettings

            default_language = (
                PlatformSettings.objects.filter(pk=1).values_list("default_language", flat=True).first()
            )
            if default_language:
                return default_language

        return fallback

    def _resolved_currency(self, fallback: str) -> str:
        """Resolve effective tenant currency without breaking schema boundaries.

        Priority inside tenant schema:
          1. Tenant.currency (public schema override / synced tenant choice)
          2. PlatformSettings.default_currency (public schema fallback)
          3. GymPreferences.currency (local fallback)
        """
        current_tenant = getattr(connection, "tenant", None)
        if current_tenant is None:
            return fallback

        schema_name = getattr(current_tenant, "schema_name", None)
        if schema_name == get_public_schema_name():
            return fallback

        currency = (getattr(current_tenant, "currency", "") or "").strip()
        if currency:
            return currency

        with schema_context(get_public_schema_name()):
            from apps.tenancy.models import PlatformSettings

            default_currency = (
                PlatformSettings.objects.filter(pk=1).values_list("default_currency", flat=True).first()
            )
            if default_currency:
                return default_currency

        return fallback

    def get(self, request):
        data = GymPreferencesSerializer(self._obj()).data
        data["language"] = self._resolved_language(data.get("language", "en"))
        data["currency"] = self._resolved_currency(data.get("currency", "USD"))
        return Response(data)

    def patch(self, request):
        serializer = GymPreferencesSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Sync language and currency back to the public-schema Tenant model so the
        # Platform Admin tenant list first-class configurations reflect the tenant's choices.
        current_tenant = getattr(connection, "tenant", None)
        if (
            current_tenant is not None
            and getattr(current_tenant, "schema_name", None) != get_public_schema_name()
        ):
            new_locale = serializer.validated_data.get("language")
            new_currency = serializer.validated_data.get("currency")
            
            with schema_context(get_public_schema_name()):
                from apps.tenancy.models import Tenant
                update_fields = {}
                if new_locale:
                    update_fields["locale"] = new_locale
                if new_currency:
                    update_fields["currency"] = new_currency
                if update_fields:
                    Tenant.objects.filter(id=current_tenant.id).update(**update_fields)

        return Response(serializer.data)


# ---------------------------------------------------------------
# Settings — My Account (proxy to identity/me)
# ---------------------------------------------------------------

class MyAccountAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)

    def patch(self, request):
        serializer = CurrentUserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CurrentUserSerializer(request.user).data)


# ---------------------------------------------------------------
# Settings — Change Password
# ---------------------------------------------------------------

class ChangePasswordAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get("current_password", "")
        new_password = request.data.get("new_password", "")

        if not current_password or not new_password:
            return Response(
                {"detail": "current_password and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not request.user.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(new_password) < 8:
            return Response(
                {"detail": "New password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(new_password)
        request.user.password_set_at = dj_timezone.now()
        request.user.save(update_fields=["password", "password_set_at"])
        return Response({"detail": "Password changed successfully."})


# ---------------------------------------------------------------
# Reminders — Templates
# ---------------------------------------------------------------

class ReminderTemplateListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(ReminderTemplateSerializer(ReminderTemplate.objects.all(), many=True).data)

    def post(self, request):
        serializer = ReminderTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ReminderTemplateDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return ReminderTemplate.objects.get(pk=pk)
        except ReminderTemplate.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ReminderTemplateSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ReminderTemplateSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------
# Reminders — Reminder records
# ---------------------------------------------------------------

class ReminderListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Reminder.objects.select_related("member", "member__member_package")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(ReminderSerializer(qs, many=True).data)

    def post(self, request):
        serializer = ReminderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ReminderDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return Reminder.objects.select_related("member", "member__member_package").get(pk=pk)
        except Reminder.DoesNotExist:
            return None

    def patch(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ReminderSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReminderSendAPIView(APIView):
    """Mark a reminder as sent."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            reminder = Reminder.objects.select_related(
                "member", "member__member_package"
            ).get(pk=pk)
        except Reminder.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        reminder.status = "sent"
        reminder.sent_at = dj_timezone.now()
        reminder.save(update_fields=["status", "sent_at"])
        return Response(ReminderSerializer(reminder).data)


# ---------------------------------------------------------------
# Reminders — Stats
# ---------------------------------------------------------------

class ReminderStatsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        schema_name = connection.schema_name

        def load():
            first_of_month = date.today().replace(day=1)
            pending = Reminder.objects.filter(status="pending").count()
            sent_this_month = Reminder.objects.filter(
                status="sent", sent_at__date__gte=first_of_month
            ).count()
            overdue_members = Member.objects.filter(end_date__lt=date.today()).count()
            overdue_amount = (
                Reminder.objects.filter(status="pending", reminder_type="payment_due")
                .aggregate(total=Sum("amount"))["total"] or 0
            )
            active_templates = ReminderTemplate.objects.filter(is_active=True).count()
            return {
                "pending": pending,
                "sent_this_month": sent_this_month,
                "overdue_members": overdue_members,
                "overdue_amount": str(overdue_amount),
                "active_templates": active_templates,
            }

        payload = get_cached_value(
            stats_key(schema_name, "reminder_stats", "all"),
            STATS_TTL,
            load,
        )
        return Response(payload)


# ---------------------------------------------------------------
# Public Gym Branding (tenant schema)
# ---------------------------------------------------------------

class PublicGymBrandingView(APIView):
    """GET /api/v1/cms/public/site-settings/ — public read of tenant gym branding."""
    permission_classes = [AllowAny]

    def get(self, request):
        schema_name = connection.schema_name

        def load():
            profile = GymProfile.objects.filter(pk=1).first()
            return serialize_gym_branding(profile)

        payload = get_cached_value(
            public_branding_key(schema_name),
            PUBLIC_BRANDING_TTL,
            load,
        )
        return Response(payload)
