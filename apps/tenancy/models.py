from utils.base_model import BaseModel
from django.db import models
from django.conf import settings


class Tenant(BaseModel):
    # Identity
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    code = models.CharField(max_length=50, unique=True)

    # Domain
    primary_domain = models.CharField(max_length=255, unique=True)
    custom_domain = models.CharField(max_length=255, null=True, blank=True, unique=True)
    subdomain = models.CharField(max_length=100, unique=True)

    # Config
    timezone = models.CharField(max_length=50, default="UTC")
    currency = models.CharField(max_length=10, default="USD")
    locale = models.CharField(max_length=10, default="en")

    # Subscription
    plan = models.CharField(max_length=50)
    billing_email = models.EmailField()
    subscription_start = models.DateTimeField(null=True, blank=True)
    subscription_end = models.DateTimeField(null=True, blank=True)

    is_trial = models.BooleanField(default=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ("active", "Active"),
            ("suspended", "Suspended"),
            ("cancelled", "Cancelled"),
            ("trial", "Trial"),
        ],
        default="trial"
    )

    # Limits
    max_users = models.IntegerField(default=10)
    max_branches = models.IntegerField(default=1)

    # Features
    features = models.JSONField(default=dict, blank=True)

    # Ownership
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="owned_tenants"
    )

    # Optional (schema-based tenancy)
    db_schema = models.CharField(max_length=100, unique=True, null=True, blank=True)

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name