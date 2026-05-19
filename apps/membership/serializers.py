from rest_framework import serializers
from .models import Member, MemberPackage, Payment, Attendance, GymClass, GymSchedule
from datetime import date


# ----------------------------
# MemberPackage
# ----------------------------
class MemberPackageSerializer(serializers.ModelSerializer):
    features = serializers.JSONField(required=False, default=list)
    add_ons = serializers.JSONField(required=False, default=list)

    class Meta:
        model = MemberPackage
        fields = (
            'id', 'name', 'package_type', 'duration_in_days', 'price',
            'description', 'features', 'add_ons', 'display_order',
            'is_active', 'is_highlighted', 'is_published', 'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at']


class MemberPackagePublicSerializer(serializers.ModelSerializer):
    """Public serializer for landing page - only published and active packages."""
    features = serializers.JSONField(required=False, default=list)
    add_ons = serializers.JSONField(required=False, default=list)

    class Meta:
        model = MemberPackage
        fields = (
            'id', 'name', 'package_type', 'duration_in_days', 'price',
            'description', 'features', 'add_ons', 'display_order', 'is_highlighted',
        )


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

    class Meta:
        model = Member
        fields = (
            'id', 'full_name', 'phone_number', 'email', 'gender',
            'date_of_birth', 'address', 'membership_type',
            'member_package', 'member_package_id',
            'start_date', 'end_date', 'remaining_days',
            'card_id', 'fingerprint_id',
            'emergency_contact_name', 'emergency_contact_phone', 'notes',
            'payment_method', 'payment_status', 'photo',
            'is_active', 'is_published', 'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at', 'remaining_days']

    def validate(self, attrs):
        membership_type = attrs.get('membership_type', getattr(self.instance, 'membership_type', None))
        member_package = attrs.get('member_package', getattr(self.instance, 'member_package', None))

        if membership_type == 'package' and member_package is None:
            raise serializers.ValidationError({'member_package_id': 'This field is required for package memberships.'})

        if membership_type == 'monthly':
            attrs['member_package'] = None

        return attrs


class MemberPublicSerializer(serializers.ModelSerializer):
    """For public registration from landing page."""
    member_package_id = serializers.PrimaryKeyRelatedField(
        queryset=MemberPackage.objects.filter(is_active=True, is_published=True),
        source='member_package',
        write_only=True,
        required=True,
    )

    class Meta:
        model = Member
        fields = (
            'full_name', 'phone_number', 'email', 'gender',
            'address', 'membership_type', 'member_package_id',
            'emergency_contact_name', 'emergency_contact_phone', 'notes',
        )

    def validate_membership_type(self, value):
        if value != 'package':
            raise serializers.ValidationError('Only package membership is allowed for self-registration.')
        return value


# ----------------------------
# Payment
# ----------------------------
class PaymentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_phone = serializers.CharField(source='member.phone_number', read_only=True)
    member_email = serializers.CharField(source='member.email', read_only=True)
    package_name = serializers.CharField(source='member.member_package.name', read_only=True)
    payment_type_display = serializers.CharField(source='get_payment_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)

    class Meta:
        model = Payment
        fields = (
            'id', 'member', 'member_name', 'member_phone', 'member_email', 'package_name',
            'payment_type', 'payment_type_display',
            'amount',
            'payment_method', 'payment_method_display',
            'payment_status', 'payment_status_display',
            'payment_date', 'invoice_no', 'note', 'is_paid',
            'is_active', 'is_published', 'created_at',
        )
        read_only_fields = [
            'created_at', 'member_name', 'member_phone', 'member_email', 'package_name',
            'payment_type_display', 'payment_method_display', 'payment_status_display',
        ]


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

    class Meta:
        model = GymClass
        fields = (
            'id', 'name', 'class_type', 'class_type_display',
            'level', 'level_display', 'instructor',
            'duration_minutes', 'capacity', 'description',
            'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at']


# ----------------------------
# GymSchedule
# ----------------------------
class GymScheduleSerializer(serializers.ModelSerializer):
    day_of_week_display = serializers.CharField(source='get_day_of_week_display', read_only=True)

    class Meta:
        model = GymSchedule
        fields = (
            'id', 'gym_class', 'title', 'class_type', 'instructor',
            'day_of_week', 'day_of_week_display',
            'start_time', 'end_time', 'capacity',
            'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ['created_at', 'updated_at']