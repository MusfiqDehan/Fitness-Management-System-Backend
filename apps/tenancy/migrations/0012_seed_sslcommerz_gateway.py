"""Seed the initial SSLCommerz PaymentGateway row in the public schema."""
from django.db import migrations


SSLCOMMERZ_CONFIG_SCHEMA = [
    {"key": "store_id", "label": "Store ID", "type": "text", "required": True},
    {"key": "store_password", "label": "Store Password", "type": "password", "required": True},
]


def seed_gateways(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")
    PaymentGateway.objects.get_or_create(
        slug="sslcommerz",
        defaults={
            "name": "SSLCommerz",
            "description": "Bangladesh's leading online payment gateway. Accepts cards, mobile banking, and internet banking.",
            "is_enabled_for_tenants": False,
            "config_schema": SSLCOMMERZ_CONFIG_SCHEMA,
            "platform_credentials": {},
            "is_sandbox": True,
            "sort_order": 10,
        },
    )


def unseed_gateways(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")
    PaymentGateway.objects.filter(slug="sslcommerz").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0011_paymentgateway_alter_platformpackage_included_items"),
    ]

    operations = [
        migrations.RunPython(seed_gateways, reverse_code=unseed_gateways),
    ]
