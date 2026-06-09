import re

from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.utils import DatabaseError
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import serializers

from apps.identity.models import User
from .models import (
    Tenant, Domain, Invitation, PlatformRole, PlatformUserRole, PlatformSettings,
    PlatformGymProfile, PlatformGymPreferences, PlatformNotificationPreferences,
)

SUBDOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{3,63}(?<!-)$")


def normalize_subdomain(value: str) -> str:
    return (value or "").strip().lower()


def resolve_base_domain(request=None) -> str:
    explicit = getattr(settings, "TENANT_BASE_DOMAIN", "") or ""
    explicit = explicit.strip().lower()
    if explicit:
        return explicit

    if request is None:
        return "localhost"

    host = request.get_host().split(":")[0].strip().lower()
    if host in {"localhost", "127.0.0.1"}:
        return "localhost"

    parts = host.split(".")
    if len(parts) > 2:
        return ".".join(parts[1:])
    return host


def full_domain_for_subdomain(subdomain: str, request=None) -> str:
    base_domain = resolve_base_domain(request)
    subdomain = normalize_subdomain(subdomain)
    if base_domain in {"localhost", "127.0.0.1"}:
        return f"{subdomain}.localhost"
    return f"{subdomain}.{base_domain}"


class TenantSelfRegistrationSerializer(serializers.Serializer):
    subdomain = serializers.CharField(max_length=63)
    company_name = serializers.CharField(max_length=255)
    admin_email = serializers.EmailField()
    admin_full_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    plan = serializers.CharField(max_length=50, required=False, allow_blank=True, default="starter")

    def validate_subdomain(self, value):
        normalized = normalize_subdomain(value)
        if not SUBDOMAIN_RE.match(normalized):
            raise serializers.ValidationError(
                "Subdomain must be 3-63 chars, lowercase letters/numbers/hyphens, and cannot start/end with a hyphen."
            )

        request = self.context.get("request")
        domain_value = full_domain_for_subdomain(normalized, request=request)
        with schema_context(get_public_schema_name()):
            exists = Domain.objects.filter(domain=domain_value).exists()
            pending = Invitation.objects.filter(
                token_type__in=[Invitation.TOKEN_TYPE_VERIFICATION, Invitation.TOKEN_TYPE_INVITATION],
                subdomain=normalized,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).exists()
        if exists and not self.context.get("allow_existing_subdomain", False):
            raise serializers.ValidationError("This subdomain is already in use.")
        if pending and not self.context.get("allow_existing_subdomain", False):
            raise serializers.ValidationError("This subdomain already has a pending invitation.")
        return normalized

    def validate_admin_email(self, value):
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")
        return value.lower().strip()


class SuperadminInvitationSerializer(serializers.Serializer):
    subdomain = serializers.CharField(max_length=63)
    company_name = serializers.CharField(max_length=255)
    admin_email = serializers.EmailField()
    admin_full_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    custom_domain = serializers.CharField(max_length=253, required=False, allow_blank=True)
    max_users = serializers.IntegerField(required=False, min_value=1)
    max_branches = serializers.IntegerField(required=False, min_value=1)
    plan = serializers.CharField(max_length=50, required=False, allow_blank=True)

    def validate_subdomain(self, value):
        normalized = normalize_subdomain(value)
        if not SUBDOMAIN_RE.match(normalized):
            raise serializers.ValidationError(
                "Subdomain must be 3-63 chars, lowercase letters/numbers/hyphens, and cannot start/end with a hyphen."
            )

        request = self.context.get("request")
        domain_value = full_domain_for_subdomain(normalized, request=request)
        with schema_context(get_public_schema_name()):
            exists = Domain.objects.filter(domain=domain_value).exists()
            pending = Invitation.objects.filter(
                token_type__in=[Invitation.TOKEN_TYPE_VERIFICATION, Invitation.TOKEN_TYPE_INVITATION],
                subdomain=normalized,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).exists()
        if exists and not self.context.get("allow_existing_subdomain", False):
            raise serializers.ValidationError("This subdomain is already in use.")
        if pending:
            raise serializers.ValidationError("This subdomain already has a pending invitation.")
        return normalized

    def validate_admin_email(self, value):
        return value.lower().strip()

    def validate_custom_domain(self, value):
        normalized = (value or "").strip().lower()
        if not normalized:
            return ""
        with schema_context(get_public_schema_name()):
            exists = Domain.objects.filter(domain=normalized).exists()
        if exists:
            raise serializers.ValidationError("This custom domain is already in use.")
        return normalized


class InvitationTokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=255)


class PasswordSetupSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=255)
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError("Passwords do not match.")
        return attrs


class TenantAuthSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    subdomain = serializers.CharField(required=False, allow_blank=True)
    domain = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        email = attrs.get("email", "").strip().lower()
        subdomain = normalize_subdomain(attrs.get("subdomain", ""))
        domain = (attrs.get("domain") or "").strip().lower()

        if not domain and not subdomain:
            raise serializers.ValidationError("Provide either domain or subdomain.")

        attrs["email"] = email
        attrs["subdomain"] = subdomain
        attrs["domain"] = domain
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    subdomain = serializers.CharField(required=False, allow_blank=True)
    domain = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        attrs["email"] = attrs.get("email", "").strip().lower()
        attrs["subdomain"] = normalize_subdomain(attrs.get("subdomain", ""))
        attrs["domain"] = (attrs.get("domain") or "").strip().lower()

        if not attrs["domain"] and not attrs["subdomain"]:
            raise serializers.ValidationError("Provide either domain or subdomain.")

        return attrs


class TenantStatusSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField()


class TenantAdminUserSerializer(serializers.ModelSerializer):
    last_login_at = serializers.DateTimeField(source="last_login", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "is_active",
            "email_verified",
            "password_set_at",
            "last_login_at",
        ]


class TenantListSerializer(serializers.ModelSerializer):
    domains = serializers.SerializerMethodField()
    admins = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "schema_name",
            "slug",
            "code",
            "owner_email",
            "billing_email",
            "plan",
            "status",
            "is_enabled",
            "timezone",
            "locale",
            "currency",
            "custom_domain_enabled",
            "max_users",
            "max_branches",
            "max_members_per_branch",
            "max_trainers_per_branch",
            "max_employees_per_branch",
            "created_at",
            "domains",
            "admins",
        ]

    def get_domains(self, obj):
        return list(obj.domains.values_list("domain", flat=True))

    def get_admins(self, obj):
        if obj.schema_name == get_public_schema_name():
            return []

        try:
            with schema_context(obj.schema_name):
                admins = User.objects.filter(role__in=["admin", "superuser"]).order_by("email", "id")
                return TenantAdminUserSerializer(admins, many=True).data
        except DatabaseError:
            return []


class TenantUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "name",
            "owner_email",
            "billing_email",
            "plan",
            "status",
            "is_enabled",
            "timezone",
            "locale",
            "currency",
            "custom_domain_enabled",
            "max_users",
            "max_branches",
            "max_members_per_branch",
            "max_trainers_per_branch",
            "max_employees_per_branch",
            "features",
            "metadata",
        ]


class PlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSettings
        fields = [
            "id",
            "default_timezone",
            "default_language",
            "default_currency",
            "enable_currency_conversion",
            "usd_to_bdt_rate",
            "exchange_rates",
            "enable_custom_domains",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


# ---------------------------------------------------------------
# Platform-schema settings serializers
# (counterparts to the tenant-only dashboard serializers)
# ---------------------------------------------------------------

class PlatformGymProfileSerializer(serializers.ModelSerializer):
    logo_url = serializers.CharField(allow_blank=True, required=False)
    website = serializers.URLField(allow_blank=True, required=False)

    def validate_logo_url(self, value):
        from django.core.validators import URLValidator
        from django.core.exceptions import ValidationError as DjangoValidationError

        normalized = (value or "").strip()
        if not normalized:
            return ""
        if normalized.startswith('/media/'):
            return normalized
        validator = URLValidator()
        try:
            validator(normalized)
        except DjangoValidationError as exc:
            raise serializers.ValidationError("Enter a valid URL.") from exc
        return normalized

    class Meta:
        model = PlatformGymProfile
        fields = [
            "id", "gym_name", "email", "phone", "website", "address", "timezone",
            "logo_url", "logo_width", "logo_height", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class PlatformGymPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformGymPreferences
        fields = ["id", "language", "currency", "date_format", "week_start", "theme", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class PlatformNotificationPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformNotificationPreferences
        fields = [
            "id", "payment_received", "new_member_signup", "reminder_due",
            "weekly_report", "push_notifications", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class PlatformInvitationCreateSerializer(serializers.Serializer):
    """Superadmin invites a new (or existing) public-schema user to the platform team."""

    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    role = serializers.PrimaryKeyRelatedField(queryset=PlatformRole.objects.all())

    def validate_email(self, value):
        return value.lower().strip()

    def validate(self, attrs):
        email = attrs["email"]
        role = attrs["role"]
        with schema_context(get_public_schema_name()):
            existing_user = User.objects.filter(email__iexact=email, tenant__isnull=True).first()
            if existing_user is not None:
                already = PlatformUserRole.objects.filter(user=existing_user, role=role).exists()
                if already:
                    raise serializers.ValidationError(
                        {"email": "This user already has that platform role."}
                    )
            pending = Invitation.objects.filter(
                token_type=Invitation.TOKEN_TYPE_PLATFORM_INVITE,
                email__iexact=email,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).exists()
            if pending:
                raise serializers.ValidationError(
                    {"email": "This email already has a pending platform invitation."}
                )
        return attrs


class PlatformInvitationListSerializer(serializers.ModelSerializer):
    role_id = serializers.IntegerField(source="platform_role_id", read_only=True)
    role_name = serializers.CharField(source="platform_role.name", read_only=True, default="")
    role_slug = serializers.CharField(source="platform_role.slug", read_only=True, default="")
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "invitee_full_name",
            "role_id",
            "role_name",
            "role_slug",
            "invited_by_email",
            "expires_at",
            "is_expired",
            "used_at",
            "created_at",
        ]


class PlatformInviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=255)
    full_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs
