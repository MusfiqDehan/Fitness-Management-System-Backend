from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0003_sitesettings_contact_fields"),
    ]

    operations = [
        migrations.DeleteModel(
            name="SiteSettings",
        ),
    ]
