from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.attendance.models import AccessDevice, DeviceUser
from apps.attendance.services.card_provision import CardProvisionService
from apps.attendance.services.enrollment import FingerprintEnrollmentService
from apps.attendance.services.ingestion import ADMSIngestionService
from apps.membership.models import Attendance, Member
from apps.tenancy.models import Domain, Tenant


class DualCredentialParseTests(SimpleTestCase):
    def test_parse_attlog_verify_columns(self):
        body = "\n".join(
            [
                "TABLE=ATTLOG",
                "1001\t2026-01-11 10:12:30\t0\t2\t0\t0",
                "1001\t2026-01-11 10:13:30\t0\t1\t0\t0",
            ]
        )
        events = ADMSIngestionService._parse_body(body)
        self.assertEqual(events[0].verify_mode, 2)
        self.assertEqual(events[1].verify_mode, 1)
        self.assertEqual(ADMSIngestionService.entry_method_for_verify(2), "card")
        self.assertEqual(ADMSIngestionService.entry_method_for_verify(1), "fingerprint")


class DualCredentialIngestionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant(
            schema_name="dualcred",
            name="Dual Cred Gym",
        )
        cls.tenant.save()
        Domain.objects.get_or_create(
            domain="dualcred.testserver",
            tenant=cls.tenant,
            defaults={"is_primary": True},
        )

    def test_card_and_fingerprint_entry_methods(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="Gate",
                device_sn="ZKT-DUAL-1",
                device_profile="zkteco",
                device_model="K40",
                mode=AccessDevice.MODE_TCP_RELAY,
            )
            member = Member.objects.create(
                full_name="Dual Member",
                phone_number="01700000999",
                fingerprint_id="1001",
                card_id="RFID-9",
                start_date=timezone.now().date(),
            )
            DeviceUser.objects.create(
                access_device=device,
                device_uid="1001",
                member=member,
                status=DeviceUser.STATUS_LINKED,
                card_number="RFID-9",
            )

            ADMSIngestionService.process(
                device,
                "TABLE=ATTLOG\n1001\t2026-01-11 10:12:30\t0\t2\t0\t0",
            )
            att = Attendance.objects.get(member=member)
            self.assertEqual(att.entry_method, "card")
            att.check_out_time = timezone.now()
            att.save(update_fields=["check_out_time"])

            ADMSIngestionService.process(
                device,
                "TABLE=ATTLOG\n1001\t2026-01-11 11:12:30\t0\t1\t0\t0",
            )
            att2 = Attendance.objects.filter(member=member, check_out_time__isnull=True).get()
            self.assertEqual(att2.entry_method, "fingerprint")

    def test_userinfo_stores_card_number(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="Gate",
                device_sn="ZKT-DUAL-2",
                device_profile="zkteco",
                device_model="K40",
            )
            ADMSIngestionService.process(
                device,
                "TABLE=USERINFO\nPIN=1001\tName=Jane\tCard=RFID-9",
            )
            user = DeviceUser.objects.get(access_device=device, device_uid="1001")
            self.assertEqual(user.card_number, "RFID-9")
            self.assertEqual(user.name, "Jane")

    def test_tcp_relay_enrollment_allowed(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="Relay Gate",
                device_sn="ZKT-RELAY-1",
                device_profile="zkteco",
                device_model="K40",
                mode=AccessDevice.MODE_TCP_RELAY,
                is_active=True,
            )
            member = Member.objects.create(
                full_name="Enroll Me",
                phone_number="01700000888",
                start_date=timezone.now().date(),
            )
            session = FingerprintEnrollmentService.start_enrollment(
                member=member,
                device=device,
                user=None,
            )
            self.assertEqual(session.status, "queued")
            meta = device.meta_json or {}
            pending = meta.get("pending_commands") or []
            self.assertTrue(any("USERINFO" in (c.get("cmd") or "") for c in pending))

    def test_card_provision_queues_userinfo(self):
        with schema_context(self.tenant.schema_name):
            device = AccessDevice.objects.create(
                name="Relay Gate",
                device_sn="ZKT-CARD-1",
                device_profile="zkteco",
                device_model="K40",
                mode=AccessDevice.MODE_TCP_RELAY,
                is_active=True,
            )
            member = Member.objects.create(
                full_name="Card Me",
                phone_number="01700000777",
                card_id="CARD-55",
                start_date=timezone.now().date(),
            )
            result = CardProvisionService.provision(member=member, device=device)
            self.assertEqual(result["card_id"], "CARD-55")
            device.refresh_from_db()
            cmds = (device.meta_json or {}).get("pending_commands") or []
            self.assertTrue(any("Card=CARD-55" in (c.get("cmd") or "") for c in cmds))
