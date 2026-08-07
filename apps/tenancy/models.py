import hashlib
import secrets
from datetime import timedelta

from django.db import models
from django.db.models import Q
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
    timezone = models.CharField(max_length=50, default="Asia/Dhaka")
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
    max_members_per_branch = models.IntegerField(
        default=0, help_text="Maximum members per branch. 0 means unlimited."
    )
    max_trainers_per_branch = models.IntegerField(
        default=0, help_text="Maximum trainers per branch. 0 means unlimited."
    )
    max_employees_per_branch = models.IntegerField(
        default=0, help_text="Maximum employees (staff) per branch. 0 means unlimited."
    )
    is_enabled = models.BooleanField(default=True)

    # Custom domain self-service toggle (per-tenant). Effective availability also
    # requires the global PlatformSettings.enable_custom_domains master switch and
    # the tenant's 'custom_domain' feature flag.
    custom_domain_enabled = models.BooleanField(
        default=False,
        help_text="When True, this tenant may connect its own custom domain from Settings.",
    )

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
    # Drop the PostgreSQL schema on delete. Without this, tenant-schema
    # identity_user rows keep a cross-schema FK to public.tenancy_tenant and
    # Django admin/shell deletes raise IntegrityError (often seen as HTTP 502).
    auto_drop_schema = True

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def allows_user_entry(self):
        return self.is_enabled and self.status in self.ENTRY_ALLOWED_STATUSES

    def delete(self, force_drop=False, *args, **kwargs):
        from django_tenants.utils import get_public_schema_name

        if self.schema_name == get_public_schema_name():
            raise PermissionError("The public tenant cannot be deleted.")
        return super().delete(force_drop=force_drop, *args, **kwargs)


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
    class Meta:
        indexes = [
            models.Index(
                fields=["tenant", "is_primary", "id"],
                name="idx_domain_tenant_primary",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.domain:
            self.domain = self.domain.strip().lower()
        super().save(*args, **kwargs)


class AccessDeviceRoute(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="access_device_routes",
    )
    access_device_id = models.PositiveBigIntegerField()
    device_sn = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["device_sn"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "access_device_id"],
                name="uniq_access_device_route_per_device",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "is_active"], name="idx_adr_tenant_active"),
        ]

    def __str__(self):
        return f"{self.device_sn} -> {self.tenant.schema_name}"


# ---------------------------------------------------------------
# CustomDomainRequest (public/shared schema)
#
# Tracks a tenant's self-service request to connect a custom domain
# (or their own subdomain, e.g. gym.theircompany.com). The actual
# routable Domain row is only created once the DNS TXT challenge is
# verified, so unverified domains never resolve to a tenant schema.
# ---------------------------------------------------------------
class CustomDomainRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending Verification"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_FAILED, "Verification Failed"),
    ]

    # Hostname (without scheme) tenants must point at the platform, e.g.
    # "gym.theircompany.com". The TXT challenge record name is derived from this.
    VERIFICATION_RECORD_PREFIX = "_fitpulse-verify"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="custom_domain_requests",
    )
    domain = models.CharField(max_length=253, unique=True)
    verification_token = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    last_error = models.CharField(max_length=255, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    created_by_email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_cdr_tenant_status"),
        ]

    def __str__(self):
        return f"{self.domain} -> {self.tenant.slug} [{self.status}]"

    def save(self, *args, **kwargs):
        if self.domain:
            self.domain = self.domain.strip().lower().rstrip(".")
        super().save(*args, **kwargs)

    @property
    def verification_record_name(self):
        return f"{self.VERIFICATION_RECORD_PREFIX}.{self.domain}"

    @property
    def is_verified(self):
        return self.status == self.STATUS_VERIFIED


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
    max_members_per_branch = models.IntegerField(
        default=0, help_text="Maximum members per branch. 0 means unlimited."
    )
    max_trainers_per_branch = models.IntegerField(
        default=0, help_text="Maximum trainers per branch. 0 means unlimited."
    )
    max_employees_per_branch = models.IntegerField(
        default=0, help_text="Maximum employees (staff) per branch. 0 means unlimited."
    )
    trial_days = models.IntegerField(default=0, help_text="Free trial length in days; 0 = no trial.")
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True, help_text="Show on public pricing page.")
    sort_order = models.IntegerField(default=0)
    highlight = models.BooleanField(default=False, help_text="Visually highlighted plan (e.g. 'most popular').")

    # ── Pricing display customisation ──────────────────────────
    badge_label = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Top-right card badge text (e.g. '14 Days Free Trial', 'Most Popular').",
    )
    cta_label = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Call-to-action button label shown on the pricing card.",
    )
    cta_url = models.CharField(
        max_length=255, blank=True, default="",
        help_text="CTA link shown on the pricing card (supports internal paths like /login and full URLs).",
    )
    setup_fee = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Setup fee display text (e.g. 'Tk. 4990' or 'Custom').",
    )
    original_setup_fee = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Strikethrough setup fee display text (e.g. 'Tk. 8990').",
    )
    original_price_monthly = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Strikethrough monthly price shown alongside the current price.",
    )
    original_price_yearly = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Strikethrough yearly price shown when billing toggle is set to annually.",
    )
    included_items = models.JSONField(
        default=list, blank=True,
        help_text="Manually typed 'What's included' list. Overrides auto-generated feature names when non-empty.",
    )
    yearly_discount_percent = models.IntegerField(
        null=True, blank=True,
        help_text=(
            "Yearly discount percentage (0–100) shown as 'You Save X%' next to the billing toggle. "
            "Leave blank to inherit the platform-wide default from PlatformPricingConfig."
        ),
    )
    price_custom_label = models.CharField(
        max_length=100, blank=True, default="",
        help_text="If set, replaces the numeric price display (e.g. 'Custom' for Enterprise plans).",
    )
    price_period_label = models.CharField(
        max_length=100, blank=True, default="",
        help_text="If set, replaces the computed period string (e.g. '(10k – 30k+)/Month').",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price_monthly"]
        indexes = [
            models.Index(
                fields=["is_active", "is_public", "sort_order", "price_monthly"],
                name="idx_platpkg_active_public_sort",
            ),
        ]

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


class PlatformPricingConfig(models.Model):
    """Singleton that stores platform-wide pricing defaults.

    Always use ``PlatformPricingConfig.get_instance()`` — never create
    more than one row (enforced via pk=1 get_or_create).
    """

    default_yearly_discount_percent = models.IntegerField(
        default=0,
        help_text=(
            "Global yearly discount % shown as 'You Save X%' on the pricing page. "
            "Individual packages can override this via their own yearly_discount_percent field."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Pricing Config"
        verbose_name_plural = "Platform Pricing Config"

    def __str__(self):
        return f"PlatformPricingConfig (default discount: {self.default_yearly_discount_percent}%)"

    @classmethod
    def get_instance(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"default_yearly_discount_percent": 0})
        return obj


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
            models.Index(
                fields=["grace_until"],
                name="idx_tff_grace_expiry",
                condition=Q(
                    is_enabled=True,
                    grace_until__isnull=False,
                ),
            ),
        ]

    def __str__(self):
        return f"{self.tenant.slug}:{self.feature.key}={'on' if self.is_enabled else 'off'}"

    @property
    def is_effectively_enabled(self):
        if self.is_enabled:
            return True
        return bool(self.grace_until and self.grace_until > timezone.now())


# ===============================================================
# Payment Gateway Registry (public schema)
#
# Platform admin registers available gateways and controls which
# ones tenants may configure. Each tenant stores their own
# credentials in billing.TenantPaymentGateway (tenant schema).
# Cross-schema FKs are not used — gateways are referenced by slug.
# ===============================================================
class PaymentGateway(models.Model):
    """Catalog of payment gateways the platform makes available to tenants."""

    slug = models.SlugField(max_length=50, unique=True, help_text="Stable identifier, e.g. 'sslcommerz'.")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    is_enabled_for_tenants = models.BooleanField(
        default=False,
        help_text="When True, tenants can configure and use this gateway.",
    )
    config_schema = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of field descriptors that define the credential form tenants must fill in. "
            "Each entry: {key, label, type ('text'|'password'|'boolean'), required (bool)}."
        ),
    )
    platform_credentials = models.JSONField(
        default=dict,
        blank=True,
        help_text="Platform-level credentials for processing SaaS subscription payments (write-only in API).",
    )
    is_sandbox = models.BooleanField(
        default=True,
        help_text="When True, platform-level credentials point to the sandbox/test environment.",
    )
    is_default_for_subscriptions = models.BooleanField(
        default=False,
        help_text=(
            "Deprecated: no gateway is used as an implicit default. "
            "Callers must choose a gateway_slug explicitly for each payment."
        ),
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"


# ===============================================================
# Tenant Subscription Invoice (public schema)
#
# Tracks platform billing of tenants for their SaaS subscriptions.
# One row per payment attempt. Lives in the public schema (FK to
# Tenant, not inside any tenant schema). NOT a BaseModel subclass.
# ===============================================================
class TenantSubscriptionInvoice(models.Model):
    """Records a single subscription billing event for a tenant."""

    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_TRIAL = "trial"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_TRIAL, "Trial (no charge)"),
    ]

    PAYMENT_TYPE_PACKAGE = "package"
    PAYMENT_TYPE_SETUP_FEE = "setup_fee"
    PAYMENT_TYPE_OTHER = "other"
    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_TYPE_PACKAGE, "Package"),
        (PAYMENT_TYPE_SETUP_FEE, "Setup Fee"),
        (PAYMENT_TYPE_OTHER, "Other"),
    ]

    ADJUSTMENT_NONE = "none"
    ADJUSTMENT_ADDITION = "addition"
    ADJUSTMENT_DEDUCTION = "deduction"
    ADJUSTMENT_TYPE_CHOICES = [
        (ADJUSTMENT_NONE, "None"),
        (ADJUSTMENT_ADDITION, "Addition"),
        (ADJUSTMENT_DEDUCTION, "Deduction"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="subscription_invoices",
    )
    package_slug = models.CharField(max_length=50)
    package_name = models.CharField(max_length=120, blank=True, default="")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="BDT")
    tran_id = models.CharField(max_length=100, unique=True)
    gateway_slug = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    gateway_response = models.JSONField(default=dict, blank=True)
    val_id = models.CharField(max_length=200, blank=True, default="")
    validated_at = models.DateTimeField(null=True, blank=True)
    BILLING_CYCLE_MONTHLY = "monthly"
    BILLING_CYCLE_YEARLY = "yearly"
    BILLING_CYCLE_CHOICES = [
        (BILLING_CYCLE_MONTHLY, "Monthly"),
        (BILLING_CYCLE_YEARLY, "Yearly"),
    ]

    billing_cycle = models.CharField(
        max_length=10,
        choices=BILLING_CYCLE_CHOICES,
        default=BILLING_CYCLE_MONTHLY,
    )
    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
        default=PAYMENT_TYPE_PACKAGE,
    )
    custom_label = models.CharField(max_length=200, blank=True, default="")
    base_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    adjustment_type = models.CharField(
        max_length=20,
        choices=ADJUSTMENT_TYPE_CHOICES,
        default=ADJUSTMENT_NONE,
    )
    adjustment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_reason = models.TextField(blank=True, default="")
    # Billing period this invoice covers
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    is_trial = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "created_at"], name="idx_tsubinv_tenant_created"),
            models.Index(fields=["status", "created_at"], name="idx_tsubinv_status_created"),
        ]

    def __str__(self):
        return f"Invoice {self.tran_id} — {self.tenant.schema_name} [{self.status}]"


# ===============================================================
# PlatformSettings (public schema — singleton)
#
# Stores platform-wide defaults configurable by platform admins.
# Only one row should ever exist (pk=1).  Views enforce this via
# get_or_create(pk=1).
# ===============================================================
class PlatformSettings(models.Model):
    """Platform-wide configuration managed by platform admins.

    Acts as a singleton: only one row with pk=1 is expected.
    """

    default_timezone = models.CharField(
        max_length=50,
        default="Asia/Dhaka",
        help_text="IANA timezone used as the default for all tenants that have not set their own.",
    )
    default_language = models.CharField(
        max_length=10,
        default="en",
        help_text="ISO 639-1 language code used as the default for all tenants that have not set their own.",
    )
    default_currency = models.CharField(
        max_length=10,
        default="USD",
        help_text="Currency code used as the default for all tenants that have not set their own.",
    )
    enable_currency_conversion = models.BooleanField(
        default=True,
        help_text="Enable or disable dynamic currency conversion based on the dollar rate or custom rates.",
    )
    usd_to_bdt_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=120.0000,
        help_text="Default USD to BDT exchange rate.",
    )
    exchange_rates = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dynamic exchange rate matrix with USD as the base currency. E.g. {'EUR': 0.92, 'INR': 83.50, 'BDT': 120.0}",
    )
    enable_custom_domains = models.BooleanField(
        default=False,
        help_text="Global master switch. When True, tenants that are individually enabled may connect their own custom domains.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Settings"
        verbose_name_plural = "Platform Settings"

    def __str__(self):
        return f"Platform Settings (tz={self.default_timezone}, lang={self.default_language})"


# ===============================================================
# Platform-schema counterparts for the tenant-only dashboard
# settings models.  These three singletons (pk=1 pattern) store
# the Platform Admin's own gym profile, preferences, and
# notification preferences in the public schema so the shared
# Settings page works for platform admin users too.
# ===============================================================

class PlatformGymProfile(models.Model):
    """Platform Admin's gym / organisation profile (public schema singleton)."""

    gym_name = models.CharField(max_length=150, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    website = models.URLField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    timezone = models.CharField(max_length=50, default="Asia/Dhaka")
    logo_url = models.URLField(max_length=1000, blank=True, default="")
    logo_width = models.PositiveIntegerField(default=120)
    logo_height = models.PositiveIntegerField(default=40)
    # Brand colours as #rrggbb. Empty means "use the built-in palette".
    primary_color = models.CharField(max_length=7, blank=True, default="")
    secondary_color = models.CharField(max_length=7, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Gym Profile"

    def __str__(self):
        return self.gym_name or "Platform Gym Profile"


class PlatformGymPreferences(models.Model):
    """Platform Admin's display preferences (public schema singleton)."""

    LANGUAGE_CHOICES = [
        ("en", "English"),
        ("bn", "বাংলা (Bengali)"),
        ("hi", "हिंदी (Hindi)"),
        ("ar", "العربية (Arabic)"),
        ("ur", "اردو (Urdu)"),
        ("zh", "中文 (Chinese)"),
        ("ja", "日本語 (Japanese)"),
        ("ko", "한국어 (Korean)"),
        ("fr", "Français (French)"),
        ("es", "Español (Spanish)"),
        ("de", "Deutsch (German)"),
        ("pt", "Português (Portuguese)"),
        ("ru", "Русский (Russian)"),
        ("tr", "Türkçe (Turkish)"),
    ]
    CURRENCY_CHOICES = [
        ("USD", "USD — $"),
        ("EUR", "EUR — €"),
        ("GBP", "GBP — £"),
        ("BDT", "BDT — Tk."),
        ("BDTT", "BDT — ৳"),
        ("INR", "INR — ₹"),
        ("AUD", "AUD — A$"),
        ("CAD", "CAD — C$"),
        ("SGD", "SGD — S$"),
        ("AED", "AED — AED"),
        ("SAR", "SAR — SR"),
        ("OMR", "OMR — OMR"),
        ("QAR", "QAR — QR"),
        ("KWD", "KWD — KD"),
        ("BHD", "BHD — BD"),
        ("MYR", "MYR — RM"),
        ("IDR", "IDR — Rp"),
        ("CNY", "CNY — ¥"),
        ("JPY", "JPY — ¥"),
        ("TRY", "TRY — ₺"),
        ("RUB", "RUB — ₽"),
        ("ZAR", "ZAR — R"),
        ("BRL", "BRL — R$"),
    ]
    DATE_FORMAT_CHOICES = [("dmy", "DD/MM/YYYY"), ("mdy", "MM/DD/YYYY")]
    WEEK_START_CHOICES = [("sun", "Sunday"), ("mon", "Monday"), ("sat", "Saturday")]
    THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("system", "System")]

    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default="en")
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default="USD")
    date_format = models.CharField(max_length=20, choices=DATE_FORMAT_CHOICES, default="dmy")
    week_start = models.CharField(max_length=10, choices=WEEK_START_CHOICES, default="sat")
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default="light")
    topbar_show_date = models.BooleanField(default=False)
    topbar_show_description = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Gym Preferences"

    def __str__(self):
        return "Platform Gym Preferences"


class PlatformNotificationPreferences(models.Model):
    """Platform Admin's notification preferences (public schema singleton)."""

    payment_received = models.BooleanField(default=True)
    new_member_signup = models.BooleanField(default=True)
    reminder_due = models.BooleanField(default=True)
    weekly_report = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Notification Preferences"

    def __str__(self):
        return "Platform Notification Preferences"
