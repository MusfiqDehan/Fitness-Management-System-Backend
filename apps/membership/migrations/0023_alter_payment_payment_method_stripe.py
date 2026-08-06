# Generated manually — add stripe to Payment.payment_method choices.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("membership", "0022_attendance_device_uid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("bkash", "Bkash"),
                    ("nagad", "Nagad"),
                    ("card", "Card"),
                    ("cash", "Cash"),
                    ("bank_transfer", "Bank Transfer"),
                    ("sslcommerz", "SSLCommerz"),
                    ("stripe", "Stripe"),
                    ("other", "Other"),
                ],
                default="cash",
                max_length=20,
            ),
        ),
    ]
