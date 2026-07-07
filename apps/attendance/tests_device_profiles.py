from django.test import SimpleTestCase

from apps.attendance.device_profiles import get_device_profile, list_device_profiles


class BiometricDeviceProfileTests(SimpleTestCase):
    def test_list_includes_f18_profiles(self):
        keys = {profile.key for profile in list_device_profiles()}
        self.assertIn("zkteco_f18", keys)
        self.assertIn("zkteco_f18_pro", keys)

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
