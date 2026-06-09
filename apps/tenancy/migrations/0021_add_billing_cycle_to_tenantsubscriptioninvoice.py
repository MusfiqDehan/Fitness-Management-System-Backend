# Generated migration — adds billing_cycle field to TenantSubscriptionInvoice.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0020_platformpackage_max_members_per_branch_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantsubscriptioninvoice',
            name='billing_cycle',
            field=models.CharField(
                choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')],
                default='monthly',
                max_length=10,
            ),
        ),
    ]
