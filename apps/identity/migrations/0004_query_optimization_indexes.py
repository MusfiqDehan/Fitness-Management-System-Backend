from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0003_alter_user_role"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="user",
            index=models.Index(
                fields=["role", "is_active"],
                name="idx_user_role_active",
            ),
        ),
    ]
