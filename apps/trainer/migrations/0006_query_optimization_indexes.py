from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trainer", "0005_unified_schedule_fields"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="trainerprofile",
            index=models.Index(
                fields=[
                    "branch",
                    "is_deleted",
                    "is_published",
                    "is_highlighted",
                    "average_rating",
                ],
                name="idx_trainer_branch_pub_rating",
                condition=models.Q(is_deleted=False),
            ),
        ),
        migrations.AddIndex(
            model_name="trainerschedule",
            index=models.Index(
                fields=["scheduled_date", "start_time"],
                name="idx_trsched_pub_date_time",
                condition=models.Q(
                    is_deleted=False,
                    is_published=True,
                    is_cancelled=False,
                ),
            ),
        ),
        migrations.AddIndex(
            model_name="schedulebooking",
            index=models.Index(
                fields=["member", "is_deleted", "status"],
                name="idx_booking_member_status",
                condition=models.Q(is_deleted=False),
            ),
        ),
        migrations.AddIndex(
            model_name="schedulebooking",
            index=models.Index(
                fields=["schedule", "is_deleted", "status"],
                name="idx_booking_schedule_status",
                condition=models.Q(is_deleted=False),
            ),
        ),
    ]
