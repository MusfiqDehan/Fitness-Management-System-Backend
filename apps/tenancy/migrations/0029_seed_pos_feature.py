"""Backfill the `pos` feature for existing tenants.

`sync_features` creates the `Feature` catalog row on every deploy, but
`seed_platform_packages` is commented out of `entrypoint.sh`, so nothing
creates the `PlatformPackageFeature` mappings or the per-tenant
`TenantFeatureFlag` rows. Without those, `tenant_has_feature("pos")` is
False for every existing tenant — including tenant admins, who bypass RBAC
but not the package gate — and POS would ship dark.

`pos` is included in all three package tiers, so every tenant on a known
plan gets it enabled. Idempotent: safe to re-run, and it never touches a
`superadmin_override` flag a platform admin has already set.
"""
from django.db import migrations

FEATURE_KEY = "pos"
FEATURE_NAME = "POS"
# Mirrors the `features` lists in
# apps/tenancy/management/commands/seed_platform_packages.py
PACKAGE_SLUGS = ("starter", "growth", "enterprise")


def seed_pos_feature(apps, schema_editor):
    Feature = apps.get_model("tenancy", "Feature")
    PlatformPackage = apps.get_model("tenancy", "PlatformPackage")
    PlatformPackageFeature = apps.get_model("tenancy", "PlatformPackageFeature")
    Tenant = apps.get_model("tenancy", "Tenant")
    TenantFeatureFlag = apps.get_model("tenancy", "TenantFeatureFlag")

    feature, _ = Feature.objects.get_or_create(
        key=FEATURE_KEY,
        defaults={
            "name": FEATURE_NAME,
            "description": "Finance",
            "is_system": True,
            "sort_order": 0,
        },
    )

    packages = list(PlatformPackage.objects.filter(slug__in=PACKAGE_SLUGS))
    for package in packages:
        PlatformPackageFeature.objects.update_or_create(
            package=package,
            feature=feature,
            defaults={"is_enabled": True},
        )

    entitled_slugs = {p.slug for p in packages}
    for tenant in Tenant.objects.all():
        if tenant.plan not in entitled_slugs:
            continue
        # Never clobber a deliberate platform-admin override.
        TenantFeatureFlag.objects.get_or_create(
            tenant=tenant,
            feature=feature,
            defaults={"is_enabled": True, "source": "package"},
        )


def unseed_pos_feature(apps, schema_editor):
    """Remove the catalog row; cascades drop package mappings and flags."""
    Feature = apps.get_model("tenancy", "Feature")
    Feature.objects.filter(key=FEATURE_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0028_tenantsubscriptioninvoice_payment_metadata"),
    ]

    operations = [
        migrations.RunPython(seed_pos_feature, unseed_pos_feature),
    ]
