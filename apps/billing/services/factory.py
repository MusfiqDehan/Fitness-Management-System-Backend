"""Factory: return the correct gateway service for a given slug."""
from .base import AbstractPaymentGateway
from .sslcommerz import SSLCommerzService


def get_gateway(
    slug: str,
    credentials: dict,
    is_sandbox: bool,
    *,
    success_url: str,
    fail_url: str,
    cancel_url: str,
    ipn_url: str,
) -> AbstractPaymentGateway:
    """Return an initialised gateway service for the given slug.

    Args:
        slug: Matches `TenantPaymentGateway.gateway_slug`.
        credentials: Raw credentials dict stored on the gateway config.
        is_sandbox: Whether to target the sandbox environment.
        success_url / fail_url / cancel_url / ipn_url: Callback URLs.

    Raises:
        ValueError: If the slug is not a known/supported gateway.
    """
    if slug == "sslcommerz":
        return SSLCommerzService(
            store_id=credentials.get("store_id", ""),
            store_password=credentials.get("store_password", ""),
            is_sandbox=is_sandbox,
            success_url=success_url,
            fail_url=fail_url,
            cancel_url=cancel_url,
            ipn_url=ipn_url,
        )

    raise ValueError(f"Unknown payment gateway: '{slug}'")
