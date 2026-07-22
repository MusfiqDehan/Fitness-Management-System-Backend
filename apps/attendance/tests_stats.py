from datetime import timedelta

from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.attendance.services.stats import AttendanceStatsService
from apps.attendance.views import AttendanceStatsAPIView
from apps.membership.models import Attendance, Member, MemberPackage
from apps.tenancy.models import Branch, Domain, Role, Tenant, User, UserRole
from django.test import TestCase


class AttendanceStatsServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            schema_name="attstats",
            name="Attendance Stats Tenant",
            slug="att-stats",
            code="ATTSTAT1",
            owner_email="admin@attstats.test",
            billing_email="admin@attstats.test",
            status="active",
            is_trial=False,
        )
        Domain.objects.create(domain="attstats.testserver", tenant=cls.tenant, is_primary=True)

    def setUp(self):
        with schema_context(self.tenant.schema_name):
            self.branch_manager = User.objects.create_user(
                email="manager@attstats.test",
                password="StrongPass123!",
                tenant=self.tenant,
                full_name="Branch Manager",
            )
            self.branch_a = Branch.objects.create(name="Downtown", manager=self.branch_manager)
            self.branch_b = Branch.objects.create(name="Uptown")
            role = Role.objects.create(name="Branch Manager", slug="branch_manager")
            UserRole.objects.create(
                user_id=self.branch_manager.id,
                user_email=self.branch_manager.email,
                branch=self.branch_a,
                role=role,
            )
            self.package = MemberPackage.objects.create(
                name="Premium",
                package_type="monthly",
                duration_in_days=30,
                price=1000,
            )
            self.member_a = Member.objects.create(
                full_name="Alice Downtown",
                phone_number="01770020001",
                branch=self.branch_a,
                is_active=True,
                membership_type="package",
                member_package=self.package,
            )
            self.member_b = Member.objects.create(
                full_name="Bob Uptown",
                phone_number="01770020002",
                branch=self.branch_b,
                is_active=True,
            )
            now = timezone.now()
            Attendance.objects.create(
                member=self.member_a,
                entry_method="fingerprint",
                device_id="SN-A",
                check_in_time=now.replace(hour=10, minute=0, second=0, microsecond=0),
            )
            Attendance.objects.create(
                member=self.member_a,
                entry_method="card",
                device_id="SN-A",
                check_in_time=now.replace(hour=18, minute=0, second=0, microsecond=0),
            )
            old_visit = Attendance.objects.create(
                member=self.member_b,
                entry_method="fingerprint",
                device_id="SN-B",
            )
            Attendance.objects.filter(id=old_visit.id).update(
                check_in_time=now - timedelta(days=10),
            )

    def test_hourly_foot_traffic_counts_check_ins_today(self):
        with schema_context(self.tenant.schema_name):
            payload = AttendanceStatsService.build_payload(
                self.branch_manager,
                hourly_range="today",
            )
            buckets = payload["hourly_foot_traffic"]["buckets"]
            hour_10 = next(item for item in buckets if item["hour"] == 10)
            hour_18 = next(item for item in buckets if item["hour"] == 18)
            self.assertEqual(hour_10["count"], 1)
            self.assertEqual(hour_18["count"], 1)

    def test_device_filter_limits_stats(self):
        with schema_context(self.tenant.schema_name):
            payload = AttendanceStatsService.build_payload(
                self.branch_manager,
                device_sn="SN-B",
            )
            self.assertEqual(payload["hourly_foot_traffic"]["buckets"][10]["count"], 0)
            self.assertEqual(len(payload["inactive_members"]["results"]), 0)

    def test_branch_scope_excludes_other_branch_members(self):
        with schema_context(self.tenant.schema_name):
            payload = AttendanceStatsService.build_payload(self.branch_manager)
            member_ids = {row["member_id"] for row in payload["top_streaks"]["results"]}
            self.assertIn(self.member_a.id, member_ids)
            self.assertNotIn(self.member_b.id, member_ids)

    def test_inactive_members_lists_members_not_visited_in_seven_days(self):
        with schema_context(self.tenant.schema_name):
            admin = User.objects.create_user(
                email="admin@attstats.test",
                password="StrongPass123!",
                tenant=self.tenant,
                full_name="Tenant Admin",
                role="admin",
            )
            payload = AttendanceStatsService.build_payload(admin)
            inactive_ids = {row["member_id"] for row in payload["inactive_members"]["results"]}
            self.assertIn(self.member_b.id, inactive_ids)
            self.assertNotIn(self.member_a.id, inactive_ids)


class AttendanceStatsAPIViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            schema_name="attstatsapi",
            name="Attendance Stats API Tenant",
            slug="att-stats-api",
            code="ATTSTAT2",
            owner_email="admin@attstatsapi.test",
            billing_email="admin@attstatsapi.test",
            status="active",
            is_trial=False,
        )
        Domain.objects.create(domain="attstatsapi.testserver", tenant=cls.tenant, is_primary=True)

    def setUp(self):
        self.factory = APIRequestFactory()
        with schema_context(self.tenant.schema_name):
            self.user = User.objects.create_user(
                email="admin@attstatsapi.test",
                password="StrongPass123!",
                tenant=self.tenant,
                full_name="Tenant Admin",
                role="admin",
            )
            self.member = Member.objects.create(
                full_name="Stats Member",
                phone_number="01770030001",
                is_active=True,
            )
            Attendance.objects.create(member=self.member, entry_method="fingerprint", device_id="SN-1")

    def test_stats_endpoint_returns_payload_sections(self):
        request = self.factory.get("/api/v1/attendance/stats/?hourly_range=today")
        request.user = self.user
        with schema_context(self.tenant.schema_name):
            response = AttendanceStatsAPIView.as_view()(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("hourly_foot_traffic", response.data)
        self.assertIn("visit_heatmap", response.data)
        self.assertIn("top_streaks", response.data)
        self.assertIn("inactive_members", response.data)
