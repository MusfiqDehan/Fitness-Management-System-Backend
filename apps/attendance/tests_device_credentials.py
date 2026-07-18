from django.test import TestCase
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.attendance.models import AccessDevice, DeviceUser
from apps.attendance.serializers import (
    DeviceUserSerializer,
    credential_types_for,
    member_credential_linked,
    member_device_uids,
)
from apps.attendance.views import (
    FingerprintLinkAPIView,
    FingerprintUnlinkAPIView,
    FingerprintUnlinkedListAPIView,
)
from apps.membership.models import Member
from apps.membership.serializers import MemberSerializer
from apps.tenancy.models import Domain, Feature, Tenant, TenantFeatureFlag
from django.contrib.auth import get_user_model

User = get_user_model()


class CredentialTypesHelperTests(TestCase):
    def test_fingerprint_only_when_no_card(self):
        user = DeviceUser(device_uid="10", card_number="", member=None)
        self.assertEqual(credential_types_for(user), ["fingerprint"])

    def test_card_only_when_card_and_no_fingerprint_match(self):
        member = Member(full_name="A", fingerprint_id=None)
        user = DeviceUser(device_uid="10", card_number="RFID-1", member=member)
        self.assertEqual(credential_types_for(user), ["card"])

    def test_both_when_card_and_fingerprint_id_matches(self):
        member = Member(full_name="A", fingerprint_id="10")
        user = DeviceUser(device_uid="10", card_number="RFID-1", member=member)
        self.assertEqual(credential_types_for(user), ["card", "fingerprint"])


class DeviceCredentialListAndLinkTests(TestCase):
    SCHEMA_NAME = "devcred_test"

    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults={
                    "name": "Public",
                    "slug": "public",
                    "code": "PUBCRED1",
                    "owner_email": "root@devcred.test",
                    "billing_email": "root@devcred.test",
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
                    "name": "Device Cred Tenant",
                    "slug": "devcred-tenant",
                    "code": "DEVCRED1",
                    "owner_email": "admin@devcred.test",
                    "billing_email": "admin@devcred.test",
                    "status": "active",
                    "is_trial": False,
                },
            )
            Domain.objects.get_or_create(
                domain="devcred.testserver",
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
                email="admin@devcred.test",
                password="StrongPass123!",
                tenant=cls.tenant,
                is_superuser=True,
                is_staff=True,
            )
            cls.device = AccessDevice.objects.create(name="Gate", device_sn="DEVCRED-1")

    def setUp(self):
        self.factory = APIRequestFactory()

    def test_list_includes_linked_and_unlinked(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Linked Member",
                phone_number="01700003001",
                start_date=timezone.now().date(),
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="1",
                status=DeviceUser.STATUS_UNLINKED,
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="2",
                member=member,
                status=DeviceUser.STATUS_LINKED,
                card_number="CARD-2",
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="3",
                status=DeviceUser.STATUS_DELETED,
            )

            request = self.factory.get("/api/v1/attendance/fingerprints/unlinked/")
            force_authenticate(request, user=self.admin)
            response = FingerprintUnlinkedListAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            uids = {row["device_uid"] for row in response.data["results"]}
            self.assertEqual(uids, {"1", "2"})
            self.assertNotIn("3", uids)

    def test_status_filter_unlinked_only(self):
        with schema_context(self.tenant.schema_name):
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="10",
                status=DeviceUser.STATUS_UNLINKED,
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="11",
                status=DeviceUser.STATUS_LINKED,
            )

            request = self.factory.get("/api/v1/attendance/fingerprints/unlinked/?status=unlinked")
            force_authenticate(request, user=self.admin)
            response = FingerprintUnlinkedListAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["device_uid"], "10")

    def test_search_by_card_number(self):
        with schema_context(self.tenant.schema_name):
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="20",
                card_number="RFID-SEARCH",
                status=DeviceUser.STATUS_UNLINKED,
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="21",
                card_number="OTHER",
                status=DeviceUser.STATUS_UNLINKED,
            )

            request = self.factory.get(
                "/api/v1/attendance/fingerprints/unlinked/?search=RFID-SEARCH"
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintUnlinkedListAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["device_uid"], "20")
            self.assertIn("card", response.data["results"][0]["credential_types"])

    def test_serializer_credential_types_on_payload(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Dual",
                phone_number="01700003002",
                fingerprint_id="30",
                start_date=timezone.now().date(),
            )
            user = DeviceUser.objects.create(
                access_device=self.device,
                device_uid="30",
                member=member,
                card_number="DUAL-CARD",
                status=DeviceUser.STATUS_LINKED,
            )
            data = DeviceUserSerializer(user).data
            self.assertEqual(data["credential_types"], ["card", "fingerprint"])

    def test_card_only_link_sets_card_id_leaves_fingerprint_id(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Card Member",
                phone_number="01700003003",
                fingerprint_id="KEEP-ME",
                start_date=timezone.now().date(),
            )
            device_user = DeviceUser.objects.create(
                access_device=self.device,
                device_uid="40",
                card_number="NEW-CARD",
                status=DeviceUser.STATUS_UNLINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/link/",
                {"device_user_id": device_user.id, "member_id": member.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintLinkAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            device_user.refresh_from_db()
            member.refresh_from_db()
            self.assertEqual(device_user.status, DeviceUser.STATUS_LINKED)
            self.assertEqual(device_user.member_id, member.id)
            self.assertEqual(member.card_id, "NEW-CARD")
            self.assertEqual(member.fingerprint_id, "KEEP-ME")

    def test_fingerprint_only_link_sets_fingerprint_id(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="FP Member",
                phone_number="01700003004",
                start_date=timezone.now().date(),
            )
            device_user = DeviceUser.objects.create(
                access_device=self.device,
                device_uid="50",
                card_number="",
                status=DeviceUser.STATUS_UNLINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/link/",
                {"device_user_id": device_user.id, "member_id": member.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintLinkAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            member.refresh_from_db()
            self.assertEqual(member.fingerprint_id, "50")

    def test_fingerprint_link_does_not_overwrite_existing_fingerprint_id(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Keep FP",
                phone_number="01700003005",
                fingerprint_id="KEEP-FP",
                start_date=timezone.now().date(),
            )
            device_user = DeviceUser.objects.create(
                access_device=self.device,
                device_uid="51",
                card_number="",
                status=DeviceUser.STATUS_UNLINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/link/",
                {"device_user_id": device_user.id, "member_id": member.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintLinkAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            member.refresh_from_db()
            self.assertEqual(member.fingerprint_id, "KEEP-FP")

    def test_unlink_clears_matching_card_and_fingerprint(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Unlink Me",
                phone_number="01700003006",
                card_id="CARD-X",
                fingerprint_id="60",
                start_date=timezone.now().date(),
            )
            device_user = DeviceUser.objects.create(
                access_device=self.device,
                device_uid="60",
                card_number="CARD-X",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/unlink/",
                {"device_user_id": device_user.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintUnlinkAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            member.refresh_from_db()
            device_user.refresh_from_db()
            self.assertEqual(device_user.status, DeviceUser.STATUS_UNLINKED)
            self.assertIsNone(member.card_id)
            self.assertIsNone(member.fingerprint_id)

    def test_unlink_keeps_card_when_another_linked_device_has_same_card(self):
        with schema_context(self.tenant.schema_name):
            other_device = AccessDevice.objects.create(
                name="Gate B",
                device_sn="SN-GATE-B",
                mode=AccessDevice.MODE_ADMS,
                is_active=True,
            )
            member = Member.objects.create(
                full_name="Multi Device",
                phone_number="01700003007",
                card_id="SHARED-CARD",
                start_date=timezone.now().date(),
            )
            first = DeviceUser.objects.create(
                access_device=self.device,
                device_uid="70",
                card_number="SHARED-CARD",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )
            DeviceUser.objects.create(
                access_device=other_device,
                device_uid="71",
                card_number="SHARED-CARD",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/unlink/",
                {"device_user_id": first.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintUnlinkAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            member.refresh_from_db()
            self.assertEqual(member.card_id, "SHARED-CARD")

    def test_member_serializer_credential_linked_and_device_uids(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Agg Member",
                phone_number="01700003008",
                fingerprint_id="80",
                start_date=timezone.now().date(),
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="80",
                card_number="AGG-CARD",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="81",
                card_number="",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )

            self.assertEqual(member_credential_linked(member), "both")
            self.assertEqual(member_device_uids(member), ["80", "81"])
            data = MemberSerializer(member).data
            self.assertEqual(data["credential_linked"], "both")
            self.assertEqual(data["device_uids"], ["80", "81"])

    def test_member_serializer_none_when_unlinked(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="No Link",
                phone_number="01700003009",
                start_date=timezone.now().date(),
            )
            data = MemberSerializer(member).data
            self.assertEqual(data["credential_linked"], "none")
            self.assertEqual(data["device_uids"], [])
