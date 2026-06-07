from django.db import models

from utils.base_model import BaseModel


class ContactQuery(models.Model):
    """Stores a contact-us form submission from the public landing page."""

    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=50)
    email = models.EmailField(blank=True, default="")
    package_name = models.CharField(max_length=255, blank=True, default="")
    message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Contact Query"
        verbose_name_plural = "Contact Queries"

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"


class EmailConfig(BaseModel):
    """
    Platform-admin-managed SMTP / email backend configuration.

    Only ONE record should have is_active=True at a time.
    When no active record exists the system falls back to Django settings.
    """

    BACKEND_CHOICES = [
        ("django.core.mail.backends.smtp.EmailBackend", "SMTP"),
        ("django.core.mail.backends.console.EmailBackend", "Console (dev)"),
        ("django.core.mail.backends.dummy.EmailBackend", "Dummy (disabled)"),
    ]

    name = models.CharField(max_length=100, help_text="Friendly label, e.g. 'Production Gmail'")
    email_backend = models.CharField(
        max_length=100,
        choices=BACKEND_CHOICES,
        default="django.core.mail.backends.smtp.EmailBackend",
    )
    host = models.CharField(max_length=255, default="smtp.gmail.com")
    port = models.PositiveIntegerField(default=465)
    use_tls = models.BooleanField(default=False)
    use_ssl = models.BooleanField(default=True)
    host_user = models.CharField(max_length=255, blank=True, default="")
    host_password = models.CharField(max_length=255, blank=True, default="")
    default_from_email = models.EmailField(blank=True, default="")
    contact_email = models.EmailField(
        blank=True,
        default="",
        help_text="Recipient address for contact-form query notifications",
    )

    class Meta:
        ordering = ["-is_active", "-created_at"]
        verbose_name = "Email Config"
        verbose_name_plural = "Email Configs"

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"{self.name} ({status})"


class TenantEmailConfig(BaseModel):
    """
    Tenant-managed SMTP / email backend configuration.

    Only one tenant config may be active at a time in the current schema.
    """

    BACKEND_CHOICES = [
        ("django.core.mail.backends.smtp.EmailBackend", "SMTP"),
        ("django.core.mail.backends.console.EmailBackend", "Console (dev)"),
        ("django.core.mail.backends.dummy.EmailBackend", "Dummy (disabled)"),
    ]

    name = models.CharField(max_length=100, help_text="Friendly label, e.g. 'Gmail SMTP'")
    email_backend = models.CharField(
        max_length=100,
        choices=BACKEND_CHOICES,
        default="django.core.mail.backends.smtp.EmailBackend",
    )
    host = models.CharField(max_length=255, default="smtp.gmail.com")
    port = models.PositiveIntegerField(default=465)
    use_tls = models.BooleanField(default=False)
    use_ssl = models.BooleanField(default=True)
    host_user = models.CharField(max_length=255, blank=True, default="")
    host_password = models.CharField(max_length=255, blank=True, default="")
    default_from_email = models.EmailField(blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")

    class Meta:
        ordering = ["-is_active", "-created_at"]
        verbose_name = "Tenant Email Config"
        verbose_name_plural = "Tenant Email Configs"

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"{self.name} ({status})"
