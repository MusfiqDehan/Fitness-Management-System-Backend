from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0021_add_billing_cycle_to_tenantsubscriptioninvoice"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformpackage",
            name="cta_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CTA link shown on the pricing card (supports internal paths like /login and full URLs).",
                max_length=255,
            ),
        ),
    ]
