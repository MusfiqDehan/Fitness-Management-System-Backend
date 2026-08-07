"""Tenant-facing custom domain self-service endpoints.

Tenant admins (or users with ``settings`` edit access) can connect their own
custom domain — including a subdomain of their own zone such as
``gym.theircompany.com`` — via a non-disruptive DNS TXT challenge.

Availability is gated by :func:`custom_domain_effectively_enabled`, which
requires the global platform master switch, the per-tenant switch, and (when a
``custom_domain`` Feature exists) the tenant's feature flag.

All ``CustomDomainRequest``/``Domain`` rows live in the public/shared schema, so
every read/write here runs inside ``schema_context(public)``. The routable
``Domain`` row is only created once verification succeeds.
"""
from __future__ import annotations

import re

from django.conf import settings
from django.utils import timezone as dj_timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from apps.tenancy.dns_verification import (
    check_domain_routing,
    generate_verification_token,
    verify_txt_record,
)
from apps.tenancy.models import CustomDomainRequest, Domain
from apps.tenancy.services import custom_domain_effectively_enabled


# Hostname syntax: labels of a-z0-9 (hyphen allowed internally), 2+ labels,
# TLD of 2+ letters. Lowercased before matching.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$"
)

def _blocked_suffixes() -> tuple[str, ...]:
    """Hostnames the platform reserves for itself / cannot be claimed by tenants."""
    from django.conf import settings

    domain = (
        getattr(settings, "PUBLIC_DOMAIN", "")
        or getattr(settings, "TENANT_BASE_DOMAIN", "")
        or "fitness.musfiqdehan.com"
    ).strip().lower().rstrip(".")
    return (domain,) if domain else ("fitness.musfiqdehan.com",)


def _normalize_domain(value: str) -> str:
    return (value or "").strip().lower().rstrip(".")


def _validate_domain(value: str) -> tuple[str, str]:
    """Return ``(normalized, error)``. ``error`` empty when valid."""
    domain = _normalize_domain(value)
    if not domain:
        return "", "Please enter a domain."
    if domain.startswith("http://") or domain.startswith("https://"):
        return "", "Enter the domain only, without http:// or https://."
    if "/" in domain or " " in domain:
        return "", "Enter a valid domain such as gym.yourcompany.com."
    if not _DOMAIN_RE.match(domain):
        return "", "Enter a valid domain such as gym.yourcompany.com."
    if any(domain == s or domain.endswith("." + s) for s in _blocked_suffixes()):
        return "", "This domain is managed by the platform and cannot be used."
    return domain, ""


def _relative_txt_host(domain: str) -> str:
    """DNS Name field relative to a typical zone (last two labels).

    Example: ``gym.example.com`` → ``_fitpulse-verify.gym``;
    ``example.com`` → ``_fitpulse-verify``.
    Providers that want the FQDN should use ``verification_record_name``.
    """
    prefix = CustomDomainRequest.VERIFICATION_RECORD_PREFIX
    parts = _normalize_domain(domain).split(".")
    if len(parts) <= 2:
        return prefix
    return f"{prefix}.{'.'.join(parts[:-2])}"


def _is_apex_domain(domain: str) -> bool:
    """Heuristic: two labels means apex (e.g. example.com). Prefer A over CNAME."""
    return len(_normalize_domain(domain).split(".")) == 2


def _routing_targets() -> tuple[str, str, str]:
    """Return ``(preferred_type, cname_target, a_target)`` from settings."""
    cname = (
        getattr(settings, "CUSTOM_DOMAIN_CNAME_TARGET", "") or ""
    ).strip().lower().rstrip(".")
    a_target = (getattr(settings, "CUSTOM_DOMAIN_A_TARGET", "") or "").strip()
    preferred = "CNAME" if cname else ("A" if a_target else "CNAME")
    return preferred, cname, a_target


def _routing_fields(domain: str = "") -> dict:
    preferred, cname, a_target = _routing_targets()
    # Apex hostnames usually cannot use CNAME — prefer A when available.
    if domain and _is_apex_domain(domain) and a_target:
        preferred = "A"
    value = a_target if preferred == "A" else cname
    return {
        "routing_record_type": preferred,
        "routing_record_name": domain or "",
        "routing_record_value": value,
        "routing_cname_target": cname,
        "routing_a_target": a_target,
        "is_apex": bool(domain) and _is_apex_domain(domain),
    }


def _serialize_request(req: CustomDomainRequest | None, *, enabled: bool) -> dict:
    if req is None:
        return {
            "enabled": enabled,
            "domain": "",
            "status": None,
            "verification_record_name": "",
            "verification_record_host": "",
            "verification_token": "",
            "verification_record_type": "TXT",
            "verified_at": None,
            "last_error": "",
            "routing_ready": False,
            "ssl_ready": False,
            **_routing_fields(""),
        }

    data = {
        "enabled": enabled,
        "domain": req.domain,
        "status": req.status,
        "verification_record_name": req.verification_record_name,
        "verification_record_host": _relative_txt_host(req.domain),
        "verification_token": req.verification_token,
        "verification_record_type": "TXT",
        "verified_at": req.verified_at.isoformat() if req.verified_at else None,
        "last_error": req.last_error,
        "routing_ready": False,
        # SSL is provisioned automatically once DNS points here; same readiness signal.
        "ssl_ready": False,
        **_routing_fields(req.domain),
    }

    if req.status == CustomDomainRequest.STATUS_VERIFIED and req.domain:
        _, cname, a_target = _routing_targets()
        ready, message = check_domain_routing(
            req.domain, cname_target=cname, a_target=a_target
        )
        data["routing_ready"] = ready
        data["ssl_ready"] = ready
        # Advisory only — never overwrite a hard verification failure message.
        if not ready and not data["last_error"]:
            data["last_error"] = message

    return data


class CustomDomainAPIView(APIView):
    """GET / POST / DELETE the tenant's single custom-domain request."""

    permission_classes = [HasFeatureMethodPermission]
    feature_key = "settings"

    def _tenant(self, request):
        return getattr(request, "tenant", None)

    def _guard_enabled(self, tenant):
        """Return a 403 Response if custom domains are not enabled, else None."""
        with schema_context(get_public_schema_name()):
            enabled = custom_domain_effectively_enabled(tenant)
        if not enabled:
            return Response(
                {"detail": "Custom domains are not enabled for your workspace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def get(self, request):
        tenant = self._tenant(request)
        if tenant is None:
            return Response({"detail": "Tenant context unavailable."}, status=400)
        with schema_context(get_public_schema_name()):
            enabled = custom_domain_effectively_enabled(tenant)
            req = (
                CustomDomainRequest.objects.filter(tenant=tenant)
                .order_by("-created_at")
                .first()
            )
            data = _serialize_request(req, enabled=enabled)
        return Response(data)

    def post(self, request):
        tenant = self._tenant(request)
        if tenant is None:
            return Response({"detail": "Tenant context unavailable."}, status=400)

        denied = self._guard_enabled(tenant)
        if denied is not None:
            return denied

        domain, error = _validate_domain(request.data.get("domain", ""))
        if error:
            return Response({"domain": error}, status=status.HTTP_400_BAD_REQUEST)

        with schema_context(get_public_schema_name()):
            # Reject domains already routable or requested by another tenant.
            if Domain.objects.filter(domain=domain).exclude(tenant=tenant).exists():
                return Response(
                    {"domain": "This domain is already in use."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            clash = (
                CustomDomainRequest.objects.filter(domain=domain)
                .exclude(tenant=tenant)
                .exists()
            )
            if clash:
                return Response(
                    {"domain": "This domain is already being set up by another workspace."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # One custom domain per tenant: replace any prior request + its alias.
            old = list(CustomDomainRequest.objects.filter(tenant=tenant))
            for prev in old:
                if prev.domain != domain:
                    Domain.objects.filter(
                        tenant=tenant, domain=prev.domain, is_primary=False
                    ).delete()
            CustomDomainRequest.objects.filter(tenant=tenant).exclude(domain=domain).delete()

            req, _ = CustomDomainRequest.objects.get_or_create(
                tenant=tenant,
                domain=domain,
                defaults={
                    "verification_token": generate_verification_token(),
                    "status": CustomDomainRequest.STATUS_PENDING,
                    "created_by_email": getattr(request.user, "email", "") or "",
                },
            )
            data = _serialize_request(req, enabled=True)
        from apps.tenancy.traefik_custom_domains import sync_traefik_custom_domains

        # Drop stale Traefik Host() routers if a previous verified alias was replaced.
        sync_traefik_custom_domains()
        return Response(data, status=status.HTTP_201_CREATED)

    def delete(self, request):
        tenant = self._tenant(request)
        if tenant is None:
            return Response({"detail": "Tenant context unavailable."}, status=400)
        with schema_context(get_public_schema_name()):
            reqs = list(CustomDomainRequest.objects.filter(tenant=tenant))
            for req in reqs:
                Domain.objects.filter(
                    tenant=tenant, domain=req.domain, is_primary=False
                ).delete()
            CustomDomainRequest.objects.filter(tenant=tenant).delete()
        from apps.tenancy.traefik_custom_domains import sync_traefik_custom_domains

        sync_traefik_custom_domains()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomDomainVerifyAPIView(APIView):
    """POST: run the DNS TXT challenge and, on success, create the alias."""

    permission_classes = [HasFeatureMethodPermission]
    feature_key = "settings"
    write_level = "edit"

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"detail": "Tenant context unavailable."}, status=400)

        with schema_context(get_public_schema_name()):
            enabled = custom_domain_effectively_enabled(tenant)
            if not enabled:
                return Response(
                    {"detail": "Custom domains are not enabled for your workspace."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            req = (
                CustomDomainRequest.objects.filter(tenant=tenant)
                .order_by("-created_at")
                .first()
            )
            if req is None:
                return Response(
                    {"detail": "No custom domain to verify. Add a domain first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            ok, error = verify_txt_record(
                req.verification_record_name, req.verification_token
            )
            if not ok:
                req.status = CustomDomainRequest.STATUS_FAILED
                req.last_error = error
                req.save(update_fields=["status", "last_error", "updated_at"])
                return Response(
                    {**_serialize_request(req, enabled=True), "detail": error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Verified: create the routable alias (secondary; subdomain stays primary).
            if not Domain.objects.filter(domain=req.domain).exists():
                Domain.objects.create(
                    domain=req.domain, tenant=tenant, is_primary=False
                )
            req.status = CustomDomainRequest.STATUS_VERIFIED
            req.last_error = ""
            req.verified_at = dj_timezone.now()
            req.save(update_fields=["status", "last_error", "verified_at", "updated_at"])
            data = _serialize_request(req, enabled=True)
        from apps.tenancy.traefik_custom_domains import sync_traefik_custom_domains

        sync_traefik_custom_domains()
        return Response(data)
