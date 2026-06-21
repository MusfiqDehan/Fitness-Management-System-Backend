from django.db import migrations, models
import django.db.models.deletion


def remove_orphan_tenant_email_configs(apps, schema_editor):
    TenantEmailConfig = apps.get_model("crm", "TenantEmailConfig")
    TenantEmailConfig.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0026_platformgympreferences_topbar_display"),
        ("crm", "0003_tenantemailconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantemailconfig",
            name="tenant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="email_configs",
                to="tenancy.tenant",
            ),
        ),
        migrations.RunPython(remove_orphan_tenant_email_configs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tenantemailconfig",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="email_configs",
                to="tenancy.tenant",
            ),
        ),
    ]
