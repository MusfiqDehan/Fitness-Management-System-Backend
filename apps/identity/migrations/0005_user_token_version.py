from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0004_query_optimization_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="token_version",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Incremented on password change to invalidate all outstanding JWTs.",
            ),
        ),
    ]
