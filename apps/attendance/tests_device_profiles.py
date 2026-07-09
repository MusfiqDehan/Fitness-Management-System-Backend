from django.test import SimpleTestCase

from apps.attendance.device_profiles import get_device_profile, list_device_profiles


class BiometricDeviceProfileTests(SimpleTestCase):
    def test_list_includes_f18_and_k_series_profiles(self):
        keys = {profile.key for profile in list_device_profiles()}
        self.assertIn("zkteco_f18", keys)
        self.assertIn("zkteco_f18_pro", keys)
        self.assertIn("zkteco_k40", keys)
        self.assertIn("zkteco_k60", keys)

    def test_k40_and_k60_support_remote_enroll(self):
        for key in ("zkteco_k40", "zkteco_k60"):
            profile = get_device_profile(key)
            self.assertTrue(profile.supports_remote_enroll)
            self.assertEqual(profile.manufacturer, "ZKTeco")
            cmd = profile.build_remote_enroll_command(pin="11", fingerprint_slot=0)
            self.assertTrue(cmd.startswith("ENROLL_FP"))
            self.assertIn("PIN=11", cmd)

    def test_build_userinfo_command(self):
        profile = get_device_profile("zkteco_f18")
        cmd = profile.build_userinfo_command(pin="42", name="Jane Doe")
        self.assertIn("DATA UPDATE USERINFO", cmd)
        self.assertIn("PIN=42", cmd)
        self.assertIn("Name=Jane Doe", cmd)

    def test_build_remote_enroll_command(self):
        profile = get_device_profile("zkteco_f18_pro")
        cmd = profile.build_remote_enroll_command(pin="7", fingerprint_slot=1)
        self.assertTrue(cmd.startswith("ENROLL_FP"))
        self.assertIn("PIN=7", cmd)
        self.assertIn("FID=1", cmd)
