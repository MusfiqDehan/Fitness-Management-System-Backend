from rest_framework import serializers
from django.utils import timezone
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context

from apps.membership.models import Attendance, Member
from apps.tenancy.models import AccessDeviceRoute

from apps.attendance.device_profiles import is_valid_device_profile
from .models import (
	AccessDevice,
	AccessDeviceEndpoint,
	DeviceCredential,
	DeviceUser,
	FingerprintEnrollmentSession,
)


class AccessDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessDevice
        fields = (
            "id",
            "name",
            "device_sn",
            "device_profile",
            "device_model",
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

    def validate_device_profile(self, value):
        normalized = (value or "").strip()
        if not is_valid_device_profile(normalized):
            raise serializers.ValidationError("Unknown device profile.")
        return normalized

    def validate_device_model(self, value):
        return (value or "").strip()

    def validate(self, attrs):
        profile = attrs.get("device_profile")
        if profile is None and self.instance is not None:
            profile = self.instance.device_profile
        model = attrs.get("device_model")
        if model is None and self.instance is not None:
            model = self.instance.device_model
        model = (model or "").strip()
        if profile == "zkteco" and not model:
            raise serializers.ValidationError(
                {"device_model": "Model name is required for ZKTeco devices."}
            )
        if "device_model" in attrs:
            attrs["device_model"] = model
        return attrs


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


def credential_types_for(device_user: DeviceUser) -> list[str]:
    """Return credential labels for a device PIN slot: card, fingerprint, or both."""
    types: list[str] = []
    card = (getattr(device_user, "card_number", None) or "").strip()
    if card:
        types.append("card")

    member = getattr(device_user, "member", None)
    fingerprint_match = bool(
        member is not None and (member.fingerprint_id or "") == device_user.device_uid
    )
    if not card or fingerprint_match:
        types.append("fingerprint")
    return types


def linked_device_users_for(member: Member) -> list[DeviceUser]:
    """Return linked DeviceUsers for a member, preferring a Prefetch cache when present."""
    cache = getattr(member, "_prefetched_objects_cache", None)
    if cache is not None and "attendance_device_users" in cache:
        return list(cache["attendance_device_users"])
    return list(
        member.attendance_device_users.filter(status=DeviceUser.STATUS_LINKED).order_by(
            "device_uid", "id"
        )
    )


def member_device_uids(member: Member) -> list[str]:
    """Distinct device UIDs from linked DeviceUsers (stable order)."""
    uids: list[str] = []
    seen: set[str] = set()
    for device_user in linked_device_users_for(member):
        uid = (device_user.device_uid or "").strip()
        if uid and uid not in seen:
            seen.add(uid)
            uids.append(uid)
    return uids


def member_credential_linked(member: Member) -> str:
    """Aggregate linked DeviceUser credential types into none|card|fingerprint|both."""
    types: set[str] = set()
    for device_user in linked_device_users_for(member):
        types.update(credential_types_for(device_user))
    has_card = "card" in types
    has_fingerprint = "fingerprint" in types
    if has_card and has_fingerprint:
        return "both"
    if has_card:
        return "card"
    if has_fingerprint:
        return "fingerprint"
    return "none"


class DeviceUserSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    access_device_name = serializers.CharField(source="access_device.name", read_only=True)
    credential_types = serializers.SerializerMethodField()

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
            "card_number",
            "credential_types",
            "status",
            "last_seen_at",
            "created_at",
        )
        read_only_fields = ("last_seen_at", "created_at", "credential_types")

    def get_credential_types(self, obj: DeviceUser) -> list[str]:
        return credential_types_for(obj)


class CardProvisionSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    access_device_id = serializers.IntegerField()

    def validate(self, attrs):
        member = Member.objects.filter(id=attrs["member_id"]).first()
        if not member:
            raise serializers.ValidationError({"member_id": "Member not found."})
        device = AccessDevice.objects.filter(id=attrs["access_device_id"], is_active=True).first()
        if not device:
            raise serializers.ValidationError({"access_device_id": "Access device not found or inactive."})
        if not (member.card_id or "").strip():
            raise serializers.ValidationError({"member_id": "Member has no card_id set."})
        attrs["member"] = member
        attrs["device"] = device
        return attrs


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

        device_user = attrs["device_user"]
        member = attrs["member"]
        existing = (
            DeviceUser.objects.filter(
                access_device=device_user.access_device,
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )
            .exclude(id=device_user.id)
            .first()
        )
        if existing:
            raise serializers.ValidationError(
                {
                    "member_id": (
                        f"{member.full_name} is already linked to PIN {existing.device_uid} "
                        f"on {device_user.access_device.name}. Unlink that PIN first."
                    )
                }
            )
        return attrs


class FingerprintUnlinkSerializer(serializers.Serializer):
    device_user_id = serializers.IntegerField()

    def validate_device_user_id(self, value):
        if not DeviceUser.objects.filter(id=value).exists():
            raise serializers.ValidationError("Device user not found.")
        return value


class FingerprintDeleteSerializer(serializers.Serializer):
    device_user_id = serializers.IntegerField()

    def validate(self, attrs):
        device_user = DeviceUser.objects.select_related("access_device", "member").filter(
            id=attrs["device_user_id"]
        ).first()
        if not device_user:
            raise serializers.ValidationError({"device_user_id": "Device user not found."})
        if device_user.status == DeviceUser.STATUS_DELETED:
            raise serializers.ValidationError({"device_user_id": "Device user already deleted."})
        device = device_user.access_device
        if not device or not device.is_active:
            raise serializers.ValidationError({"device_user_id": "Access device is inactive."})
        if device.mode not in (AccessDevice.MODE_ADMS, AccessDevice.MODE_TCP_RELAY):
            raise serializers.ValidationError(
                {"device_user_id": "Delete requires ADMS or TCP Relay mode."}
            )
        attrs["device_user"] = device_user
        attrs["device"] = device
        return attrs


class FingerprintEnrollmentStartSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    access_device_id = serializers.IntegerField()
    fingerprint_slot = serializers.IntegerField(required=False, min_value=0, max_value=9, default=0)

    def validate(self, attrs):
        member = Member.objects.filter(id=attrs["member_id"]).first()
        if not member:
            raise serializers.ValidationError({"member_id": "Member not found."})
        device = AccessDevice.objects.filter(id=attrs["access_device_id"], is_active=True).first()
        if not device:
            raise serializers.ValidationError({"access_device_id": "Access device not found or inactive."})
        attrs["member"] = member
        attrs["device"] = device
        return attrs


class FingerprintEnrollmentSessionSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    access_device_name = serializers.CharField(source="access_device.name", read_only=True)
    device_profile = serializers.CharField(source="access_device.device_profile", read_only=True)

    class Meta:
        model = FingerprintEnrollmentSession
        fields = (
            "id",
            "access_device",
            "access_device_name",
            "device_profile",
            "member",
            "member_name",
            "device_uid",
            "fingerprint_slot",
            "status",
            "failure_reason",
            "expires_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


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
            "device_uid",
        )
