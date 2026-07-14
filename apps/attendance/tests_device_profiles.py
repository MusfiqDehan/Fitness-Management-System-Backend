from django.test import SimpleTestCase

from apps.attendance.device_profiles import (
    get_device_profile,
    is_valid_device_profile,
    list_device_profiles,
)


class BiometricDeviceProfileTests(SimpleTestCase):
    def test_list_includes_zkteco_and_stellar(self):
        keys = {profile.key for profile in list_device_profiles()}
        self.assertEqual(keys, {"zkteco", "stellar"})
        self.assertNotIn("zkteco_f18", keys)
        self.assertNotIn("zkteco_k40", keys)

    def test_zkteco_supports_remote_enroll(self):
        profile = get_device_profile("zkteco")
        self.assertTrue(profile.supports_remote_enroll)
        self.assertEqual(profile.manufacturer, "ZKTeco")
        cmd = profile.build_remote_enroll_command(pin="11", fingerprint_slot=0)
        self.assertTrue(cmd.startswith("ENROLL_FP"))
        self.assertIn("PIN=11", cmd)

    def test_stellar_does_not_support_remote_enroll(self):
        profile = get_device_profile("stellar")
        self.assertFalse(profile.supports_remote_enroll)
        self.assertEqual(profile.manufacturer, "Stellar")

    def test_legacy_keys_invalid(self):
        for key in ("zkteco_f18", "zkteco_f18_pro", "zkteco_k40", "zkteco_k60"):
            self.assertFalse(is_valid_device_profile(key))

    def test_build_userinfo_command(self):
        profile = get_device_profile("zkteco")
        cmd = profile.build_userinfo_command(pin="42", name="Jane Doe")
        self.assertIn("DATA UPDATE USERINFO", cmd)
        self.assertIn("PIN=42", cmd)
        self.assertIn("Name=Jane Doe", cmd)

    def test_build_remote_enroll_command(self):
        profile = get_device_profile("zkteco")
        cmd = profile.build_remote_enroll_command(pin="7", fingerprint_slot=1)
        self.assertTrue(cmd.startswith("ENROLL_FP"))
        self.assertIn("PIN=7", cmd)
        self.assertIn("FID=1", cmd)
