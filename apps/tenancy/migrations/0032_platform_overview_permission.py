"""Grant the new ``platform.overview`` module to existing platform roles.

``seed_platform_roles`` only runs by hand, so without this every platform role
in an already-provisioned database would be missing the permission and get a
403 on the new landing dashboard. Superadmins bypass the check in code, but
platform managers and support agents do not.

Custom roles an operator created themselves are deliberately left alone — the
overview is granted to the three predefined roles only, and anything else stays
under the operator's control.
"""

from django.db import migrations

DEFAULT_LEVELS = {
    "superadmin": "full",
    "platform_manager": "view",
    "support_agent": "view",
}


def grant_overview(apps, schema_editor):
    PlatformRole = apps.get_model("tenancy", "PlatformRole")
    PlatformRolePermission = apps.get_model("tenancy", "PlatformRolePermission")

    for slug, level in DEFAULT_LEVELS.items():
        role = PlatformRole.objects.filter(slug=slug).first()
        if role is None:
            continue
        PlatformRolePermission.objects.update_or_create(
            role=role,
            module_key="platform.overview",
            defaults={"permission_level": level},
        )


def revoke_overview(apps, schema_editor):
    PlatformRolePermission = apps.get_model("tenancy", "PlatformRolePermission")
    PlatformRolePermission.objects.filter(module_key="platform.overview").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0031_brand_colors"),
    ]

    operations = [
        migrations.RunPython(grant_overview, revoke_overview),
    ]
