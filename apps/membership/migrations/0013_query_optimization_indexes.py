from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("membership", "0012_unified_class_schedule_links"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="memberpackage",
            index=models.Index(
                fields=["is_active", "is_published", "display_order", "name"],
                name="idx_mpkg_active_pub_order",
                condition=models.Q(is_deleted=False),
            ),
        ),
        migrations.AddIndex(
            model_name="member",
            index=models.Index(
                fields=["branch", "is_deleted", "is_active", "end_date"],
                name="idx_member_branch_active_end",
                condition=models.Q(is_deleted=False),
            ),
        ),
        migrations.AddIndex(
            model_name="member",
            index=models.Index(
                fields=["branch", "is_deleted", "created_at"],
                name="idx_member_branch_created",
                condition=models.Q(is_deleted=False),
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["member", "is_deleted", "payment_date"],
                name="idx_payment_member_date",
                condition=models.Q(is_deleted=False),
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["is_deleted", "payment_date", "payment_status"],
                name="idx_payment_date_status",
                condition=models.Q(is_deleted=False),
            ),
        ),
        migrations.AddIndex(
            model_name="attendance",
            index=models.Index(
                fields=["member", "check_in_time"],
                name="idx_attendance_member_checkin",
            ),
        ),
        migrations.AddIndex(
            model_name="attendance",
            index=models.Index(
                fields=["member"],
                name="idx_attendance_open_session",
                condition=models.Q(check_out_time__isnull=True),
            ),
        ),
        migrations.AddIndex(
            model_name="gymschedule",
            index=models.Index(
                fields=["is_deleted", "day_of_week", "start_time"],
                name="idx_gymsched_day_time",
                condition=models.Q(is_deleted=False),
            ),
        ),
    ]
