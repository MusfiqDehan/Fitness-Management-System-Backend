from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0027_platformgympreferences_bdt_taka_symbol"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantsubscriptioninvoice",
            name="payment_type",
            field=models.CharField(
                choices=[
                    ("package", "Package"),
                    ("setup_fee", "Setup Fee"),
                    ("other", "Other"),
                ],
                default="package",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="tenantsubscriptioninvoice",
            name="custom_label",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="tenantsubscriptioninvoice",
            name="base_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="tenantsubscriptioninvoice",
            name="adjustment_type",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("addition", "Addition"),
                    ("deduction", "Deduction"),
                ],
                default="none",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="tenantsubscriptioninvoice",
            name="adjustment_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=12),
        ),
        migrations.AddField(
            model_name="tenantsubscriptioninvoice",
            name="adjustment_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
