from django.db import migrations, models

LEGACY_ZKTECO_PROFILE_MAP = {
    "zkteco_f18": ("zkteco", "F18"),
    "zkteco_f18_pro": ("zkteco", "F18 Pro"),
    "zkteco_k40": ("zkteco", "K40"),
    "zkteco_k60": ("zkteco", "K60"),
}


def migrate_legacy_profiles(apps, schema_editor):
    AccessDevice = apps.get_model("attendance", "AccessDevice")
    for legacy_key, (profile_key, device_model) in LEGACY_ZKTECO_PROFILE_MAP.items():
        AccessDevice.objects.filter(device_profile=legacy_key).update(
            device_profile=profile_key,
            device_model=device_model,
        )


def reverse_legacy_profiles(apps, schema_editor):
    AccessDevice = apps.get_model("attendance", "AccessDevice")
    reverse_map = {
        model: legacy for legacy, (_profile, model) in LEGACY_ZKTECO_PROFILE_MAP.items()
    }
    for device in AccessDevice.objects.filter(device_profile="zkteco").iterator():
        legacy = reverse_map.get((device.device_model or "").strip())
        if legacy:
            device.device_profile = legacy
            device.device_model = ""
            device.save(update_fields=["device_profile", "device_model"])


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0003_fingerprint_enrollment"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessdevice",
            name="device_model",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AlterField(
            model_name="accessdevice",
            name="device_profile",
            field=models.CharField(default="zkteco", max_length=64),
        ),
        migrations.RunPython(migrate_legacy_profiles, reverse_legacy_profiles),
    ]
