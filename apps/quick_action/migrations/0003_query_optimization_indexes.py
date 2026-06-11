from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main_app", "0002_remove_gymclub_facilities_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="contact",
            index=models.Index(
                fields=["status", "created_at"],
                name="idx_contact_status_created",
            ),
        ),
        migrations.AddIndex(
            model_name="fithivesupport",
            index=models.Index(
                fields=["status", "created_at"],
                name="idx_fithive_status_created",
            ),
        ),
    ]
