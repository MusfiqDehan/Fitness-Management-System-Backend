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

from .models import (
    PlatformPackage,
    PlatformPackageFeature,
    Tenant,
    TenantFeatureFlag,
)


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

    plan_slug = tenant.plan or "trial"
    # "free" is a legacy alias for the trial package used before the billing
    # system was introduced.  Map it to "trial" so tenants created before the
    # billing migration still get their features synced correctly.
    if plan_slug == "free":
        plan_slug = "trial"

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

    return summary


def expire_grace_periods(now=None) -> int:
    """Disable feature flags whose grace_until has passed. Called by daily cron."""
    now = now or timezone.now()
    qs = TenantFeatureFlag.objects.filter(grace_until__lt=now, is_enabled=True)
    count = qs.count()
    qs.update(is_enabled=False, grace_until=None)
    return count


def tenant_has_feature(tenant, feature_key: str) -> bool:
    """Check whether a tenant currently has access to a given feature."""
    if tenant is None:
        return False
    flag = TenantFeatureFlag.objects.filter(
        tenant=tenant, feature__key=feature_key
    ).first()
    if flag is None:
        return False
    return flag.is_effectively_enabled
