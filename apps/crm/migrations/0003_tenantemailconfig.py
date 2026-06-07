from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crm", "0002_emailconfig"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantEmailConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True, help_text="Whether this item is active and usable")),
                ("is_published", models.BooleanField(default=False, help_text="Whether this item is published/visible")),
                ("is_deleted", models.BooleanField(default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(help_text="Friendly label, e.g. 'Gmail SMTP'", max_length=100)),
                ("email_backend", models.CharField(choices=[("django.core.mail.backends.smtp.EmailBackend", "SMTP"), ("django.core.mail.backends.console.EmailBackend", "Console (dev)"), ("django.core.mail.backends.dummy.EmailBackend", "Dummy (disabled)")], default="django.core.mail.backends.smtp.EmailBackend", max_length=100)),
                ("host", models.CharField(default="smtp.gmail.com", max_length=255)),
                ("port", models.PositiveIntegerField(default=465)),
                ("use_tls", models.BooleanField(default=False)),
                ("use_ssl", models.BooleanField(default=True)),
                ("host_user", models.CharField(blank=True, default="", max_length=255)),
                ("host_password", models.CharField(blank=True, default="", max_length=255)),
                ("default_from_email", models.EmailField(blank=True, default="", max_length=254)),
                ("contact_email", models.EmailField(blank=True, default="", max_length=254)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_created_records", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_deleted_records", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_updated_records", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-is_active", "-created_at"],
                "verbose_name": "Tenant Email Config",
                "verbose_name_plural": "Tenant Email Configs",
            },
        ),
    ]
