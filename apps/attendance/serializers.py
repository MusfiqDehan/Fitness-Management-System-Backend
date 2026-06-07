from rest_framework import serializers
from django.utils import timezone
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context

from apps.membership.models import Attendance, Member
from apps.tenancy.models import AccessDeviceRoute

from .models import AccessDevice, AccessDeviceEndpoint, DeviceCredential, DeviceUser


class AccessDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessDevice
        fields = (
            "id",
            "name",
            "device_sn",
            "mode",
            "status",
            "timezone",
            "last_seen_at",
            "is_active",
            "meta_json",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "status",
            "last_seen_at",
            "created_at",
            "updated_at",
        )

    def validate_device_sn(self, value):
        normalized = (value or "").strip()
        if not normalized:
            raise serializers.ValidationError("Device serial number is required.")

        current_schema = connection.schema_name
        if current_schema == get_public_schema_name():
            return normalized

        with schema_context(get_public_schema_name()):
            route = (
                AccessDeviceRoute.objects.select_related("tenant")
                .filter(device_sn=normalized)
                .first()
            )

        if route is None:
            return normalized

        if (
            route.tenant.schema_name == current_schema
            and route.access_device_id == getattr(self.instance, "pk", None)
        ):
            return normalized

        raise serializers.ValidationError("Device serial number is already assigned to another tenant.")


class AccessDeviceEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessDeviceEndpoint
        fields = (
            "id",
            "access_device",
            "base_url",
            "path_prefix",
            "relay_host",
            "relay_port",
            "api_key_ref",
            "poll_interval_sec",
            "heartbeat_interval_sec",
            "meta_json",
        )


class DeviceCredentialRotateSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=80)
    secret = serializers.CharField(max_length=1024, write_only=True)


class DeviceUserSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    access_device_name = serializers.CharField(source="access_device.name", read_only=True)

    class Meta:
        model = DeviceUser
        fields = (
            "id",
            "access_device",
            "access_device_name",
            "member",
            "member_name",
            "device_uid",
            "name",
            "status",
            "last_seen_at",
            "created_at",
        )
        read_only_fields = ("last_seen_at", "created_at")


class FingerprintLinkSerializer(serializers.Serializer):
    device_user_id = serializers.IntegerField()
    member_id = serializers.IntegerField()

    def validate(self, attrs):
        attrs["device_user"] = DeviceUser.objects.filter(id=attrs["device_user_id"]).first()
        if not attrs["device_user"]:
            raise serializers.ValidationError({"device_user_id": "Device user not found."})

        attrs["member"] = Member.objects.filter(id=attrs["member_id"]).first()
        if not attrs["member"]:
            raise serializers.ValidationError({"member_id": "Member not found."})
        return attrs


class FingerprintUnlinkSerializer(serializers.Serializer):
    device_user_id = serializers.IntegerField()

    def validate_device_user_id(self, value):
        if not DeviceUser.objects.filter(id=value).exists():
            raise serializers.ValidationError("Device user not found.")
        return value


class AttendanceLogSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    total_staying_time = serializers.SerializerMethodField()

    def get_total_staying_time(self, obj):
        end_time = obj.check_out_time or timezone.now()
        delta = end_time - obj.check_in_time
        total_seconds = max(int(delta.total_seconds()), 0)

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    class Meta:
        model = Attendance
        fields = (
            "id",
            "member",
            "member_name",
            "check_in_time",
            "check_out_time",
            "total_staying_time",
            "entry_method",
            "device_id",
        )
