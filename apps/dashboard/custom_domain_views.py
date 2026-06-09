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

from django.utils import timezone as dj_timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from apps.tenancy.dns_verification import (
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

# Hostnames the platform reserves for itself / cannot be claimed by tenants.
_BLOCKED_SUFFIXES = ("fitssort.com",)


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
    if any(domain == s or domain.endswith("." + s) for s in _BLOCKED_SUFFIXES):
        return "", "This domain is managed by the platform and cannot be used."
    return domain, ""


def _serialize_request(req: CustomDomainRequest | None, *, enabled: bool) -> dict:
    if req is None:
        return {
            "enabled": enabled,
            "domain": "",
            "status": None,
            "verification_record_name": "",
            "verification_token": "",
            "verification_record_type": "TXT",
            "verified_at": None,
            "last_error": "",
        }
    return {
        "enabled": enabled,
        "domain": req.domain,
        "status": req.status,
        "verification_record_name": req.verification_record_name,
        "verification_token": req.verification_token,
        "verification_record_type": "TXT",
        "verified_at": req.verified_at.isoformat() if req.verified_at else None,
        "last_error": req.last_error,
    }


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
        return Response(data)
