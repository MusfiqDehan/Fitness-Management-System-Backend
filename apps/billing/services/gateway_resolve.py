"""Helpers for resolving payment gateways without an implicit default."""
from __future__ import annotations

from apps.tenancy.models import PaymentGateway


def gateway_credentials_complete(gateway: PaymentGateway, credentials: dict | None) -> bool:
    """Return True when all required config_schema fields are present."""
    required_keys = [
        field.get("key")
        for field in (gateway.config_schema or [])
        if field.get("required") and field.get("key")
    ]
    if not required_keys:
        # Fall back to "any non-empty credentials" when schema is empty.
        return bool(credentials)
    return all(str((credentials or {}).get(key, "")).strip() for key in required_keys)


def list_subscription_ready_gateways():
    """Return platform gateways that have complete platform credentials.

    Order is stable (sort_order, name). No gateway is treated as default —
    callers must pick a slug explicitly.
    """
    gateways = list(PaymentGateway.objects.order_by("sort_order", "name"))
    return [
        gw
        for gw in gateways
        if gateway_credentials_complete(gw, gw.platform_credentials)
    ]


def resolve_subscription_gateway(gateway_slug: str | None) -> PaymentGateway:
    """Resolve a platform gateway by slug for SaaS subscription billing.

    Raises:
        ValueError: When slug is missing, unknown, or credentials are incomplete.
    """
    slug = (gateway_slug or "").strip().lower()
    if not slug:
        ready = list_subscription_ready_gateways()
        names = ", ".join(g.slug for g in ready) or "(none configured)"
        raise ValueError(
            "gateway_slug is required. Choose one of the configured subscription "
            f"gateways: {names}."
        )

    gateway = PaymentGateway.objects.filter(slug=slug).first()
    if gateway is None:
        raise ValueError(f"Unknown payment gateway '{slug}'.")

    if not gateway_credentials_complete(gateway, gateway.platform_credentials):
        raise ValueError(
            f"Payment gateway '{slug}' does not have platform credentials configured."
        )

    return gateway


def serialize_subscription_ready_gateways() -> list[dict]:
    """JSON-serializable list of subscription-ready gateways for API responses."""
    return [
        {
            "slug": gw.slug,
            "name": gw.name,
            "is_sandbox": gw.is_sandbox,
            "description": gw.description or "",
        }
        for gw in list_subscription_ready_gateways()
    ]
