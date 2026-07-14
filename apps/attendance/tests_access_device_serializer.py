from django.test import SimpleTestCase
from rest_framework.serializers import ValidationError

from apps.attendance.serializers import AccessDeviceSerializer


class AccessDeviceSerializerProfileTests(SimpleTestCase):
    def test_zkteco_requires_device_model(self):
        serializer = AccessDeviceSerializer()
        with self.assertRaises(ValidationError) as ctx:
            serializer.validate({"device_profile": "zkteco", "device_model": ""})
        self.assertIn("device_model", ctx.exception.detail)

    def test_zkteco_with_model_valid(self):
        serializer = AccessDeviceSerializer()
        result = serializer.validate({"device_profile": "zkteco", "device_model": "K40"})
        self.assertEqual(result["device_model"], "K40")

    def test_stellar_allows_empty_model(self):
        serializer = AccessDeviceSerializer()
        result = serializer.validate({"device_profile": "stellar", "device_model": ""})
        self.assertEqual(result["device_model"], "")

    def test_legacy_profile_rejected(self):
        serializer = AccessDeviceSerializer()
        with self.assertRaises(ValidationError):
            serializer.validate_device_profile("zkteco_f18")
