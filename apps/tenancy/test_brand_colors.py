"""Brand colour validation shared by the tenant and platform gym profiles.

Both Settings → Gym Profile forms feed ``normalize_brand_color``; these tests
pin the accepted input shapes so the two serializers cannot drift apart.
"""
from django.test import SimpleTestCase
from rest_framework import serializers as drf_serializers

from apps.dashboard.serializers import GymProfileSerializer
from apps.tenancy.serializers import PlatformGymProfileSerializer
from utils.brand_colors import normalize_brand_color

SERIALIZERS = (GymProfileSerializer, PlatformGymProfileSerializer)


class NormalizeBrandColorTests(SimpleTestCase):
    def test_canonicalises_to_lowercase_six_digit_hex(self):
        self.assertEqual(normalize_brand_color("#FFC300"), "#ffc300")
        self.assertEqual(normalize_brand_color("  #FfC300 "), "#ffc300")

    def test_adds_missing_hash(self):
        self.assertEqual(normalize_brand_color("ffc300"), "#ffc300")

    def test_expands_shorthand(self):
        self.assertEqual(normalize_brand_color("#abc"), "#aabbcc")

    def test_blank_means_no_override(self):
        self.assertEqual(normalize_brand_color(""), "")
        self.assertEqual(normalize_brand_color("   "), "")
        self.assertEqual(normalize_brand_color(None), "")

    def test_rejects_malformed_values(self):
        for value in ("#ff", "red", "#gggggg", "#ffc3000", "rgb(1,2,3)"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_brand_color(value)


class BrandColorSerializerTests(SimpleTestCase):
    def test_both_profile_serializers_normalise_colors(self):
        for serializer_class in SERIALIZERS:
            with self.subTest(serializer=serializer_class.__name__):
                serializer = serializer_class(
                    data={"primary_color": "FFC300", "secondary_color": "#abc"},
                    partial=True,
                )
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data["primary_color"], "#ffc300")
                self.assertEqual(serializer.validated_data["secondary_color"], "#aabbcc")

    def test_both_profile_serializers_reject_bad_colors(self):
        for serializer_class in SERIALIZERS:
            with self.subTest(serializer=serializer_class.__name__):
                serializer = serializer_class(data={"primary_color": "not-a-colour"}, partial=True)
                self.assertFalse(serializer.is_valid())
                self.assertIn("primary_color", serializer.errors)
                self.assertIsInstance(
                    serializer.errors["primary_color"][0],
                    drf_serializers.ErrorDetail,
                )

    def test_clearing_a_color_is_allowed(self):
        for serializer_class in SERIALIZERS:
            with self.subTest(serializer=serializer_class.__name__):
                serializer = serializer_class(
                    data={"primary_color": "", "secondary_color": ""},
                    partial=True,
                )
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data["primary_color"], "")
                self.assertEqual(serializer.validated_data["secondary_color"], "")
