from rest_framework import serializers
from .models import Member, MemberPackage, Payment, Attendance

# ----------------------------
# MemberPackage
# ----------------------------
class MemberPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = MemberPackage
        fields = ('id', 'name', 'package_type', 'duration_in_days', 'price')


# ----------------------------
# Member
# ----------------------------
class MemberSerializer(serializers.ModelSerializer):
    member_package = MemberPackageSerializer(read_only=True)
    remaining_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = Member
        fields = (
            'id',
            'full_name',
            'phone_number',
            'membership_type',
            'member_package',
            'start_date',
            'end_date',
            'remaining_days',
            'card_id',
            'fingerprint_id',
            'is_active',
            'created_at',
        )


# ----------------------------
# Payment
# ----------------------------
class PaymentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)

    class Meta:
        model = Payment
        fields = (
            'id',
            'member',
            'member_name',  # useful for dashboard display
            'payment_type',
            'amount',
            'payment_date',
            'note',
        )


# ----------------------------
# Attendance
# ----------------------------
class AttendanceSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)

    class Meta:
        model = Attendance
        fields = (
            'id',
            'member',
            'member_name',  # useful for dashboard
            'check_in_time',
            'check_out_time',
            'entry_method',
            'device_id',
        )