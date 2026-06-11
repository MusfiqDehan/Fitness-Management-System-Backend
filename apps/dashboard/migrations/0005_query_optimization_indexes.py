from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0004_alter_gympreferences_currency"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(
                fields=["status", "reminder_type"],
                name="idx_reminder_status_type",
            ),
        ),
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(
                fields=["status", "created_at"],
                name="idx_reminder_status_created",
            ),
        ),
    ]
