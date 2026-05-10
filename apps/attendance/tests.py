from datetime import datetime, timezone as dt_timezone

from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory
from unittest.mock import MagicMock, patch

from apps.attendance.models import AccessDevice, AttendanceIngestEvent, DeviceUser
from apps.attendance.services import realtime as realtime_service
from apps.attendance.services.ingestion import ADMSIngestionService
from apps.attendance.views import AccessCheckAPIView, IclockCdataAPIView, _build_attlog_sync_command
from apps.membership.models import Attendance, Member
from apps.tenancy.models import Domain, Tenant


class ADMSIngestionServiceTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		with schema_context("public"):
			cls.public_tenant, _ = Tenant.objects.get_or_create(
				schema_name="public",
				defaults={
					"name": "Public",
					"slug": "public",
					"code": "PUBATT01",
					"owner_email": "root@attendance.test",
					"billing_email": "root@attendance.test",
					"status": "active",
					"is_trial": False,
				},
			)
			Domain.objects.get_or_create(
				domain="testserver",
				tenant=cls.public_tenant,
				defaults={"is_primary": True},
			)

			cls.tenant, _ = Tenant.objects.get_or_create(
				schema_name="attendance_test",
				defaults={
					"name": "Attendance Test Tenant",
					"slug": "attendance-test-tenant",
					"code": "ATTTEN01",
					"owner_email": "admin@attendance.test",
					"billing_email": "admin@attendance.test",
					"status": "active",
					"is_trial": False,
				},
			)
			Domain.objects.get_or_create(
				domain="attendance.testserver",
				tenant=cls.tenant,
				defaults={"is_primary": True},
			)

	def test_parse_body_extracts_attlog_and_userinfo(self):
		body = "\n".join(
			[
				"TABLE=ATTLOG",
				"1001\t2026-01-11 10:12:30\t0\t1\t0\t0",
				"TABLE=USERINFO",
				"PIN=1001\tName=John",
			]
		)

		events = ADMSIngestionService._parse_body(body)
		self.assertEqual(len(events), 2)
		self.assertEqual(events[0].event_type, "ATTLOG")
		self.assertEqual(events[0].device_uid, "1001")
		self.assertEqual(events[1].event_type, "USERINFO")
		self.assertEqual(events[1].device_uid, "1001")

	def test_process_is_idempotent_for_duplicate_lines(self):
		payload = "\n".join(
			[
				"TABLE=ATTLOG",
				"2002\t2026-01-11 11:22:33\t0\t1\t0\t0",
			]
		)

		with schema_context(self.tenant.schema_name):
			device = AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-001",
			)

			first = ADMSIngestionService.process(device, payload)
			second = ADMSIngestionService.process(device, payload)

			self.assertEqual(first["handled"], 1)
			self.assertEqual(first["skipped"], 0)
			self.assertEqual(second["handled"], 0)
			self.assertEqual(second["skipped"], 1)
			self.assertEqual(AttendanceIngestEvent.objects.count(), 1)
			self.assertEqual(DeviceUser.objects.filter(access_device=device, device_uid="2002").count(), 1)

	def test_build_attlog_sync_command_uses_latest_ingested_event_time(self):
		with schema_context(self.tenant.schema_name):
			device = AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-RECENT",
				timezone="Asia/Dhaka",
			)
			AttendanceIngestEvent.objects.create(
				access_device=device,
				event_hash="hash-attlog-recent",
				event_type="ATTLOG",
				device_uid="3001",
				event_time=datetime(2026, 5, 10, 11, 47, 45, tzinfo=dt_timezone.utc),
				raw_line="3001\t2026-05-10 17:47:45",
			)

			command, start_time = _build_attlog_sync_command(device)

			self.assertEqual(command, "DATA QUERY ATTLOG StartTime=2026-05-10 17:46:45")
			self.assertEqual(start_time, "2026-05-10 17:46:45")


@override_settings(GYM_DEVICE_API_KEY="test-device-key")
class AttendanceApiFlowTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		with schema_context("public"):
			cls.public_tenant, _ = Tenant.objects.get_or_create(
				schema_name="public",
				defaults={
					"name": "Public",
					"slug": "public",
					"code": "PUBATT02",
					"owner_email": "root@attendance.test",
					"billing_email": "root@attendance.test",
					"status": "active",
					"is_trial": False,
				},
			)
			Domain.objects.get_or_create(
				domain="testserver",
				tenant=cls.public_tenant,
				defaults={"is_primary": True},
			)

			cls.tenant, _ = Tenant.objects.get_or_create(
				schema_name="attendance_api_test",
				defaults={
					"name": "Attendance API Tenant",
					"slug": "attendance-api-tenant",
					"code": "ATTTEN02",
					"owner_email": "admin-api@attendance.test",
					"billing_email": "admin-api@attendance.test",
					"status": "active",
					"is_trial": False,
				},
			)
			Domain.objects.get_or_create(
				domain="attendance-api.testserver",
				tenant=cls.tenant,
				defaults={"is_primary": True},
			)

	def setUp(self):
		self.factory = APIRequestFactory()

	def test_access_check_checks_in_then_checks_out(self):
		with schema_context(self.tenant.schema_name):
			AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-API",
				is_active=True,
			)
			member = Member.objects.create(
				full_name="Demo Member",
				phone_number="01700000001",
				card_id="CARD-101",
				start_date=timezone.now().date(),
			)

			view = AccessCheckAPIView.as_view()
			request_in = self.factory.post(
				"/api/v1/attendance/access/check/",
				{"card_id": "CARD-101", "device_sn": "ZKT-F18-API"},
				format="json",
				HTTP_X_API_KEY="test-device-key",
			)
			response_in = view(request_in)
			self.assertEqual(response_in.status_code, status.HTTP_200_OK)
			self.assertEqual(response_in.data["action"], "checked_in")

			request_out = self.factory.post(
				"/api/v1/attendance/access/check/",
				{"card_id": "CARD-101", "device_sn": "ZKT-F18-API"},
				format="json",
				HTTP_X_API_KEY="test-device-key",
			)
			response_out = view(request_out)
			self.assertEqual(response_out.status_code, status.HTTP_200_OK)
			self.assertEqual(response_out.data["action"], "checked_out")

			attendance = Attendance.objects.get(member=member)
			self.assertIsNotNone(attendance.check_out_time)

	def test_iclock_post_returns_handled_then_skipped_for_duplicate(self):
		payload = "\n".join(
			[
				"TABLE=ATTLOG",
				"3001\t2026-01-11 11:22:33\t0\t1\t0\t0",
			]
		)

		with schema_context(self.tenant.schema_name):
			AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-API",
				is_active=True,
			)

			view = IclockCdataAPIView.as_view()
			request_first = self.factory.post(
				"/api/v1/attendance/iclock/cdata/?SN=ZKT-F18-API",
				payload,
				content_type="text/plain",
			)
			response_first = view(request_first)
			first_text = response_first.rendered_content.decode("utf-8")
			self.assertEqual(response_first.status_code, status.HTTP_200_OK)
			self.assertIn("handled=1", first_text)
			self.assertIn("skipped=0", first_text)

			request_second = self.factory.post(
				"/api/v1/attendance/iclock/cdata/?SN=ZKT-F18-API",
				payload,
				content_type="text/plain",
			)
			response_second = view(request_second)
			second_text = response_second.rendered_content.decode("utf-8")
			self.assertEqual(response_second.status_code, status.HTTP_200_OK)
			self.assertIn("handled=0", second_text)
			self.assertIn("skipped=1", second_text)


class AttendanceRealtimePublishTests(TestCase):
	@patch("apps.attendance.services.realtime.async_to_sync")
	@patch("apps.attendance.services.realtime.get_channel_layer")
	def test_publish_attendance_event_sends_group_message(self, mock_get_layer, mock_async_to_sync):
		layer = MagicMock()
		mock_get_layer.return_value = layer
		sync_callable = MagicMock()
		mock_async_to_sync.return_value = sync_callable

		realtime_service.publish_attendance_event("attendance-updated", {"member_id": 10})

		mock_async_to_sync.assert_called_once_with(layer.group_send)
		sync_callable.assert_called_once()
		sent_group, sent_payload = sync_callable.call_args[0]
		self.assertEqual(sent_group, "attendance_events")
		self.assertEqual(sent_payload["type"], "attendance.event")
		self.assertEqual(sent_payload["event"], "attendance-updated")
		self.assertEqual(sent_payload["payload"], {"member_id": 10})

	@patch("apps.attendance.services.realtime.async_to_sync")
	@patch("apps.attendance.services.realtime.get_channel_layer")
	def test_publish_attendance_event_noop_when_channel_layer_missing(self, mock_get_layer, mock_async_to_sync):
		mock_get_layer.return_value = None

		realtime_service.publish_attendance_event("attendance-updated", {"member_id": 11})

		mock_async_to_sync.assert_not_called()
