"""
Tenant resolution middleware for hostless API clients (e.g. the React Native
mobile app).

The default django-tenants ``TenantMainMiddleware`` resolves the active tenant
purely from the request hostname (the subdomain). Native mobile clients call
the API on a single, subdomain-less host (e.g. ``api.fitssort.com`` or the
Android emulator's ``10.0.2.2``), so the hostname alone cannot identify the
tenant.

This subclass lets the client name its tenant explicitly and securely:

1. Authenticated requests -> the tenant is read from the SIGNED JWT access
   token's ``tenant_schema`` claim. Because the claim is cryptographically
   signed by the server at login time, a client cannot point a token at a
   schema it was not issued for.

2. Unauthenticated public endpoints (member self-registration, public package
   listing) -> the tenant is read from the ``X-Tenant-Subdomain`` header (or
   ``X-Tenant-Schema``). These endpoints only ever expose tenant-public data,
   so a header hint is acceptable there.

When neither is present we fall back to the normal hostname-based resolution,
so existing browser/subdomain flows are completely unaffected.
"""
from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_public_schema_name

from .models import Domain


def _derive_schema_from_subdomain(subdomain: str) -> str:
    return (subdomain or "").strip().lower().replace("-", "_")


class MobileAwareTenantMainMiddleware(TenantMainMiddleware):
    """TenantMainMiddleware that also honours JWT/header tenant hints."""

    def _schema_from_token(self, request):
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth.startswith("Bearer "):
            return None
        raw = auth.split(" ", 1)[1].strip()
        if not raw:
            return None
        try:
            # AccessToken() verifies the signature and expiry. An invalid or
            # expired token yields no hint (the request will 401 downstream).
            from rest_framework_simplejwt.tokens import AccessToken

            token = AccessToken(raw)
        except Exception:
            return None
        return token.get("tenant_schema") or None

    def _schema_from_header(self, request):
        schema = (request.META.get("HTTP_X_TENANT_SCHEMA") or "").strip().lower()
        if schema:
            return schema
        subdomain = (request.META.get("HTTP_X_TENANT_SUBDOMAIN") or "").strip().lower()
        if subdomain:
            return _derive_schema_from_subdomain(subdomain)
        return None

    def _hint_schema(self, request):
        # Prefer the signed token claim; fall back to the header hint.
        return self._schema_from_token(request) or self._schema_from_header(request)

    def hostname_from_request(self, request):
        schema = self._hint_schema(request)
        if schema and schema != get_public_schema_name():
            # Resolve a real domain row for this tenant schema and let the
            # parent middleware perform schema activation + URL routing.
            domain = (
                Domain.objects.filter(tenant__schema_name=schema)
                .order_by("-is_primary", "id")
                .values_list("domain", flat=True)
                .first()
            )
            if domain:
                return domain
        return super().hostname_from_request(request)
