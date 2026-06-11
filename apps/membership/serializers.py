from decimal import Decimal, InvalidOperation

from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from rest_framework import serializers
import calendar

from apps.dashboard.models import GymPreferences
from utils.currency import convert_currency
from .models import Member, MemberPackage, Payment, Attendance, GymClass, GymSchedule
from datetime import date


def _format_elapsed_ymd(start: date | None, end: date | None = None) -> str:
    """Format elapsed time between two dates as 'x years y months z days'."""
    if start is None:
        return "0 years 0 months 0 days"

    effective_end = end or date.today()
    if start > effective_end:
        return "0 years 0 months 0 days"

    years = effective_end.year - start.year
    months = effective_end.month - start.month
    days = effective_end.day - start.day

    if days < 0:
        prev_month = effective_end.month - 1 or 12
        prev_year = effective_end.year if effective_end.month > 1 else effective_end.year - 1
        days += calendar.monthrange(prev_year, prev_month)[1]
        months -= 1

    if months < 0:
        months += 12
        years -= 1

    if years < 0:
        return "0 years 0 months 0 days"

    return f"{years} years {months} months {days} days"


def _format_elapsed_years(start: date | None, end: date | None = None) -> str:
    """Format elapsed time between two dates as 'x.y years'."""
    if start is None:
        return "0.0 years"

    effective_end = end or date.today()
    if start > effective_end:
        return "0.0 years"

    days = (effective_end - start).days
    years = days / 365.2425
    return f"{years:.1f} years"


class PackageCurrencyDisplayMixin:
    """Provide converted display prices while preserving raw stored values."""

    def _get_platform_settings(self):
        if not hasattr(self, "_platform_settings_cache"):
            with schema_context(get_public_schema_name()):
                from apps.tenancy.models import PlatformSettings

                self._platform_settings_cache = PlatformSettings.objects.filter(pk=1).first()
        return self._platform_settings_cache

    def _get_rate_matrix(self):
        if hasattr(self, "_rate_matrix_cache"):
            return self._rate_matrix_cache

        matrix = {"USD": Decimal("1.0000")}
        settings = self._get_platform_settings()
        if settings and settings.enable_currency_conversion:
            try:
                matrix["BDT"] = Decimal(str(settings.usd_to_bdt_rate))
            except (TypeError, ValueError, InvalidOperation):
                matrix["BDT"] = Decimal("120.0000")

            for code, rate in (settings.exchange_rates or {}).items():
                try:
                    matrix[str(code).upper()] = Decimal(str(rate))
                except (TypeError, ValueError, InvalidOperation):
                    continue

        self._rate_matrix_cache = matrix
        return matrix

    def _resolve_display_currency(self) -> str:
        if hasattr(self, "_display_currency_cache"):
            return self._display_currency_cache

        settings = self._get_platform_settings()
        matrix = self._get_rate_matrix()
        tenant = getattr(connection, "tenant", None)
        tenant_currency = ""
        if tenant is not None:
            tenant_currency = str(getattr(tenant, "currency", "") or "").strip().upper()

        # Mirror dashboard settings resolution so package endpoints return the
        # same effective tenant currency the settings screen exposes.
        gym_preferences_currency = (
            GymPreferences.objects.filter(pk=1).values_list("currency", flat=True).first() or ""
        ).strip().upper()
        platform_default = str(getattr(settings, "default_currency", "") or "").strip().upper()
        preferred_currency = tenant_currency or platform_default or gym_preferences_currency or "USD"

        if settings and settings.enable_currency_conversion:
            if preferred_currency in matrix:
                self._display_currency_cache = preferred_currency
            elif platform_default in matrix:
                self._display_currency_cache = platform_default
            elif gym_preferences_currency in matrix:
                self._display_currency_cache = gym_preferences_currency
            else:
                self._display_currency_cache = "USD"
        else:
            # Conversion disabled: keep amount as-is and preserve resolved label.
            self._display_currency_cache = preferred_currency

        return self._display_currency_cache

    def _serialize_display_price(self, value):
        if value in (None, ""):
            return None

        try:
            amount = Decimal(str(value))
        except (TypeError, ValueError, InvalidOperation):
            return None

        converted = convert_currency(amount, "USD", self._resolve_display_currency())
        return f"{converted:.2f}"


# ----------------------------
# MemberPackage
# ----------------------------
class MemberPackageSerializer(PackageCurrencyDisplayMixin, serializers.ModelSerializer):
    display_currency = serializers.SerializerMethodField()
    display_price = serializers.SerializerMethodField()
    features = serializers.JSONField(required=False, default=list)
    add_ons = serializers.JSONField(required=False, default=list)

    class Meta:
        model = MemberPackage
        fields = (
            'id', 'name', 'package_type', 'duration_in_days', 'price',
            'display_currency', 'display_price',
            'description', 'features', 'add_ons', 'display_order',
            'is_active', 'is_highlighted', 'is_published', 'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at']

    def get_display_currency(self, obj):
        return self._resolve_display_currency()

    def get_display_price(self, obj):
        return self._serialize_display_price(obj.price)


class MemberPackagePublicSerializer(PackageCurrencyDisplayMixin, serializers.ModelSerializer):
    """Public serializer for landing page - only published and active packages."""
    display_currency = serializers.SerializerMethodField()
    display_price = serializers.SerializerMethodField()
    features = serializers.JSONField(required=False, default=list)
    add_ons = serializers.JSONField(required=False, default=list)

    class Meta:
        model = MemberPackage
        fields = (
            'id', 'name', 'package_type', 'duration_in_days', 'price',
            'display_currency', 'display_price',
            'description', 'features', 'add_ons', 'display_order', 'is_highlighted',
        )

    def get_display_currency(self, obj):
        return self._resolve_display_currency()

    def get_display_price(self, obj):
        return self._serialize_display_price(obj.price)


# ----------------------------
# Member
# ----------------------------
class MemberSerializer(serializers.ModelSerializer):
    member_package = MemberPackageSerializer(read_only=True)
    member_package_id = serializers.PrimaryKeyRelatedField(
        queryset=MemberPackage.objects.all(),
        source='member_package',
        write_only=True,
        required=False,
        allow_null=True,
    )
    remaining_days = serializers.IntegerField(read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    duration = serializers.SerializerMethodField()
    duration_years = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    age_years = serializers.SerializerMethodField()
    invitation_pending = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = (
            'id', 'full_name', 'phone_number', 'email', 'gender',
            'date_of_birth', 'address', 'membership_type',
            'member_package', 'member_package_id',
            'start_date', 'end_date', 'remaining_days', 'duration', 'duration_years', 'age', 'age_years',
            'card_id', 'fingerprint_id',
            'emergency_contact_name', 'emergency_contact_phone', 'notes',
            'payment_method', 'payment_status', 'photo',
            'branch', 'branch_name',
            'is_active', 'is_published', 'invitation_pending',
            'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at', 'remaining_days']

    def get_duration(self, obj):
        return _format_elapsed_ymd(obj.start_date)

    def get_duration_years(self, obj):
        return _format_elapsed_years(obj.start_date)

    def get_age(self, obj):
        return _format_elapsed_ymd(obj.date_of_birth)

    def get_age_years(self, obj):
        return _format_elapsed_years(obj.date_of_birth)

    def get_invitation_pending(self, obj):
        return bool(obj.invitation_token)

    def validate(self, attrs):
        membership_type = attrs.get('membership_type', getattr(self.instance, 'membership_type', None))
        email = attrs.get('email', getattr(self.instance, 'email', None))

        if not email:
            raise serializers.ValidationError({'email': 'This field is required.'})

        if membership_type == 'monthly':
            attrs['member_package'] = None

        return attrs


class MemberPublicSerializer(serializers.ModelSerializer):
    """For public registration from landing page."""

    class ActiveBranchPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
        """Resolve active branches lazily so import-time assertions remain valid."""

        def get_queryset(self):
            from apps.gym_branch.models import Branch

            return Branch.objects.filter(is_active=True)

    member_package_id = serializers.PrimaryKeyRelatedField(
        queryset=MemberPackage.objects.filter(is_active=True, is_published=True),
        source='member_package',
        write_only=True,
        required=True,
    )
    branch_id = ActiveBranchPrimaryKeyRelatedField(
        source='branch',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Member
        fields = (
            'full_name', 'phone_number', 'email', 'gender',
            'address', 'membership_type', 'member_package_id',
            'branch_id',
            'emergency_contact_name', 'emergency_contact_phone', 'notes',
        )

    def validate_membership_type(self, value):
        if value != 'package':
            raise serializers.ValidationError('Only package membership is allowed for self-registration.')
        return value

    def create(self, validated_data):
        # Default to the first active branch (Main Branch) if none specified.
        if validated_data.get('branch') is None:
            from apps.gym_branch.models import Branch
            main_branch = Branch.objects.filter(is_active=True).order_by('created_at').first()
            if main_branch is not None:
                validated_data['branch'] = main_branch
        return super().create(validated_data)


# PaymentSerializer (notify dispatch, renewal sync) lives in apps.billing.serializers.

# ----------------------------
# Attendance
# ----------------------------
class AttendanceSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)

    class Meta:
        model = Attendance
        fields = (
            'id', 'member', 'member_name', 'check_in_time',
            'check_out_time', 'entry_method', 'device_id',
            'is_active', 'created_at',
        )
        read_only_fields = ['created_at']


# ----------------------------
# Member Minimal (for dropdowns)
# ----------------------------
class MemberMinimalSerializer(serializers.ModelSerializer):
    """Minimal serializer for member dropdowns - devices page."""
    class Meta:
        model = Member
        fields = ('id', 'full_name', 'phone_number', 'card_id', 'fingerprint_id', 'is_active')


# ----------------------------
# GymClass
# ----------------------------
class GymClassSerializer(serializers.ModelSerializer):
    class_type_display = serializers.CharField(source='get_class_type_display', read_only=True)
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    trainer_name = serializers.CharField(source='trainer_profile.user.full_name', read_only=True, default=None)
    trainer_profile_id = serializers.IntegerField(source='trainer_profile_id', read_only=True)
    image_url = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = GymClass
        fields = (
            'id', 'name', 'class_type', 'class_type_display',
            'level', 'level_display', 'instructor',
            'trainer_profile', 'trainer_profile_id', 'trainer_name',
            'trainer_class', 'duration_minutes', 'capacity', 'description', 'image_url',
            'is_active', 'is_published', 'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at', 'trainer_class', 'trainer_profile_id', 'trainer_name']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is None and not attrs.get('trainer_profile'):
            raise serializers.ValidationError({'trainer_profile': 'Trainer assignment is required.'})
        if self.instance is not None and 'trainer_profile' in attrs and attrs['trainer_profile'] is None:
            raise serializers.ValidationError({'trainer_profile': 'Trainer assignment cannot be removed.'})
        return attrs

    def validate_image_url(self, value):
        normalized = (value or '').strip()
        if not normalized:
            return ''

        if normalized.startswith('/media/'):
            return normalized

        validator = URLValidator()
        try:
            validator(normalized)
        except DjangoValidationError as exc:
            raise serializers.ValidationError('Enter a valid image URL.') from exc

        return normalized


# ----------------------------
# GymSchedule
# ----------------------------
class GymScheduleSerializer(serializers.ModelSerializer):
    day_of_week_display = serializers.CharField(source='get_day_of_week_display', read_only=True)
    trainer_name = serializers.CharField(source='trainer_profile.user.full_name', read_only=True, default=None)
    recurrence_mode_display = serializers.CharField(source='get_recurrence_mode_display', read_only=True)

    class Meta:
        model = GymSchedule
        fields = (
            'id', 'gym_class', 'trainer_profile', 'trainer_schedule', 'title', 'class_type', 'instructor',
            'recurrence_mode', 'recurrence_mode_display', 'scheduled_date',
            'day_of_week', 'day_of_week_display',
            'start_time', 'end_time', 'capacity',
            'is_active', 'is_published', 'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at', 'trainer_schedule', 'trainer_name', 'recurrence_mode_display']


class UnifiedClassSerializer(GymClassSerializer):
    source = serializers.SerializerMethodField()

    class Meta(GymClassSerializer.Meta):
        fields = GymClassSerializer.Meta.fields + ('source',)

    def get_source(self, obj):
        return 'admin' if obj.trainer_profile_id else 'trainer'


class UnifiedScheduleSerializer(GymScheduleSerializer):
    trainer_class_name = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    class Meta(GymScheduleSerializer.Meta):
        fields = GymScheduleSerializer.Meta.fields + ('trainer_class_name', 'source')

    def get_trainer_class_name(self, obj):
        if obj.gym_class and obj.gym_class.trainer_class_id:
            return obj.gym_class.trainer_class.name
        return obj.title

    def get_source(self, obj):
        return 'weekly' if obj.recurrence_mode == 'weekly' else 'one_off'