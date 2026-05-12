from rest_framework import serializers
from .models import GymProfile, NotificationPreferences, GymPreferences, ReminderTemplate, Reminder


class GymProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GymProfile
        fields = ["id", "gym_name", "email", "phone", "website", "address", "timezone", "updated_at"]
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
        fields = ["id", "language", "currency", "date_format", "week_start", "theme", "updated_at"]
        read_only_fields = ["id", "updated_at"]


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
