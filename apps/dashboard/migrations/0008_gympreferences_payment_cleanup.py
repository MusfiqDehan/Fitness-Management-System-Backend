from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0007_gympreferences_bdt_taka_symbol"),
    ]

    operations = [
        migrations.AddField(
            model_name="gympreferences",
            name="payment_auto_delete_credentials_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="gympreferences",
            name="payment_cleanup_run_at_1",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="gympreferences",
            name="payment_cleanup_run_at_2",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
