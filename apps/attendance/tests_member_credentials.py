from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.attendance.models import AccessDevice, DeviceUser
from apps.attendance.views import MemberCredentialsAPIView
from apps.identity.models import User
from apps.membership.models import Attendance, Member
from apps.tenancy.models import Domain, Tenant


class MemberCredentialsAPIViewTests(TestCase):
    SCHEMA_NAME = "member_creds_test"

    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults={
                    "name": "Public",
                    "slug": "public",
                    "code": "PUBMCRED1",
                    "owner_email": "root@membercred.test",
                    "billing_email": "root@membercred.test",
                    "status": "active",
                    "is_trial": False,
                },
            )
            Domain.objects.get_or_create(
                domain="testserver",
                tenant=public,
                defaults={"is_primary": True},
            )
            cls.tenant, _ = Tenant.objects.get_or_create(
                schema_name=cls.SCHEMA_NAME,
                defaults={
                    "name": "Member Cred Tenant",
                    "slug": "member-cred-tenant",
                    "code": "MCRED001",
                    "owner_email": "admin@membercred.test",
                    "billing_email": "admin@membercred.test",
                    "status": "active",
                    "is_trial": False,
                },
            )
            Domain.objects.get_or_create(
                domain="membercred.testserver",
                tenant=cls.tenant,
                defaults={"is_primary": True},
            )

        with schema_context(cls.tenant.schema_name):
            cls.member_user = User.objects.create_user(
                email="self@membercred.test",
                password="StrongPass123!",
                tenant=cls.tenant,
                role="student",
            )
            cls.other_user = User.objects.create_user(
                email="other@membercred.test",
                password="StrongPass123!",
                tenant=cls.tenant,
                role="student",
            )
            cls.staff_user = User.objects.create_user(
                email="staff@membercred.test",
                password="StrongPass123!",
                tenant=cls.tenant,
                role="admin",
            )
            cls.member = Member.objects.create(
                full_name="Self Member",
                phone_number="01700004001",
                email=cls.member_user.email,
                fingerprint_id="80",
                start_date=timezone.now().date(),
            )
            cls.other_member = Member.objects.create(
                full_name="Other Member",
                phone_number="01700004002",
                email=cls.other_user.email,
                fingerprint_id="90",
                start_date=timezone.now().date(),
            )
            cls.device = AccessDevice.objects.create(name="Gate", device_sn="MCRED-1")

    def setUp(self):
        self.factory = APIRequestFactory()

    def _get(self, user):
        request = self.factory.get("/api/v1/attendance/me/credentials/")
        force_authenticate(request, user=user)
        return MemberCredentialsAPIView.as_view()(request)

    def test_no_member_profile_returns_empty_payload(self):
        with schema_context(self.tenant.schema_name):
            response = self._get(self.staff_user)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "credential_linked": "none",
                "last_used_at": None,
                "last_entry_method": None,
                "last_fingerprint_used_at": None,
                "last_card_used_at": None,
            },
        )

    def test_both_credentials_with_per_type_last_use(self):
        with schema_context(self.tenant.schema_name):
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="80",
                member=self.member,
                status=DeviceUser.STATUS_LINKED,
                card_number="DUAL-CARD",
            )
            card_log = Attendance.objects.create(
                member=self.member,
                entry_method="card",
                device_id="MCRED-1",
            )
            fingerprint_log = Attendance.objects.create(
                member=self.member,
                entry_method="fingerprint",
                device_id="MCRED-1",
            )
            older = timezone.now() - timedelta(days=2)
            newer = timezone.now() - timedelta(hours=1)
            Attendance.objects.filter(id=card_log.id).update(check_in_time=older)
            Attendance.objects.filter(id=fingerprint_log.id).update(check_in_time=newer)

            # Other member logs must not leak into self response.
            Attendance.objects.create(
                member=self.other_member,
                entry_method="card",
                device_id="MCRED-OTHER",
            )

            response = self._get(self.member_user)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["credential_linked"], "both")
        self.assertEqual(response.data["last_entry_method"], "fingerprint")
        self.assertIsNotNone(response.data["last_used_at"])
        self.assertIsNotNone(response.data["last_fingerprint_used_at"])
        self.assertIsNotNone(response.data["last_card_used_at"])
        self.assertEqual(
            response.data["last_used_at"],
            response.data["last_fingerprint_used_at"],
        )
        self.assertNotEqual(
            response.data["last_fingerprint_used_at"],
            response.data["last_card_used_at"],
        )

    def test_fingerprint_only_last_card_is_null(self):
        with schema_context(self.tenant.schema_name):
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="80",
                member=self.member,
                status=DeviceUser.STATUS_LINKED,
                card_number="",
            )
            log = Attendance.objects.create(
                member=self.member,
                entry_method="fingerprint",
                device_id="MCRED-1",
            )
            Attendance.objects.filter(id=log.id).update(
                check_in_time=timezone.now() - timedelta(minutes=30),
            )

            response = self._get(self.member_user)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["credential_linked"], "fingerprint")
        self.assertEqual(response.data["last_entry_method"], "fingerprint")
        self.assertIsNotNone(response.data["last_fingerprint_used_at"])
        self.assertIsNone(response.data["last_card_used_at"])

    def test_isolation_other_member_does_not_see_self_logs(self):
        with schema_context(self.tenant.schema_name):
            Attendance.objects.create(
                member=self.member,
                entry_method="card",
                device_id="MCRED-1",
            )

            response = self._get(self.other_user)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["credential_linked"], "none")
        self.assertIsNone(response.data["last_used_at"])
        self.assertIsNone(response.data["last_card_used_at"])
        self.assertIsNone(response.data["last_fingerprint_used_at"])
