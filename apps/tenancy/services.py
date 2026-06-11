"""Tenant feature flag synchronization service.

When a tenant is created or its `plan` changes, this module ensures the
`TenantFeatureFlag` rows match the new package — without disturbing any
`source='superadmin_override'` rows.

Downgrade behaviour: features the new package no longer includes are NOT
disabled immediately. Instead, `grace_until = tenant.subscription_end`
is set so the tenant retains access until billing period ends. A daily
management command sweeps expired grace periods.
"""
from django.utils import timezone

from utils.cache_helpers import (
    TENANT_FEATURE_TTL,
    get_cached_value,
    invalidate_tenant_features,
    tenant_feature_key,
)

from .models import (
    PlatformPackage,
    PlatformPackageFeature,
    Tenant,
    TenantFeatureFlag,
)


PLAN_PACKAGE_ALIASES = {
    "trial": "starter",
    "free": "starter",
    "pro": "starter",
}


def normalize_plan_slug(plan: str | None) -> str:
    plan_slug = (plan or "starter").strip().lower()
    return PLAN_PACKAGE_ALIASES.get(plan_slug, plan_slug)


def sync_tenant_features(tenant: Tenant, *, force_revoke: bool = False) -> dict:
    """Ensure TenantFeatureFlag rows match the tenant's current package.

    Args:
        tenant: The tenant whose flags should be synchronised.
        force_revoke: If True, revoke removed features immediately (no grace).
                      If False (default), set grace_until to subscription_end
                      so the tenant retains access until billing ends.

    Returns:
        A dict summary: {"added": int, "kept": int, "graced": int, "revoked": int}
    """
    summary = {"added": 0, "kept": 0, "graced": 0, "revoked": 0}

    # Map legacy tenant plan slugs to the canonical package slugs used by the
    # seeded feature packages.
    plan_slug = normalize_plan_slug(tenant.plan)

    package = PlatformPackage.objects.filter(slug=plan_slug, is_active=True).first()
    package_features = {}
    if package:
        package_features = {
            pf.feature_id: pf.is_enabled
            for pf in PlatformPackageFeature.objects.filter(package=package)
        }

    existing = {
        flag.feature_id: flag
        for flag in TenantFeatureFlag.objects.filter(tenant=tenant)
    }

    # Step 1: enable / refresh package-sourced features
    for feature_id, enabled in package_features.items():
        flag = existing.get(feature_id)
        if flag is None:
            TenantFeatureFlag.objects.create(
                tenant=tenant,
                feature_id=feature_id,
                is_enabled=enabled,
                source=TenantFeatureFlag.SOURCE_PACKAGE,
                grace_until=None,
            )
            summary["added"] += 1
        else:
            # Skip overrides — they persist across plan changes
            if flag.source == TenantFeatureFlag.SOURCE_OVERRIDE:
                summary["kept"] += 1
                continue
            # Re-enable previously revoked package features (e.g. upgrade restored it)
            flag.is_enabled = enabled
            flag.source = TenantFeatureFlag.SOURCE_PACKAGE
            flag.grace_until = None
            flag.save(update_fields=["is_enabled", "source", "grace_until", "updated_at"])
            summary["kept"] += 1

    # Step 2: handle features the new package doesn't include
    package_feature_ids = set(package_features.keys())
    for feature_id, flag in existing.items():
        if feature_id in package_feature_ids:
            continue
        if flag.source == TenantFeatureFlag.SOURCE_OVERRIDE:
            # Overrides survive; not touched
            continue
        if force_revoke or not tenant.subscription_end:
            flag.is_enabled = False
            flag.grace_until = None
            flag.save(update_fields=["is_enabled", "grace_until", "updated_at"])
            summary["revoked"] += 1
        else:
            # Grace period: keep enabled until subscription_end
            flag.grace_until = tenant.subscription_end
            flag.save(update_fields=["grace_until", "updated_at"])
            summary["graced"] += 1

    invalidate_tenant_features(tenant.id)
    return summary


def expire_grace_periods(now=None) -> int:
    """Disable feature flags whose grace_until has passed. Called by daily cron."""
    now = now or timezone.now()
    qs = TenantFeatureFlag.objects.filter(grace_until__lt=now, is_enabled=True)
    tenant_ids = list(qs.values_list("tenant_id", flat=True).distinct())
    count = qs.count()
    qs.update(is_enabled=False, grace_until=None)
    for tenant_id in tenant_ids:
        invalidate_tenant_features(tenant_id)
    return count


def _load_tenant_enabled_feature_keys(tenant: Tenant) -> set[str]:
    keys: set[str] = set()
    for flag in TenantFeatureFlag.objects.filter(tenant=tenant).select_related(
        "feature"
    ):
        if flag.is_effectively_enabled:
            keys.add(flag.feature.key)
    return keys


def get_tenant_enabled_feature_keys(tenant: Tenant) -> set[str]:
    """Return effectively enabled feature keys for a tenant (cached)."""
    return get_cached_value(
        tenant_feature_key(tenant.id),
        TENANT_FEATURE_TTL,
        lambda: _load_tenant_enabled_feature_keys(tenant),
    )


def tenant_has_feature(tenant, feature_key: str) -> bool:
    """Check whether a tenant currently has access to a given feature."""
    if tenant is None:
        return False
    return feature_key in get_tenant_enabled_feature_keys(tenant)


CUSTOM_DOMAIN_FEATURE_KEY = "custom_domain"


def custom_domain_effectively_enabled(tenant) -> bool:
    """Whether a tenant may use custom-domain self-service.

    Requires ALL of:
      1. The global PlatformSettings.enable_custom_domains master switch.
      2. The per-tenant Tenant.custom_domain_enabled switch.
      3. The tenant's 'custom_domain' feature flag being effectively enabled
         (package- or superadmin-sourced). If no such Feature/flag exists yet,
         this gate is skipped so the two boolean switches remain sufficient.

    Safe to call from either a public or tenant schema connection — the shared
    PlatformSettings/Tenant tables are reachable via the search path.
    """
    from .models import Feature, PlatformSettings

    if tenant is None:
        return False
    if not getattr(tenant, "custom_domain_enabled", False):
        return False

    settings_row = PlatformSettings.objects.filter(pk=1).first()
    if settings_row is not None and not settings_row.enable_custom_domains:
        return False
    if settings_row is None:
        # No platform settings configured yet → treat global switch as OFF.
        return False

    # Optional feature-flag gate. Only enforced when the Feature actually exists.
    if Feature.objects.filter(key=CUSTOM_DOMAIN_FEATURE_KEY).exists():
        return tenant_has_feature(tenant, CUSTOM_DOMAIN_FEATURE_KEY)
    return True
