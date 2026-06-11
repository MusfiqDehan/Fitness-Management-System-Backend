from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reminder", "0002_notification_recipient"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["recipient", "created_at"],
                name="idx_notif_recip_created",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["created_at"],
                name="idx_notif_broadcast",
                condition=models.Q(recipient__isnull=True),
            ),
        ),
    ]
