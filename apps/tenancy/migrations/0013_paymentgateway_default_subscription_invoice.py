"""
0013 — Add is_default_for_subscriptions to PaymentGateway and create
       TenantSubscriptionInvoice for tracking platform → tenant billing.
"""

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0012_seed_sslcommerz_gateway"),
    ]

    operations = [
        # ── Field: PaymentGateway.is_default_for_subscriptions ──────────
        migrations.AddField(
            model_name="paymentgateway",
            name="is_default_for_subscriptions",
            field=models.BooleanField(
                default=False,
                help_text="This gateway is used by the platform to bill tenants for SaaS subscriptions.",
            ),
        ),
        # ── Model: TenantSubscriptionInvoice ────────────────────────────
        migrations.CreateModel(
            name="TenantSubscriptionInvoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_invoices",
                        to="tenancy.tenant",
                    ),
                ),
                ("package_slug", models.CharField(max_length=50)),
                ("package_name", models.CharField(blank=True, default="", max_length=120)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("currency", models.CharField(default="BDT", max_length=10)),
                ("tran_id", models.CharField(max_length=100, unique=True)),
                ("gateway_slug", models.CharField(blank=True, default="", max_length=50)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                            ("trial", "Trial (no charge)"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("gateway_response", models.JSONField(blank=True, default=dict)),
                ("val_id", models.CharField(blank=True, default="", max_length=200)),
                ("validated_at", models.DateTimeField(blank=True, null=True)),
                ("period_start", models.DateTimeField(blank=True, null=True)),
                ("period_end", models.DateTimeField(blank=True, null=True)),
                ("is_trial", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
