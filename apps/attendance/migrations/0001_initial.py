from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("membership", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccessDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("device_sn", models.CharField(max_length=100, unique=True)),
                (
                    "mode",
                    models.CharField(
                        choices=[("adms", "ADMS"), ("tcp_relay", "TCP Relay")],
                        default="adms",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("online", "Online"),
                            ("offline", "Offline"),
                            ("error", "Error"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=20,
                    ),
                ),
                ("timezone", models.CharField(default="Asia/Dhaka", max_length=64)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("meta_json", models.JSONField(blank=True, default=dict)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="attendance_access_device_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="attendance_access_device_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="AccessDeviceEndpoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("base_url", models.CharField(blank=True, default="", max_length=255)),
                ("path_prefix", models.CharField(blank=True, default="/iclock", max_length=120)),
                ("relay_host", models.CharField(blank=True, default="", max_length=120)),
                ("relay_port", models.PositiveIntegerField(default=4370)),
                ("api_key_ref", models.CharField(blank=True, default="", max_length=120)),
                ("poll_interval_sec", models.PositiveIntegerField(default=30)),
                ("heartbeat_interval_sec", models.PositiveIntegerField(default=30)),
                ("meta_json", models.JSONField(blank=True, default=dict)),
                (
                    "access_device",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="endpoint",
                        to="attendance.accessdevice",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DeviceCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=80)),
                ("secret_ciphertext", models.TextField()),
                ("is_active", models.BooleanField(default=True)),
                ("rotated_at", models.DateTimeField(auto_now=True)),
                (
                    "access_device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credentials",
                        to="attendance.accessdevice",
                    ),
                ),
            ],
            options={"unique_together": {("access_device", "key")}},
        ),
        migrations.CreateModel(
            name="DeviceUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device_uid", models.CharField(max_length=64)),
                ("name", models.CharField(blank=True, max_length=120, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("unlinked", "Unlinked"), ("linked", "Linked"), ("deleted", "Deleted")],
                        default="unlinked",
                        max_length=20,
                    ),
                ),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "access_device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="device_users",
                        to="attendance.accessdevice",
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="attendance_device_users",
                        to="membership.member",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["device_uid"], name="att_du_device_uid_idx")],
                "unique_together": {("access_device", "device_uid")},
            },
        ),
        migrations.CreateModel(
            name="AttendanceIngestEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_hash", models.CharField(max_length=64, unique=True)),
                ("event_type", models.CharField(max_length=32)),
                ("device_uid", models.CharField(blank=True, default="", max_length=64)),
                ("event_time", models.DateTimeField(blank=True, null=True)),
                ("raw_line", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "access_device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ingest_events",
                        to="attendance.accessdevice",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
