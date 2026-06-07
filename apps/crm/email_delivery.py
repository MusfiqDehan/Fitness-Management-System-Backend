import logging

from django.conf import settings
from django.core.mail import get_connection
from django_tenants.utils import schema_context

from .models import EmailConfig, TenantEmailConfig

logger = logging.getLogger(__name__)


def _normalize_tls_ssl(use_tls, use_ssl):
    """Django SMTP backend does not support TLS and SSL simultaneously."""
    normalized_use_tls = bool(use_tls)
    normalized_use_ssl = bool(use_ssl)
    if normalized_use_tls and normalized_use_ssl:
        normalized_use_tls = False
    return normalized_use_tls, normalized_use_ssl


def _build_connection_from_config(config):
    use_tls, use_ssl = _normalize_tls_ssl(config.use_tls, config.use_ssl)
    return get_connection(
        backend=config.email_backend,
        host=config.host,
        port=config.port,
        username=config.host_user,
        password=config.host_password,
        use_tls=use_tls,
        use_ssl=use_ssl,
        timeout=15,
        fail_silently=False,
    )


def resolve_tenant_mail_route(tenant):
    """
    Resolve tenant mail route safely.

    Returns a tuple of (from_email, connection_or_none).
    Falls back to DEFAULT_FROM_EMAIL and Django's default connection whenever
    tenant config is missing, inaccessible, or invalid.
    """
    default_from = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local")

    if tenant is None:
        return default_from, None

    try:
        with schema_context(tenant.schema_name):
            config = TenantEmailConfig.objects.filter(is_active=True, is_deleted=False).first()
    except Exception as exc:
        logger.warning(
            "Tenant email config lookup failed for schema=%s: %s",
            getattr(tenant, "schema_name", "unknown"),
            exc,
        )
        return default_from, None

    if config is None:
        return default_from, None

    from_email = config.default_from_email or config.host_user or default_from

    try:
        connection = _build_connection_from_config(config)
    except Exception as exc:
        logger.warning(
            "Tenant email connection build failed for schema=%s config_id=%s: %s",
            getattr(tenant, "schema_name", "unknown"),
            getattr(config, "id", None),
            exc,
        )
        return default_from, None

    return from_email, connection


def resolve_platform_mail_route():
    """Resolve platform mail route safely from active EmailConfig."""
    default_from = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local")
    default_to = getattr(settings, "CONTACT_EMAIL", default_from)

    try:
        config = EmailConfig.objects.filter(is_active=True, is_deleted=False).first()
    except Exception as exc:
        logger.warning("Platform email config lookup failed: %s", exc)
        return default_from, None, default_to

    if config is None:
        return default_from, None, default_to

    from_email = config.default_from_email or config.host_user or default_from
    to_email = config.contact_email or config.host_user or default_to

    try:
        connection = _build_connection_from_config(config)
    except Exception as exc:
        logger.warning(
            "Platform email connection build failed for config_id=%s: %s",
            getattr(config, "id", None),
            exc,
        )
        return default_from, None, default_to

    return from_email, connection, to_email