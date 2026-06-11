from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="accessdevice",
            index=models.Index(
                fields=["is_active", "updated_at"],
                name="idx_accessdev_active_updated",
            ),
        ),
        migrations.AddIndex(
            model_name="deviceuser",
            index=models.Index(
                fields=["access_device", "status"],
                name="idx_deviceuser_dev_status",
            ),
        ),
        migrations.AddIndex(
            model_name="attendanceingestevent",
            index=models.Index(
                fields=["access_device", "event_type", "event_time"],
                name="idx_ingest_dev_type_time",
            ),
        ),
    ]
