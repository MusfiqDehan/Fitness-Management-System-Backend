from django.contrib import admin
from .models import (
	AccessDevice,
	AccessDeviceEndpoint,
	AttendanceIngestEvent,
	DeviceCredential,
	DeviceUser,
	FingerprintEnrollmentSession,
)


@admin.register(AccessDevice)
class AccessDeviceAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"name",
		"device_sn",
		"device_profile",
		"device_model",
		"mode",
		"status",
		"is_active",
		"last_seen_at",
	)
	list_filter = ("mode", "status", "is_active")
	search_fields = ("name", "device_sn")


@admin.register(AccessDeviceEndpoint)
class AccessDeviceEndpointAdmin(admin.ModelAdmin):
	list_display = ("id", "access_device", "base_url", "relay_host", "relay_port")
	search_fields = ("access_device__name", "access_device__device_sn", "base_url", "relay_host")


@admin.register(DeviceCredential)
class DeviceCredentialAdmin(admin.ModelAdmin):
	list_display = ("id", "access_device", "key", "is_active", "rotated_at")
	list_filter = ("is_active",)
	search_fields = ("access_device__name", "access_device__device_sn", "key")


@admin.register(DeviceUser)
class DeviceUserAdmin(admin.ModelAdmin):
	list_display = ("id", "access_device", "device_uid", "member", "status", "last_seen_at")
	list_filter = ("status",)
	search_fields = ("device_uid", "name", "member__full_name", "access_device__device_sn")


@admin.register(AttendanceIngestEvent)
class AttendanceIngestEventAdmin(admin.ModelAdmin):
	list_display = ("id", "access_device", "event_type", "device_uid", "event_time", "created_at")
	search_fields = ("event_hash", "device_uid", "event_type", "access_device__device_sn")
	list_filter = ("event_type",)


@admin.register(FingerprintEnrollmentSession)
class FingerprintEnrollmentSessionAdmin(admin.ModelAdmin):
	list_display = ("id", "access_device", "member", "device_uid", "status", "expires_at", "created_at")
	list_filter = ("status",)
	search_fields = ("device_uid", "member__full_name", "access_device__device_sn")
