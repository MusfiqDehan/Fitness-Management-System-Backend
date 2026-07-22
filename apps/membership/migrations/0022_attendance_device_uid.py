from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("membership", "0021_coupon_code_max_length_32"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendance",
            name="device_uid",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
