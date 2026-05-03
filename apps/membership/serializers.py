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
            'id',
            'full_name',
            'phone_number',
            'membership_type',
            'member_package',
            'member_package_id',
            'start_date',
            'end_date',
            'remaining_days',
            'card_id',
            'fingerprint_id',
            'is_active',
            'created_at',
        )

    def validate(self, attrs):
        membership_type = attrs.get('membership_type', getattr(self.instance, 'membership_type', None))
        member_package = attrs.get('member_package', getattr(self.instance, 'member_package', None))

        if membership_type == 'package' and member_package is None:
            raise serializers.ValidationError({'member_package_id': 'This field is required for package memberships.'})

        if membership_type == 'monthly':
            attrs['member_package'] = None

        return attrs


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