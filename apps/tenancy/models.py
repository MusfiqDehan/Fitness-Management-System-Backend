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

    TOKEN_TYPE_CHOICES = [
        (TOKEN_TYPE_VERIFICATION, "Verification"),
        (TOKEN_TYPE_INVITATION, "Invitation"),
        (TOKEN_TYPE_PASSWORD_RESET, "Password Reset"),
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
                    invited_by_email="", ttl_minutes=60, metadata=None):
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
