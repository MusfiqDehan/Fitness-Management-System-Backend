import logging

from django.conf import settings
from django.core.mail import get_connection

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


def _default_from_address():
    return getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local")


def _from_email_for_config(config, default_from=None):
    default_from = default_from or _default_from_address()
    return config.default_from_email or config.host_user or default_from


def _active_tenant_email_config(tenant):
    if tenant is None:
        return None
    return TenantEmailConfig.objects.filter(
        tenant_id=tenant.id,
        is_active=True,
        is_deleted=False,
    ).first()


def resolve_platform_mail_route():
    """Resolve platform mail route safely from active EmailConfig."""
    default_from = _default_from_address()
    default_to = getattr(settings, "CONTACT_EMAIL", default_from)

    try:
        config = EmailConfig.objects.filter(is_active=True, is_deleted=False).first()
    except Exception as exc:
        logger.warning("Platform email config lookup failed: %s", exc)
        return default_from, None, default_to

    if config is None:
        return default_from, None, default_to

    from_email = _from_email_for_config(config, default_from)
    to_email = config.contact_email or config.host_user or default_to

    try:
        mail_connection = _build_connection_from_config(config)
    except Exception as exc:
        logger.warning(
            "Platform email connection build failed for config_id=%s: %s",
            getattr(config, "id", None),
            exc,
        )
        return default_from, None, default_to

    return from_email, mail_connection, to_email


def resolve_operational_mail_route(tenant):
    """
    Resolve mail route for tenant operational emails.

    Priority: tenant config -> platform admin config -> Django env settings.
    """
    default_from = _default_from_address()

    if tenant is None:
        platform_from, platform_connection, _ = resolve_platform_mail_route()
        return platform_from, platform_connection

    config = _active_tenant_email_config(tenant)

    if config is not None:
        from_email = _from_email_for_config(config, default_from)
        try:
            mail_connection = _build_connection_from_config(config)
            return from_email, mail_connection
        except Exception as exc:
            logger.warning(
                "Tenant email connection build failed for tenant_id=%s config_id=%s: %s",
                getattr(tenant, "id", None),
                getattr(config, "id", None),
                exc,
            )

    platform_from, platform_connection, _ = resolve_platform_mail_route()
    return platform_from, platform_connection


def resolve_tenant_mail_route(tenant):
    """Backward-compatible alias for tenant operational mail resolution."""
    return resolve_operational_mail_route(tenant)
