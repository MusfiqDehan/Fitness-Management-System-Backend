"""Mark the SSLCommerz gateway as the default gateway for SaaS subscription billing.

migration 0013 added the is_default_for_subscriptions field (default=False) but
never set it to True for any gateway. Without this flag set, the
_maybe_initiate_subscription_payment helper always falls through to the
"no gateway configured" branch and returns payment_url=None, so the SSLCommerz
payment window never appears after tenant password setup.

Note: platform_credentials (store_id / store_password) must still be filled in
by a platform admin via the admin interface or the billing API. This migration
only flips the flag so the gateway is selected when credentials are present.
"""
from django.db import migrations


def mark_sslcommerz_default(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")
    PaymentGateway.objects.filter(slug="sslcommerz").update(is_default_for_subscriptions=True)


def unmark_sslcommerz_default(apps, schema_editor):
    PaymentGateway = apps.get_model("tenancy", "PaymentGateway")
    PaymentGateway.objects.filter(slug="sslcommerz").update(is_default_for_subscriptions=False)


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0014_enable_sslcommerz_for_tenants"),
    ]

    operations = [
        migrations.RunPython(mark_sslcommerz_default, reverse_code=unmark_sslcommerz_default),
    ]
