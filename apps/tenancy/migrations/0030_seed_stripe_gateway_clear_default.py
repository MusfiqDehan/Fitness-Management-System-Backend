"""Seed Stripe gateway and clear any default subscription gateway.

There is intentionally no default payment gateway — tenants and members
must choose which enabled gateway to use for each payment.
"""
from django.conf import settings
from django.db import migrations


STRIPE_CONFIG_SCHEMA = [
    {"key": "publishable_key", "label": "Publishable Key", "type": "text", "required": True},
    {"key": "secret_key", "label": "Secret Key", "type": "password", "required": True},
]


def seed_stripe_and_clear_default(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")

    publishable = (getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "").strip()
    secret = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    platform_credentials = {}
    if publishable and secret:
        platform_credentials = {
            "publishable_key": publishable,
            "secret_key": secret,
        }

    gateway, created = PaymentGateway.objects.get_or_create(
        slug="stripe",
        defaults={
            "name": "Stripe",
            "description": (
                "Accept cards and local payment methods worldwide via Stripe Checkout."
            ),
            "is_enabled_for_tenants": True,
            "config_schema": STRIPE_CONFIG_SCHEMA,
            "platform_credentials": platform_credentials,
            "is_sandbox": True,
            "is_default_for_subscriptions": False,
            "sort_order": 20,
        },
    )
    if not created:
        updates = []
        if gateway.config_schema != STRIPE_CONFIG_SCHEMA:
            gateway.config_schema = STRIPE_CONFIG_SCHEMA
            updates.append("config_schema")
        if platform_credentials and not (gateway.platform_credentials or {}):
            gateway.platform_credentials = platform_credentials
            updates.append("platform_credentials")
        if updates:
            gateway.save(update_fields=[*updates, "updated_at"])

    # No gateway should be the implicit default anymore.
    PaymentGateway.objects.filter(is_default_for_subscriptions=True).update(
        is_default_for_subscriptions=False,
    )


def unseed_stripe(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")
    PaymentGateway.objects.filter(slug="stripe").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0029_seed_pos_feature"),
    ]

    operations = [
        migrations.RunPython(seed_stripe_and_clear_default, reverse_code=unseed_stripe),
    ]
