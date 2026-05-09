import hashlib
import secrets
from datetime import timedelta

from django.db import models
from django_tenants.models import TenantMixin, DomainMixin
from django.utils import timezone


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
# schema FK from the public schema is not supported. The supported
# relationship direction is User.tenant -> Tenant.
# ---------------------------------------------------------------
class Tenant(TenantMixin):
    ENTRY_ALLOWED_STATUSES = {"active", "trial"}

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
    is_enabled = models.BooleanField(default=True)

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

    def allows_user_entry(self):
        return self.is_enabled and self.status in self.ENTRY_ALLOWED_STATUSES


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


class Invitation(models.Model):
    TOKEN_TYPE_VERIFICATION = "verification"
    TOKEN_TYPE_INVITATION = "invitation"
    TOKEN_TYPE_PASSWORD_RESET = "password_reset"
    TOKEN_TYPE_PLATFORM_INVITE = "platform_invite"

    TOKEN_TYPE_CHOICES = [
        (TOKEN_TYPE_VERIFICATION, "Verification"),
        (TOKEN_TYPE_INVITATION, "Invitation"),
        (TOKEN_TYPE_PASSWORD_RESET, "Password Reset"),
        (TOKEN_TYPE_PLATFORM_INVITE, "Platform Team Invitation"),
    ]

    token_type = models.CharField(max_length=20, choices=TOKEN_TYPE_CHOICES)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="invitations",
    )
    email = models.EmailField()
    invitee_full_name = models.CharField(max_length=120, blank=True, default="")
    subdomain = models.CharField(max_length=100)
    company_name = models.CharField(max_length=255)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    invited_by_email = models.EmailField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Phase 0 — when superadmin invites a platform employee (not a tenant user),
    # this stores which PlatformRole they should receive on acceptance.
    platform_role = models.ForeignKey(
        "tenancy.PlatformRole",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations",
    )

    class Meta:
        indexes = [
            models.Index(fields=["token_type", "email"], name="idx_invite_type_email"),
            models.Index(fields=["expires_at"], name="idx_invite_expires"),
        ]

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_usable(self):
        return self.used_at is None and not self.is_expired

    @classmethod
    def issue_token(cls, *, token_type, email, subdomain, company_name, tenant=None, invitee_full_name="",
                    invited_by_email="", ttl_minutes=60, metadata=None, platform_role=None):
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        invitation = cls.objects.create(
            token_type=token_type,
            tenant=tenant,
            email=email,
            invitee_full_name=invitee_full_name or "",
            subdomain=subdomain,
            company_name=company_name,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
            invited_by_email=invited_by_email,
            metadata=metadata or {},
            platform_role=platform_role,
        )
        return raw_token, invitation

    @classmethod
    def from_raw_token(cls, raw_token, *, for_update=False):
        token_hash = hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()
        queryset = cls.objects
        if for_update:
            queryset = queryset.select_for_update()
        return queryset.filter(token_hash=token_hash).first()


class EmailQueue(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]

    PURPOSE_VERIFICATION = "verification"
    PURPOSE_INVITATION = "invitation"
    PURPOSE_PASSWORD_RESET = "password_reset"

    PURPOSE_CHOICES = [
        (PURPOSE_VERIFICATION, "Verification"),
        (PURPOSE_INVITATION, "Invitation"),
        (PURPOSE_PASSWORD_RESET, "Password Reset"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.SET_NULL, null=True, blank=True, related_name="emails")
    to_email = models.EmailField()
    subject = models.CharField(max_length=255)
    html_body = models.TextField(blank=True, default="")
    text_body = models.TextField(blank=True, default="")
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    context = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"], name="idx_email_status_created"),
        ]


class TenantAuditLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    actor_email = models.EmailField(blank=True, default="")
    actor_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=120)
    target_type = models.CharField(max_length=80, blank=True, default="")
    target_id = models.CharField(max_length=120, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"], name="idx_audit_action_created"),
        ]


# ===============================================================
# Permission Levels (shared across Platform RBAC and Tenant RBAC)
# ===============================================================
PERMISSION_LEVEL_NONE = "none"
PERMISSION_LEVEL_VIEW = "view"
PERMISSION_LEVEL_EDIT = "edit"
PERMISSION_LEVEL_FULL = "full"

PERMISSION_LEVEL_CHOICES = [
    (PERMISSION_LEVEL_NONE, "None"),
    (PERMISSION_LEVEL_VIEW, "View"),
    (PERMISSION_LEVEL_EDIT, "Edit"),
    (PERMISSION_LEVEL_FULL, "Full"),
]

PERMISSION_HIERARCHY = {
    PERMISSION_LEVEL_NONE: 0,
    PERMISSION_LEVEL_VIEW: 1,
    PERMISSION_LEVEL_EDIT: 2,
    PERMISSION_LEVEL_FULL: 3,
}


# ===============================================================
# Phase 0 — Platform Team RBAC (shared schema)
#
# These models govern the platform team (superadmin + employees).
# They live in the public schema and only apply to users with
# tenant=None (public-schema users).
# ===============================================================
class PlatformRole(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    is_system = models.BooleanField(default=False, help_text="System roles cannot be deleted.")
    color = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PlatformRolePermission(models.Model):
    role = models.ForeignKey(PlatformRole, on_delete=models.CASCADE, related_name="permissions")
    module_key = models.CharField(max_length=80)
    permission_level = models.CharField(
        max_length=10,
        choices=PERMISSION_LEVEL_CHOICES,
        default=PERMISSION_LEVEL_NONE,
    )

    class Meta:
        unique_together = [("role", "module_key")]
        indexes = [
            models.Index(fields=["module_key"], name="idx_platrp_module"),
        ]

    def __str__(self):
        return f"{self.role.slug}:{self.module_key}={self.permission_level}"


class PlatformUserRole(models.Model):
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.CASCADE,
        related_name="platform_role_assignments",
    )
    role = models.ForeignKey(PlatformRole, on_delete=models.CASCADE, related_name="user_assignments")
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        unique_together = [("user", "role")]
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.user_id} -> {self.role.slug}"


# ===============================================================
# Phase 1 — Feature Registry, Platform Packages, Tenant Flags
# (all live in the public/shared schema)
# ===============================================================
class Feature(models.Model):
    """Catalog of features tenants can be granted access to.

    `key` is a stable string referenced by RolePermission rows
    inside each tenant schema. Cross-schema FKs are not used.
    """

    key = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True, default="")
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    is_system = models.BooleanField(default=False, help_text="System features cannot be disabled.")
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "key"]

    def __str__(self):
        return self.key


class PlatformPackage(models.Model):
    """A SaaS plan a tenant subscribes to (Trial, Starter, Pro, Enterprise).

    `slug` MUST match values used in Tenant.plan.
    """

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_users = models.IntegerField(default=10)
    max_branches = models.IntegerField(default=1)
    trial_days = models.IntegerField(default=0, help_text="Free trial length in days; 0 = no trial.")
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True, help_text="Show on public pricing page.")
    sort_order = models.IntegerField(default=0)
    highlight = models.BooleanField(default=False, help_text="Visually highlighted plan (e.g. 'most popular').")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price_monthly"]

    def __str__(self):
        return f"{self.name} ({self.slug})"


class PlatformPackageFeature(models.Model):
    """Maps which features each package includes."""

    package = models.ForeignKey(PlatformPackage, on_delete=models.CASCADE, related_name="package_features")
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="package_features")
    is_enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = [("package", "feature")]

    def __str__(self):
        return f"{self.package.slug}:{self.feature.key}={'on' if self.is_enabled else 'off'}"


class TenantFeatureFlag(models.Model):
    """Effective feature gate for a tenant.

    Two sources:
      - 'package' rows are auto-synced from Tenant.plan -> PlatformPackageFeature.
      - 'superadmin_override' rows persist across plan changes.

    On downgrade, removed features get grace_until = tenant.subscription_end
    instead of being immediately disabled.
    """

    SOURCE_PACKAGE = "package"
    SOURCE_OVERRIDE = "superadmin_override"

    SOURCE_CHOICES = [
        (SOURCE_PACKAGE, "Package"),
        (SOURCE_OVERRIDE, "Superadmin Override"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="feature_flags")
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="tenant_flags")
    is_enabled = models.BooleanField(default=False)
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default=SOURCE_PACKAGE)
    grace_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_email = models.EmailField(blank=True, default="")

    class Meta:
        unique_together = [("tenant", "feature")]
        indexes = [
            models.Index(fields=["tenant", "is_enabled"], name="idx_tff_tenant_enabled"),
        ]

    def __str__(self):
        return f"{self.tenant.slug}:{self.feature.key}={'on' if self.is_enabled else 'off'}"

    @property
    def is_effectively_enabled(self):
        if self.is_enabled:
            return True
        return bool(self.grace_until and self.grace_until > timezone.now())
