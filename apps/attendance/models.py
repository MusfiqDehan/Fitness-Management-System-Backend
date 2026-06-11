from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.membership.models import Member


class AccessDevice(models.Model):
	MODE_ADMS = "adms"
	MODE_TCP_RELAY = "tcp_relay"
	MODE_CHOICES = (
		(MODE_ADMS, "ADMS"),
		(MODE_TCP_RELAY, "TCP Relay"),
	)

	STATUS_ONLINE = "online"
	STATUS_OFFLINE = "offline"
	STATUS_ERROR = "error"
	STATUS_UNKNOWN = "unknown"
	STATUS_CHOICES = (
		(STATUS_ONLINE, "Online"),
		(STATUS_OFFLINE, "Offline"),
		(STATUS_ERROR, "Error"),
		(STATUS_UNKNOWN, "Unknown"),
	)

	name = models.CharField(max_length=120)
	device_sn = models.CharField(max_length=100, unique=True)
	mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_ADMS)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UNKNOWN)
	timezone = models.CharField(max_length=64, default="Asia/Dhaka")
	last_seen_at = models.DateTimeField(null=True, blank=True)
	is_active = models.BooleanField(default=True)
	meta_json = models.JSONField(default=dict, blank=True)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="attendance_access_device_created",
	)
	updated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="attendance_access_device_updated",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-updated_at"]
		indexes = [
			models.Index(fields=["is_active", "updated_at"], name="idx_accessdev_active_updated"),
		]

	def __str__(self):
		return f"{self.name} ({self.device_sn})"


class AccessDeviceEndpoint(models.Model):
	access_device = models.OneToOneField(
		AccessDevice,
		on_delete=models.CASCADE,
		related_name="endpoint",
	)
	base_url = models.CharField(max_length=255, blank=True, default="")
	path_prefix = models.CharField(max_length=120, blank=True, default="/iclock")
	relay_host = models.CharField(max_length=120, blank=True, default="")
	relay_port = models.PositiveIntegerField(default=4370)
	api_key_ref = models.CharField(max_length=120, blank=True, default="")
	poll_interval_sec = models.PositiveIntegerField(default=30)
	heartbeat_interval_sec = models.PositiveIntegerField(default=30)
	meta_json = models.JSONField(default=dict, blank=True)

	def __str__(self):
		return f"Endpoint[{self.access_device_id}]"


class DeviceCredential(models.Model):
	access_device = models.ForeignKey(
		AccessDevice,
		on_delete=models.CASCADE,
		related_name="credentials",
	)
	key = models.CharField(max_length=80)
	# Stores non-plaintext value (hash or encrypted blob depending on runtime).
	secret_ciphertext = models.TextField()
	is_active = models.BooleanField(default=True)
	rotated_at = models.DateTimeField(auto_now=True)

	class Meta:
		unique_together = [("access_device", "key")]

	def __str__(self):
		return f"Credential[{self.access_device_id}:{self.key}]"


class DeviceUser(models.Model):
	STATUS_UNLINKED = "unlinked"
	STATUS_LINKED = "linked"
	STATUS_DELETED = "deleted"
	STATUS_CHOICES = (
		(STATUS_UNLINKED, "Unlinked"),
		(STATUS_LINKED, "Linked"),
		(STATUS_DELETED, "Deleted"),
	)

	access_device = models.ForeignKey(
		AccessDevice,
		on_delete=models.CASCADE,
		related_name="device_users",
	)
	member = models.ForeignKey(
		Member,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="attendance_device_users",
	)
	device_uid = models.CharField(max_length=64)
	name = models.CharField(max_length=120, null=True, blank=True)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UNLINKED)
	last_seen_at = models.DateTimeField(auto_now=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = [("access_device", "device_uid")]
		indexes = [
			models.Index(fields=["device_uid"], name="att_du_device_uid_idx"),
			models.Index(fields=["access_device", "status"], name="idx_deviceuser_dev_status"),
		]

	def __str__(self):
		return f"{self.device_uid}@{self.access_device_id}"


class AttendanceIngestEvent(models.Model):
	"""Idempotency ledger for device ingestion events."""

	access_device = models.ForeignKey(
		AccessDevice,
		on_delete=models.CASCADE,
		related_name="ingest_events",
	)
	event_hash = models.CharField(max_length=64, unique=True)
	event_type = models.CharField(max_length=32)
	device_uid = models.CharField(max_length=64, blank=True, default="")
	event_time = models.DateTimeField(null=True, blank=True)
	raw_line = models.TextField(blank=True, default="")
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]
		indexes = [
			models.Index(
				fields=["access_device", "event_type", "event_time"],
				name="idx_ingest_dev_type_time",
			),
		]

	def __str__(self):
		return f"{self.event_type}:{self.event_hash[:12]}"
