from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0004_flexible_device_profiles"),
    ]

    operations = [
        migrations.AddField(
            model_name="deviceuser",
            name="card_number",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
