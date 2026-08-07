from rest_framework import serializers
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from utils.brand_colors import normalize_brand_color
from .models import GymProfile, NotificationPreferences, GymPreferences, ReminderTemplate, Reminder


class GymProfileSerializer(serializers.ModelSerializer):
    logo_url = serializers.CharField(allow_blank=True, required=False)
    website = serializers.URLField(allow_blank=True, required=False)

    def validate_logo_url(self, value):
        normalized = (value or "").strip()
        if not normalized:
            return ""

        # Local storage uploads return relative /media/... paths in dev/prod.
        if normalized.startswith('/media/'):
            return normalized

        validator = URLValidator()
        try:
            validator(normalized)
        except DjangoValidationError as exc:
            raise serializers.ValidationError("Enter a valid URL.") from exc

        return normalized

    def validate_primary_color(self, value):
        return self._validate_brand_color(value)

    def validate_secondary_color(self, value):
        return self._validate_brand_color(value)

    @staticmethod
    def _validate_brand_color(value):
        try:
            return normalize_brand_color(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    class Meta:
        model = GymProfile
        fields = [
            "id", "gym_name", "email", "phone", "website", "address", "timezone",
            "logo_url", "logo_width", "logo_height",
            "primary_color", "secondary_color",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class NotificationPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreferences
        fields = [
            "id",
            "payment_received",
            "new_member_signup",
            "reminder_due",
            "weekly_report",
            "push_notifications",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class GymPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = GymPreferences
        fields = [
            "id",
            "language",
            "currency",
            "date_format",
            "week_start",
            "theme",
            "topbar_show_date",
            "topbar_show_description",
            "payment_auto_delete_credentials_enabled",
            "payment_cleanup_run_at_1",
            "payment_cleanup_run_at_2",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def validate(self, attrs):
        enabled = attrs.get(
            "payment_auto_delete_credentials_enabled",
            getattr(self.instance, "payment_auto_delete_credentials_enabled", False)
            if self.instance
            else False,
        )
        run_at_1 = attrs.get(
            "payment_cleanup_run_at_1",
            getattr(self.instance, "payment_cleanup_run_at_1", None) if self.instance else None,
        )
        run_at_2 = attrs.get(
            "payment_cleanup_run_at_2",
            getattr(self.instance, "payment_cleanup_run_at_2", None) if self.instance else None,
        )
        if enabled:
            if run_at_1 is None or run_at_2 is None:
                raise serializers.ValidationError(
                    {
                        "payment_auto_delete_credentials_enabled": (
                            "Both cleanup run times are required when auto-delete is enabled."
                        )
                    }
                )
            if run_at_1 == run_at_2:
                raise serializers.ValidationError(
                    {
                        "payment_cleanup_run_at_2": (
                            "Cleanup run times must be distinct."
                        )
                    }
                )
        return attrs


class ReminderTemplateSerializer(serializers.ModelSerializer):
    reminder_type_display = serializers.CharField(source="get_reminder_type_display", read_only=True)
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)

    class Meta:
        model = ReminderTemplate
        fields = [
            "id",
            "title",
            "reminder_type",
            "reminder_type_display",
            "channel",
            "channel_display",
            "description",
            "days_before",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "reminder_type_display", "channel_display", "created_at", "updated_at"]


class ReminderSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    member_phone = serializers.CharField(source="member.phone_number", read_only=True)
    member_email = serializers.CharField(source="member.email", read_only=True)
    member_package = serializers.SerializerMethodField()
    reminder_type_display = serializers.CharField(source="get_reminder_type_display", read_only=True)
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Reminder
        fields = [
            "id",
            "member",
            "member_name",
            "member_phone",
            "member_email",
            "member_package",
            "reminder_type",
            "reminder_type_display",
            "channel",
            "channel_display",
            "due_date",
            "amount",
            "status",
            "status_display",
            "sent_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "member_name",
            "member_phone",
            "member_email",
            "member_package",
            "reminder_type_display",
            "channel_display",
            "status_display",
            "sent_at",
            "created_at",
        ]

    def get_member_package(self, obj):
        pkg = getattr(obj.member, "member_package", None)
        return pkg.name if pkg else ""


class ReminderStatsSerializer(serializers.Serializer):
    pending = serializers.IntegerField()
    sent_this_month = serializers.IntegerField()
    overdue_members = serializers.IntegerField()
    overdue_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    active_templates = serializers.IntegerField()
