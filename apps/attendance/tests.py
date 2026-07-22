from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import MagicMock, patch

from apps.attendance.models import AccessDevice, AttendanceIngestEvent, DeviceUser
from apps.attendance.serializers import AccessDeviceSerializer
from apps.attendance.services import realtime as realtime_service
from apps.attendance.services.ingestion import ADMSIngestionService
from apps.attendance.views import (
	AccessCheckAPIView,
	AttendanceLogListAPIView,
	IclockCdataAPIView,
	IclockGetRequestAPIView,
	MemberAttendanceLogListAPIView,
	MembersInsideAPIView,
	FingerprintUnlinkedListAPIView,
	_build_attlog_sync_command,
)
from apps.access.models import Role, UserRole
from apps.gym_branch.models import Branch
from apps.identity.models import User
from apps.membership.models import Attendance, Member
from apps.tenancy.models import AccessDeviceRoute, Domain, Feature, Tenant, TenantFeatureFlag


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
			cls.other_tenant, _ = Tenant.objects.get_or_create(
				schema_name="attendance_api_other",
				defaults={
					"name": "Attendance API Other Tenant",
					"slug": "attendance-api-other-tenant",
					"code": "ATTTEN03",
					"owner_email": "other-api@attendance.test",
					"billing_email": "other-api@attendance.test",
					"status": "active",
					"is_trial": False,
				},
			)
			Domain.objects.get_or_create(
				domain="attendance-api-other.testserver",
				tenant=cls.other_tenant,
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

			attendance = Attendance.objects.get(member=member)
			Attendance.objects.filter(id=attendance.id).update(
				check_in_time=timezone.now() - timedelta(seconds=61),
			)

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

	def test_public_iclock_heartbeat_routes_into_matching_tenant_schema(self):
		with schema_context(self.tenant.schema_name):
			device = AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-PUBLIC",
				is_active=True,
			)

		with schema_context("public"):
			route = AccessDeviceRoute.objects.get(device_sn="ZKT-F18-PUBLIC")
			self.assertEqual(route.tenant_id, self.tenant.id)

			view = IclockCdataAPIView.as_view()
			request = self.factory.get("/iclock/cdata/?SN=ZKT-F18-PUBLIC")
			response = view(request)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertIn("OK", response.content.decode("utf-8"))

		with schema_context(self.tenant.schema_name):
			device.refresh_from_db()
			self.assertEqual(device.status, AccessDevice.STATUS_ONLINE)
			self.assertIsNotNone(device.last_seen_at)

	def test_public_iclock_getrequest_dispatches_pending_command(self):
		with schema_context(self.tenant.schema_name):
			device = AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-CMD",
				is_active=True,
				meta_json={
					"pending_commands": [
						{"id": "sync-1", "cmd": "DATA QUERY USERINFO"},
					],
				},
			)

		with schema_context("public"):
			view = IclockGetRequestAPIView.as_view()
			request = self.factory.get("/iclock/getrequest/?SN=ZKT-F18-CMD")
			response = view(request)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.content.decode("utf-8"), "C:sync-1:DATA QUERY USERINFO\n")

		with schema_context(self.tenant.schema_name):
			device.refresh_from_db()
			self.assertEqual(device.meta_json["pending_commands"], [])
			self.assertEqual(device.meta_json["last_command_sent"], "DATA QUERY USERINFO")
			self.assertEqual(device.status, AccessDevice.STATUS_ONLINE)

	def test_device_serial_number_must_be_globally_unique_across_tenants(self):
		with schema_context(self.tenant.schema_name):
			AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-GLOBAL",
				is_active=True,
			)

		with schema_context(self.other_tenant.schema_name):
			serializer = AccessDeviceSerializer(
				data={
					"name": "Side Gate",
					"device_sn": "ZKT-F18-GLOBAL",
					"is_active": True,
				}
			)
			self.assertFalse(serializer.is_valid())
			self.assertEqual(
				serializer.errors["device_sn"][0],
				"Device serial number is already assigned to another tenant.",
			)


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


class AttendanceBranchScopeTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		with schema_context("public"):
			cls.public_tenant = Tenant.objects.create(
				schema_name="public",
				name="Public",
				slug="public",
				code="PUBATTS1",
				owner_email="root@attendance-scope.test",
				billing_email="root@attendance-scope.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain="testserver",
				tenant=cls.public_tenant,
				defaults={"is_primary": True},
			)

			cls.tenant = Tenant.objects.create(
				schema_name="attendance_scope_test",
				name="Attendance Scope Tenant",
				slug="attendance-scope-tenant",
				code="ATTSCOPE1",
				owner_email="admin@attendance-scope.test",
				billing_email="admin@attendance-scope.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.create(domain="attendance-scope.testserver", tenant=cls.tenant, is_primary=True)

		with schema_context(cls.tenant.schema_name):
			cls.branch_manager = User.objects.create_user(
				email="manager@attendance-scope.test",
				password="StrongPass123!",
				tenant=cls.tenant,
				full_name="Branch Manager",
			)
			cls.other_user = User.objects.create_user(
				email="staff@attendance-scope.test",
				password="StrongPass123!",
				tenant=cls.tenant,
				full_name="Staff User",
			)

			cls.branch_a = Branch.objects.create(name="Downtown", manager=cls.branch_manager)
			cls.branch_b = Branch.objects.create(name="Uptown")

			role = Role.objects.create(name="Branch Manager", slug="branch_manager")
			UserRole.objects.create(
				user_id=cls.branch_manager.id,
				user_email=cls.branch_manager.email,
				branch=cls.branch_a,
				role=role,
			)

			cls.member_a = Member.objects.create(
				full_name="Alice Downtown",
				phone_number="01770010001",
				branch=cls.branch_a,
			)
			cls.member_b = Member.objects.create(
				full_name="Bob Uptown",
				phone_number="01770010002",
				branch=cls.branch_b,
			)

			Attendance.objects.create(
				member=cls.member_a,
				entry_method="card",
				device_id="SN-A",
			)
			Attendance.objects.create(
				member=cls.member_b,
				entry_method="fingerprint",
				device_id="SN-B",
			)

			cls.member_user = User.objects.create_user(
				email="member-self@attendance-scope.test",
				password="StrongPass123!",
				tenant=cls.tenant,
				role="student",
			)
			cls.member_self = Member.objects.create(
				full_name="Self Member",
				phone_number="01770010003",
				email=cls.member_user.email,
				branch=cls.branch_a,
			)
			self_log_current = Attendance.objects.create(
				member=cls.member_self,
				entry_method="card",
				device_id="SN-SELF-1",
			)
			self_log_old = Attendance.objects.create(
				member=cls.member_self,
				entry_method="fingerprint",
				device_id="SN-SELF-2",
			)
			Attendance.objects.filter(id=self_log_old.id).update(
				check_in_time=timezone.now() - timedelta(days=40),
			)

	def setUp(self):
		self.factory = APIRequestFactory()

	def test_attendance_logs_only_return_managed_branch_records_for_branch_manager(self):
		request = self.factory.get("/api/v1/attendance/logs/")
		request.user = self.branch_manager

		with schema_context(self.tenant.schema_name):
			view = AttendanceLogListAPIView()
			view.request = request
			view.args = ()
			view.kwargs = {}

			queryset = view.get_queryset()
			self.assertEqual(list(queryset.values_list("member_id", flat=True)), [self.member_a.id])

	def test_members_inside_only_return_managed_branch_records_for_branch_manager(self):
		request = self.factory.get("/api/v1/attendance/access/members-inside/")
		request.user = self.branch_manager

		with schema_context(self.tenant.schema_name):
			response = MembersInsideAPIView().get(request)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data["total_inside"], 1)
		self.assertEqual(response.data["members"][0]["member_name"], "Alice Downtown")

	def test_attendance_logs_default_to_today_when_no_filters(self):
		request = self.factory.get("/api/v1/attendance/logs/")
		request.user = self.branch_manager

		with schema_context(self.tenant.schema_name):
			stale_log = Attendance.objects.create(
				member=self.member_a,
				entry_method="card",
				device_id="SN-OLD",
			)
			Attendance.objects.filter(id=stale_log.id).update(
				check_in_time=timezone.now() - timedelta(days=1),
			)

			view = AttendanceLogListAPIView()
			view.request = request
			view.args = ()
			view.kwargs = {}

			queryset = view.get_queryset()
			self.assertNotIn(stale_log.id, list(queryset.values_list("id", flat=True)))

	def test_member_attendance_logs_default_to_current_month(self):
		request = self.factory.get("/api/v1/attendance/logs/my/")
		request.user = self.member_user

		with schema_context(self.tenant.schema_name):
			view = MemberAttendanceLogListAPIView()
			view.request = request
			view.args = ()
			view.kwargs = {}

			queryset = view.get_queryset()
			self.assertEqual(list(queryset.values_list("member_id", flat=True)), [self.member_self.id])


class FingerprintUnlinkedListPaginationTests(TestCase):
	SCHEMA_NAME = "attendance_fp_pagination_test"

	@classmethod
	def setUpTestData(cls):
		with schema_context("public"):
			cls.public_tenant, _ = Tenant.objects.get_or_create(
				schema_name="public",
				defaults={
					"name": "Public",
					"slug": "public",
					"code": "PUBFP001",
					"owner_email": "root@fp-pagination.test",
					"billing_email": "root@fp-pagination.test",
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
				schema_name=cls.SCHEMA_NAME,
				defaults={
					"name": "Fingerprint Pagination Tenant",
					"slug": "fp-pagination-tenant",
					"code": "FPPAG001",
					"owner_email": "admin@fp-pagination.test",
					"billing_email": "admin@fp-pagination.test",
					"status": "active",
					"is_trial": False,
				},
			)
			Domain.objects.get_or_create(
				domain="fp-pagination.testserver",
				tenant=cls.tenant,
				defaults={"is_primary": True},
			)
			feature, _ = Feature.objects.get_or_create(
				key="attendance.fingerprints",
				defaults={"name": "Fingerprints", "sort_order": 1},
			)
			TenantFeatureFlag.objects.update_or_create(
				tenant=cls.tenant,
				feature=feature,
				defaults={
					"is_enabled": True,
					"source": TenantFeatureFlag.SOURCE_OVERRIDE,
				},
			)

		with schema_context(cls.tenant.schema_name):
			cls.admin = User.objects.create_user(
				email="admin@fp-pagination.test",
				password="StrongPass123!",
				tenant=cls.tenant,
				is_superuser=True,
				is_staff=True,
			)
			cls.device_a = AccessDevice.objects.create(name="Front Gate", device_sn="FP-PAG-A")
			cls.device_b = AccessDevice.objects.create(name="Side Gate", device_sn="FP-PAG-B")
			for index in range(12):
				DeviceUser.objects.create(
					access_device=cls.device_a if index % 2 == 0 else cls.device_b,
					device_uid=f"UID-{index:03d}",
					name=f"User {index}",
					status=DeviceUser.STATUS_UNLINKED,
				)
			DeviceUser.objects.create(
				access_device=cls.device_a,
				device_uid="LINKED-999",
				name="Linked User",
				status=DeviceUser.STATUS_LINKED,
			)

	def setUp(self):
		self.factory = APIRequestFactory()

	def _get_unlinked(self, query_string=""):
		request = self.factory.get(f"/api/v1/attendance/fingerprints/unlinked/{query_string}")
		force_authenticate(request, user=self.admin)

		with schema_context(self.tenant.schema_name):
			response = FingerprintUnlinkedListAPIView.as_view()(request)

		return response

	def test_paginated_response_shape_and_page_size(self):
		response = self._get_unlinked("?page=2&page_size=5")

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		# 12 unlinked + 1 linked (deleted excluded)
		self.assertEqual(response.data["count"], 13)
		self.assertEqual(response.data["page"], 2)
		self.assertEqual(response.data["page_size"], 5)
		self.assertEqual(response.data["total_pages"], 3)
		self.assertEqual(len(response.data["results"]), 5)

	def test_search_filters_by_device_uid_name_or_device(self):
		response = self._get_unlinked("?search=Side+Gate")

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data["count"], 6)
		self.assertTrue(all("Side Gate" in row["access_device_name"] for row in response.data["results"]))

		uid_response = self._get_unlinked("?search=UID-001")
		self.assertEqual(uid_response.status_code, status.HTTP_200_OK)
		self.assertEqual(uid_response.data["count"], 1)
		self.assertEqual(uid_response.data["results"][0]["device_uid"], "UID-001")

	def test_list_includes_linked_and_supports_unlinked_filter(self):
		response = self._get_unlinked()

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data["count"], 13)
		self.assertIn("LINKED-999", [row["device_uid"] for row in response.data["results"]])

		unlinked_only = self._get_unlinked("?status=unlinked")
		self.assertEqual(unlinked_only.status_code, status.HTTP_200_OK)
		self.assertEqual(unlinked_only.data["count"], 12)
		self.assertTrue(
			all(row["status"] == DeviceUser.STATUS_UNLINKED for row in unlinked_only.data["results"])
		)
		self.assertNotIn("LINKED-999", [row["device_uid"] for row in unlinked_only.data["results"]])

		filtered = self._get_unlinked(f"?access_device_id={self.device_a.id}")
		self.assertEqual(filtered.status_code, status.HTTP_200_OK)
		# 6 unlinked on device_a + 1 linked
		self.assertEqual(filtered.data["count"], 7)
		self.assertTrue(all(row["access_device_name"] == "Front Gate" for row in filtered.data["results"]))


class RemoteFingerprintEnrollmentTests(TestCase):
	SCHEMA_NAME = "remote_enroll_test"

	@classmethod
	def setUpTestData(cls):
		with schema_context("public"):
			cls.public_tenant, _ = Tenant.objects.get_or_create(
				schema_name="public",
				defaults={
					"name": "Public",
					"slug": "public",
					"code": "PUBENR01",
					"owner_email": "root@remote-enroll.test",
					"billing_email": "root@remote-enroll.test",
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
				schema_name=cls.SCHEMA_NAME,
				defaults={
					"name": "Remote Enroll Tenant",
					"slug": "remote-enroll-tenant",
					"code": "REMENR01",
					"owner_email": "admin@remote-enroll.test",
					"billing_email": "admin@remote-enroll.test",
					"status": "active",
					"is_trial": False,
				},
			)
			Domain.objects.get_or_create(
				domain="remote-enroll.testserver",
				tenant=cls.tenant,
				defaults={"is_primary": True},
			)
			for key in ("attendance.fingerprints", "attendance.devices"):
				feature, _ = Feature.objects.get_or_create(key=key, defaults={"name": key, "sort_order": 1})
				TenantFeatureFlag.objects.update_or_create(
					tenant=cls.tenant,
					feature=feature,
					defaults={"is_enabled": True, "source": TenantFeatureFlag.SOURCE_OVERRIDE},
				)

		with schema_context(cls.tenant.schema_name):
			cls.admin = User.objects.create_user(
				email="admin@remote-enroll.test",
				password="StrongPass123!",
				tenant=cls.tenant,
				is_superuser=True,
				is_staff=True,
			)
			cls.device = AccessDevice.objects.create(
				name="Front Gate",
				device_sn="ZKT-F18-ENR",
				device_profile="zkteco",
				device_model="F18",
				mode=AccessDevice.MODE_ADMS,
			)
			cls.member = Member.objects.create(
				full_name="Jane Member",
				phone_number="01700000001",
				is_active=True,
			)

	def setUp(self):
		self.factory = APIRequestFactory()

	def test_device_profiles_list(self):
		from apps.attendance.views import BiometricDeviceProfileListAPIView

		request = self.factory.get("/api/v1/attendance/device-profiles/")
		force_authenticate(request, user=self.admin)
		with schema_context(self.tenant.schema_name):
			response = BiometricDeviceProfileListAPIView.as_view()(request)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		keys = {row["key"] for row in response.data}
		self.assertIn("zkteco", keys)
		self.assertIn("stellar", keys)
		self.assertNotIn("zkteco_f18", keys)
		zkteco = next(row for row in response.data if row["key"] == "zkteco")
		stellar = next(row for row in response.data if row["key"] == "stellar")
		self.assertTrue(zkteco["supports_remote_enroll"])
		self.assertTrue(zkteco.get("supports_card", True))
		self.assertTrue(zkteco.get("supports_fingerprint", True))
		self.assertFalse(stellar["supports_remote_enroll"])
		self.assertFalse(stellar.get("supports_card", False))

	@patch("apps.attendance.services.enrollment.publish_attendance_event")
	def test_start_enrollment_queues_profile_commands(self, mock_publish):
		from apps.attendance.views import FingerprintEnrollmentStartAPIView
		from apps.attendance.models import FingerprintEnrollmentSession

		request = self.factory.post(
			"/api/v1/attendance/fingerprints/enroll/",
			{"member_id": self.member.id, "access_device_id": self.device.id},
			format="json",
		)
		force_authenticate(request, user=self.admin)
		with schema_context(self.tenant.schema_name):
			response = FingerprintEnrollmentStartAPIView.as_view()(request)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(response.data["status"], FingerprintEnrollmentSession.STATUS_QUEUED)
		with schema_context(self.tenant.schema_name):
			self.device.refresh_from_db()
			pending = self.device.meta_json.get("pending_commands", [])
		self.assertEqual(len(pending), 2)
		self.assertTrue(pending[0]["cmd"].startswith("DATA UPDATE USERINFO"))
		self.assertTrue(pending[1]["cmd"].startswith("ENROLL_FP"))

	@patch("apps.attendance.services.enrollment.publish_attendance_event")
	def test_devicecmd_ack_advances_session(self, mock_publish):
		from apps.attendance.services.enrollment import FingerprintEnrollmentService
		from apps.attendance.models import FingerprintEnrollmentSession

		with schema_context(self.tenant.schema_name):
			session = FingerprintEnrollmentService.start_enrollment(
				member=self.member,
				device=self.device,
				user=self.admin,
			)
			self.device.refresh_from_db()
			first_cmd_id = str(self.device.meta_json["pending_commands"][0]["id"])
			updated = FingerprintEnrollmentService.handle_command_ack(
				device=self.device,
				command_id=first_cmd_id,
				return_code=0,
				cmd_echo="DATA",
			)
			self.assertEqual(updated.status, FingerprintEnrollmentSession.STATUS_USERINFO_SENT)

	@patch("apps.attendance.services.enrollment.publish_attendance_event")
	def test_fp_ingest_completes_session_and_links_member(self, mock_publish):
		from apps.attendance.services.enrollment import FingerprintEnrollmentService
		from apps.attendance.models import FingerprintEnrollmentSession

		with schema_context(self.tenant.schema_name):
			session = FingerprintEnrollmentService.start_enrollment(
				member=self.member,
				device=self.device,
				user=self.admin,
			)
			session.status = FingerprintEnrollmentSession.STATUS_AWAITING_SCAN
			session.save(update_fields=["status", "updated_at"])
			completed = FingerprintEnrollmentService.handle_fingerprint_ingested(
				device=self.device,
				device_uid=session.device_uid,
			)
			self.member.refresh_from_db()
			self.assertEqual(completed.status, FingerprintEnrollmentSession.STATUS_COMPLETED)
			self.assertEqual(self.member.fingerprint_id, session.device_uid)

	def test_push_handshake_on_options_all(self):
		with schema_context(self.tenant.schema_name):
			view = IclockCdataAPIView.as_view()
			request = self.factory.get("/iclock/cdata/?SN=ZKT-F18-ENR&options=all")
			response = view(request)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		body = response.content.decode("utf-8")
		self.assertIn("GET OPTION FROM:", body)
		self.assertIn("ServerVer=3.0.1", body)
		self.assertIn("TransFlag=", body)
