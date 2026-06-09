"""
TimezoneMiddleware — activates the correct IANA timezone for every request.

Priority chain (highest to lowest):
  1. GymProfile.timezone   — the tenant's own setting (tenant schema)
  2. Tenant.timezone       — platform-admin's per-tenant override (public schema)
  3. PlatformSettings.default_timezone — platform-admin global default (public schema)
  4. settings.TIME_ZONE    — code-level fallback (Asia/Dhaka)

The middleware must be placed *after* TenantMainMiddleware in MIDDLEWARE so that
connection.tenant is already resolved when _resolve_timezone() runs.
"""
from __future__ import annotations

import zoneinfo
import logging

from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tz_name = self._resolve_timezone()
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            logger.warning("TimezoneMiddleware: unknown timezone %r, falling back to %s", tz_name, settings.TIME_ZONE)
            try:
                tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
            except (zoneinfo.ZoneInfoNotFoundError, KeyError):
                tz = zoneinfo.ZoneInfo("UTC")

        timezone.activate(tz)
        try:
            response = self.get_response(request)
        finally:
            timezone.deactivate()
        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_timezone(self) -> str:
        """Return the best IANA timezone string for the current request."""
        tenant = getattr(connection, "tenant", None)
        if tenant is None:
            return self._platform_default()

        from django_tenants.utils import get_public_schema_name

        schema_name = getattr(tenant, "schema_name", None)
        if schema_name == get_public_schema_name():
            return self._platform_default()

        # 1. Tenant's own GymProfile.timezone (highest priority)
        try:
            from apps.dashboard.models import GymProfile
            tz_name = (
                GymProfile.objects
                .filter(pk=1)
                .values_list("timezone", flat=True)
                .first()
            )
            if tz_name:
                return tz_name
        except Exception:
            pass

        # 2. Platform-admin's per-tenant override stored on the Tenant model
        tz_name = getattr(tenant, "timezone", None)
        if tz_name:
            return tz_name

        # 3. Global platform default
        return self._platform_default()

    @staticmethod
    def _platform_default() -> str:
        """Read PlatformSettings.default_timezone from the public schema."""
        try:
            from apps.tenancy.models import PlatformSettings
            from django_tenants.utils import get_public_schema_name, schema_context

            with schema_context(get_public_schema_name()):
                tz_name = (
                    PlatformSettings.objects
                    .filter(pk=1)
                    .values_list("default_timezone", flat=True)
                    .first()
                )
                if tz_name:
                    return tz_name
        except Exception:
            pass

        return settings.TIME_ZONE
