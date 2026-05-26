"""Ensure SSLCommerz is available for tenant payment gateway configuration."""

from django.db import migrations


SSLCOMMERZ_CONFIG_SCHEMA = [
    {"key": "store_id", "label": "Store ID", "type": "text", "required": True},
    {"key": "store_password", "label": "Store Password", "type": "password", "required": True},
]


def enable_sslcommerz_for_tenants(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")
    gateway, _created = PaymentGateway.objects.get_or_create(
        slug="sslcommerz",
        defaults={
            "name": "SSLCommerz",
            "description": "Bangladesh's leading online payment gateway. Accepts cards, mobile banking, and internet banking.",
            "is_enabled_for_tenants": True,
            "config_schema": SSLCOMMERZ_CONFIG_SCHEMA,
            "platform_credentials": {},
            "is_sandbox": True,
            "sort_order": 10,
        },
    )

    gateway.name = "SSLCommerz"
    gateway.description = "Bangladesh's leading online payment gateway. Accepts cards, mobile banking, and internet banking."
    gateway.config_schema = SSLCOMMERZ_CONFIG_SCHEMA
    gateway.is_enabled_for_tenants = True
    if gateway.sort_order is None:
        gateway.sort_order = 10
    gateway.save()


def disable_sslcommerz_for_tenants(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")
    PaymentGateway.objects.filter(slug="sslcommerz").update(is_enabled_for_tenants=False)


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0013_paymentgateway_default_subscription_invoice"),
    ]

    operations = [
        migrations.RunPython(enable_sslcommerz_for_tenants, reverse_code=disable_sslcommerz_for_tenants),
    ]
