from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


# ---------------------------------------------------------------
# Tenant (lives in the public/shared PostgreSQL schema)
#
# Extends TenantMixin which adds:
#   - schema_name (CharField, max 63 chars) — the PostgreSQL schema
#     name used to isolate this tenant's data.
#   - auto_create_schema = True — automatically creates the schema
#     when a Tenant is saved for the first time.
#
# NOTE: Do NOT add ForeignKey fields pointing to AUTH_USER_MODEL
# here. The User model lives in each tenant's schema; a cross-
# schema FK from the public schema is not supported.
# ---------------------------------------------------------------
class Tenant(TenantMixin):
    # Identity
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    code = models.CharField(max_length=50, unique=True)

    # Config
    timezone = models.CharField(max_length=50, default="UTC")
    currency = models.CharField(max_length=10, default="USD")
    locale = models.CharField(max_length=10, default="en")

    # Subscription
    plan = models.CharField(max_length=50, default="free")
    billing_email = models.EmailField(blank=True)
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
        default="trial",
    )

    # Limits
    max_users = models.IntegerField(default=10)
    max_branches = models.IntegerField(default=1)

    # Features (feature flags per tenant plan)
    features = models.JSONField(default=dict, blank=True)

    # Ownership — stored as email since User is tenant-scoped
    owner_email = models.EmailField(null=True, blank=True)

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    auto_create_schema = True

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------
# Domain (lives in the public/shared schema)
#
# Extends DomainMixin which adds:
#   - domain (CharField, unique) — the hostname used for routing
#   - tenant (ForeignKey → Tenant)
#   - is_primary (BooleanField) — marks the canonical domain
#
# A tenant can have multiple Domain rows (e.g. subdomain +
# custom domain). The middleware resolves the incoming request
# hostname against this table to activate the correct tenant
# schema before the view is called.
# ---------------------------------------------------------------
class Domain(DomainMixin):
    def save(self, *args, **kwargs):
        if self.domain:
            self.domain = self.domain.strip().lower()
        super().save(*args, **kwargs)