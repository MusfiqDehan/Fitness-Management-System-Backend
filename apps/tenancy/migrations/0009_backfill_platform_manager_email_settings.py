from django.db import migrations


EMAIL_SETTINGS_MODULE_KEY = "platform.email_settings"
PLATFORM_MANAGER_SLUG = "platform_manager"
TARGET_LEVEL = "edit"


def forwards(apps, schema_editor):
    PlatformRole = apps.get_model("tenancy", "PlatformRole")
    PlatformRolePermission = apps.get_model("tenancy", "PlatformRolePermission")

    role = PlatformRole.objects.filter(slug=PLATFORM_MANAGER_SLUG, is_system=True).first()
    if not role:
        return

    perm, created = PlatformRolePermission.objects.get_or_create(
        role=role,
        module_key=EMAIL_SETTINGS_MODULE_KEY,
        defaults={"permission_level": TARGET_LEVEL},
    )
    if created:
        return

    # Backfill legacy rows that were seeded as none before this module shipped.
    if perm.permission_level == "none":
        perm.permission_level = TARGET_LEVEL
        perm.save(update_fields=["permission_level"])


def backwards(apps, schema_editor):
    PlatformRole = apps.get_model("tenancy", "PlatformRole")
    PlatformRolePermission = apps.get_model("tenancy", "PlatformRolePermission")

    role = PlatformRole.objects.filter(slug=PLATFORM_MANAGER_SLUG, is_system=True).first()
    if not role:
        return

    perm = PlatformRolePermission.objects.filter(
        role=role,
        module_key=EMAIL_SETTINGS_MODULE_KEY,
    ).first()
    if not perm:
        return

    if perm.permission_level == TARGET_LEVEL:
        perm.permission_level = "none"
        perm.save(update_fields=["permission_level"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0008_platform_invite_token_type"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
