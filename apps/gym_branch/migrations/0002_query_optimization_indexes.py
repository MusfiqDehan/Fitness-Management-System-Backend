from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gym_branch", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="branch",
            index=models.Index(
                fields=["is_active", "display_order", "id"],
                name="idx_branch_active_order",
            ),
        ),
        migrations.AddIndex(
            model_name="branchshiftrequest",
            index=models.Index(
                fields=["status", "created_at"],
                name="idx_shift_status_created",
            ),
        ),
        migrations.AddIndex(
            model_name="branchshiftrequest",
            index=models.Index(
                fields=["member", "created_at"],
                name="idx_shift_member_created",
            ),
        ),
        migrations.AddIndex(
            model_name="branchshiftrequest",
            index=models.Index(
                fields=["trainer", "created_at"],
                name="idx_shift_trainer_created",
            ),
        ),
    ]
