import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("membership", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("attendance", "0002_query_optimization_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessdevice",
            name="device_profile",
            field=models.CharField(default="zkteco_f18", max_length=64),
        ),
        migrations.CreateModel(
            name="FingerprintEnrollmentSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device_uid", models.CharField(max_length=64)),
                ("fingerprint_slot", models.PositiveSmallIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("userinfo_sent", "Userinfo Sent"),
                            ("enroll_sent", "Enroll Sent"),
                            ("awaiting_scan", "Awaiting Scan"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                            ("expired", "Expired"),
                        ],
                        default="queued",
                        max_length=20,
                    ),
                ),
                ("command_trace", models.JSONField(blank=True, default=list)),
                ("failure_reason", models.TextField(blank=True, default="")),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "access_device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="enrollment_sessions",
                        to="attendance.accessdevice",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="fingerprint_enrollment_sessions_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fingerprint_enrollment_sessions",
                        to="membership.member",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["access_device", "status"], name="idx_enroll_dev_status"),
                    models.Index(fields=["device_uid", "access_device"], name="idx_enroll_uid_dev"),
                ],
            },
        ),
    ]
