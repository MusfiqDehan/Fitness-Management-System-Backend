from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0005_query_optimization_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="gympreferences",
            name="topbar_show_date",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="gympreferences",
            name="topbar_show_description",
            field=models.BooleanField(default=True),
        ),
    ]
