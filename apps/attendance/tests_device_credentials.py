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
from apps.attendance.services.adms_commands import build_delete_userinfo_command
from apps.attendance.views import (
    FingerprintDeleteAPIView,
    FingerprintLinkAPIView,
    FingerprintUnlinkAPIView,
    FingerprintUnlinkedListAPIView,
)
from apps.membership.filters import MemberFilter
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

    def test_member_filter_gender_excludes_blank(self):
        with schema_context(self.tenant.schema_name):
            male = Member.objects.create(
                full_name="Male Member",
                phone_number="01700004001",
                gender="male",
                start_date=timezone.now().date(),
            )
            Member.objects.create(
                full_name="Blank Gender",
                phone_number="01700004002",
                gender=None,
                start_date=timezone.now().date(),
            )
            female = Member.objects.create(
                full_name="Female Member",
                phone_number="01700004003",
                gender="female",
                start_date=timezone.now().date(),
            )

            filtered = MemberFilter({"gender": "male"}, queryset=Member.objects.all()).qs
            ids = set(filtered.values_list("id", flat=True))
            self.assertIn(male.id, ids)
            self.assertNotIn(female.id, ids)
            self.assertEqual(len(ids & set(Member.objects.filter(gender__isnull=True).values_list("id", flat=True))), 0)

            all_ids = set(MemberFilter({}, queryset=Member.objects.all()).qs.values_list("id", flat=True))
            self.assertIn(male.id, all_ids)
            self.assertIn(female.id, all_ids)
            self.assertTrue(Member.objects.filter(gender__isnull=True, id__in=all_ids).exists())

    def test_member_filter_credential_linked_values(self):
        with schema_context(self.tenant.schema_name):
            none_member = Member.objects.create(
                full_name="None Creds",
                phone_number="01700004010",
                start_date=timezone.now().date(),
            )
            card_member = Member.objects.create(
                full_name="Card Creds",
                phone_number="01700004011",
                start_date=timezone.now().date(),
            )
            fp_member = Member.objects.create(
                full_name="FP Creds",
                phone_number="01700004012",
                fingerprint_id="91",
                start_date=timezone.now().date(),
            )
            both_member = Member.objects.create(
                full_name="Both Creds",
                phone_number="01700004013",
                fingerprint_id="92",
                start_date=timezone.now().date(),
            )

            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="90",
                card_number="FILTER-CARD",
                member=card_member,
                status=DeviceUser.STATUS_LINKED,
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="91",
                card_number="",
                member=fp_member,
                status=DeviceUser.STATUS_LINKED,
            )
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="92",
                card_number="FILTER-BOTH",
                member=both_member,
                status=DeviceUser.STATUS_LINKED,
            )

            def ids_for(value: str) -> set[int]:
                return set(
                    MemberFilter({"credential_linked": value}, queryset=Member.objects.all()).qs.values_list(
                        "id", flat=True
                    )
                )

            self.assertIn(none_member.id, ids_for("none"))
            self.assertNotIn(card_member.id, ids_for("none"))

            self.assertIn(card_member.id, ids_for("card"))
            self.assertNotIn(both_member.id, ids_for("card"))

            self.assertIn(fp_member.id, ids_for("fingerprint"))
            self.assertNotIn(card_member.id, ids_for("fingerprint"))

            self.assertIn(both_member.id, ids_for("both"))
            self.assertNotIn(fp_member.id, ids_for("both"))

    def test_build_delete_userinfo_command(self):
        self.assertEqual(build_delete_userinfo_command("42"), "DATA DELETE USERINFO PIN=42")

    def test_list_filters_by_access_device_id(self):
        with schema_context(self.tenant.schema_name):
            other = AccessDevice.objects.create(name="Other Gate", device_sn="DEVCRED-OTHER")
            DeviceUser.objects.create(
                access_device=self.device,
                device_uid="200",
                status=DeviceUser.STATUS_UNLINKED,
            )
            DeviceUser.objects.create(
                access_device=other,
                device_uid="201",
                status=DeviceUser.STATUS_UNLINKED,
            )

            request = self.factory.get(
                f"/api/v1/attendance/fingerprints/unlinked/?access_device_id={self.device.id}"
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintUnlinkedListAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            uids = {row["device_uid"] for row in response.data["results"]}
            self.assertIn("200", uids)
            self.assertNotIn("201", uids)

    def test_delete_queues_command_for_adms_and_clears_member(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="ADMS Gate",
                device_sn="DEVCRED-DEL-ADMS",
                mode=AccessDevice.MODE_ADMS,
                is_active=True,
            )
            member = Member.objects.create(
                full_name="Delete Me",
                phone_number="01700005001",
                card_id="DEL-CARD",
                fingerprint_id="300",
                start_date=timezone.now().date(),
            )
            device_user = DeviceUser.objects.create(
                access_device=device,
                device_uid="300",
                card_number="DEL-CARD",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/delete/",
                {"device_user_id": device_user.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintDeleteAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            device_user.refresh_from_db()
            member.refresh_from_db()
            device.refresh_from_db()
            self.assertEqual(device_user.status, DeviceUser.STATUS_DELETED)
            self.assertIsNone(device_user.member_id)
            self.assertIsNone(member.card_id)
            self.assertIsNone(member.fingerprint_id)
            self.assertEqual(member_credential_linked(member), "none")
            self.assertEqual(member_device_uids(member), [])
            pending = device.meta_json.get("pending_commands") or []
            self.assertTrue(any("DELETE USERINFO" in (c.get("cmd") or "") and "PIN=300" in (c.get("cmd") or "") for c in pending))

            list_request = self.factory.get("/api/v1/attendance/fingerprints/unlinked/")
            force_authenticate(list_request, user=self.admin)
            list_response = FingerprintUnlinkedListAPIView.as_view()(list_request)
            listed_ids = {row["id"] for row in list_response.data["results"]}
            self.assertNotIn(device_user.id, listed_ids)

    def test_delete_queues_command_for_tcp_relay(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="Relay Gate",
                device_sn="DEVCRED-DEL-RELAY",
                mode=AccessDevice.MODE_TCP_RELAY,
                is_active=True,
            )
            device_user = DeviceUser.objects.create(
                access_device=device,
                device_uid="301",
                status=DeviceUser.STATUS_UNLINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/delete/",
                {"device_user_id": device_user.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintDeleteAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            device.refresh_from_db()
            pending = device.meta_json.get("pending_commands") or []
            self.assertTrue(any("DELETE USERINFO PIN=301" in (c.get("cmd") or "") for c in pending))

    def test_delete_rejects_inactive_device(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="Off Gate",
                device_sn="DEVCRED-DEL-OFF",
                mode=AccessDevice.MODE_ADMS,
                is_active=False,
            )
            device_user = DeviceUser.objects.create(
                access_device=device,
                device_uid="302",
                status=DeviceUser.STATUS_UNLINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/delete/",
                {"device_user_id": device_user.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintDeleteAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            device_user.refresh_from_db()
            self.assertEqual(device_user.status, DeviceUser.STATUS_UNLINKED)

    def test_delete_updates_member_linked_when_other_link_remains(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="Multi Gate",
                device_sn="DEVCRED-DEL-MULTI",
                mode=AccessDevice.MODE_ADMS,
                is_active=True,
            )
            member = Member.objects.create(
                full_name="Keep One",
                phone_number="01700005002",
                card_id="KEEP-CARD",
                fingerprint_id="400",
                start_date=timezone.now().date(),
            )
            to_delete = DeviceUser.objects.create(
                access_device=device,
                device_uid="400",
                card_number="",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )
            DeviceUser.objects.create(
                access_device=device,
                device_uid="401",
                card_number="KEEP-CARD",
                member=member,
                status=DeviceUser.STATUS_LINKED,
            )

            request = self.factory.post(
                "/api/v1/attendance/fingerprints/delete/",
                {"device_user_id": to_delete.id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = FingerprintDeleteAPIView.as_view()(request)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            member.refresh_from_db()
            self.assertEqual(member_credential_linked(member), "card")
            self.assertEqual(member_device_uids(member), ["401"])
            self.assertEqual(member.card_id, "KEEP-CARD")
            self.assertIsNone(member.fingerprint_id)
