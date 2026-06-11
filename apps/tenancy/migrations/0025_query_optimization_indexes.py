from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0024_accessdeviceroute"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="domain",
            index=models.Index(
                fields=["tenant", "is_primary", "id"],
                name="idx_domain_tenant_primary",
            ),
        ),
        migrations.AddIndex(
            model_name="tenantfeatureflag",
            index=models.Index(
                fields=["grace_until"],
                name="idx_tff_grace_expiry",
                condition=models.Q(is_enabled=True, grace_until__isnull=False),
            ),
        ),
        migrations.AddIndex(
            model_name="platformpackage",
            index=models.Index(
                fields=["is_active", "is_public", "sort_order", "price_monthly"],
                name="idx_platpkg_active_public_sort",
            ),
        ),
        migrations.AddIndex(
            model_name="tenantsubscriptioninvoice",
            index=models.Index(
                fields=["tenant", "created_at"],
                name="idx_tsubinv_tenant_created",
            ),
        ),
        migrations.AddIndex(
            model_name="tenantsubscriptioninvoice",
            index=models.Index(
                fields=["status", "created_at"],
                name="idx_tsubinv_status_created",
            ),
        ),
    ]
