from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="paymenttransaction",
            index=models.Index(
                fields=["source_payment", "created_at"],
                name="idx_paytx_source_created",
            ),
        ),
    ]
