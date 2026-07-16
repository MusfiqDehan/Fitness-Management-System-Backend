"""Platform public branding + gym-profile GET permission tests."""
from django.core.cache import cache
from django.test import override_settings
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from apps.tenancy.models import (
    Domain,
    PlatformGymProfile,
    PlatformRole,
    PlatformRolePermission,
    PlatformUserRole,
    Tenant,
)
from utils.cache_helpers import public_branding_key


@override_settings(PUBLIC_DOMAIN="testserver")
class PlatformPublicBrandingApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            cls.public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults=dict(
                    name="Public",
                    slug="public",
                    code="BRANDTEST",
                    owner_email="root@brand.test",
                    billing_email="root@brand.test",
                    status="active",
                    is_trial=False,
                ),
            )
            Domain.objects.get_or_create(
                domain="testserver",
                tenant=cls.public,
                defaults={"is_primary": True},
            )
            cls.staff = User.objects.create_user(
                email="staff@brand.test",
                password="Test@1234",
                tenant=cls.public,
            )
            cls.staff.is_staff = True
            cls.staff.save(update_fields=["is_staff"])

            # Role with tenants view only — intentionally no platform.settings
            role = PlatformRole.objects.create(
                name="Tenant Viewer",
                slug="tenant-viewer-brand",
            )
            PlatformRolePermission.objects.create(
                role=role,
                module_key="platform.tenants",
                permission_level="view",
            )
            PlatformUserRole.objects.create(user=cls.staff, role=role)

            PlatformGymProfile.objects.update_or_create(
                pk=1,
                defaults={
                    "gym_name": "Fitssort Platform",
                    "email": "contact@fitssort.com",
                    "phone": "+8801000000000",
                    "logo_url": "https://cdn.example.com/logo.png",
                    "logo_width": 140,
                    "logo_height": 48,
                },
            )

    def setUp(self):
        cache.clear()

    def test_public_site_settings_returns_platform_gym_profile(self):
        res = self.client.get(
            "/api/v1/cms/public/site-settings/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["company_name"], "Fitssort Platform")
        self.assertEqual(res.data["logo_url"], "https://cdn.example.com/logo.png")
        self.assertEqual(res.data["discount_enabled"], False)

    def test_public_site_settings_empty_profile_returns_200_not_404(self):
        with schema_context("public"):
            PlatformGymProfile.objects.filter(pk=1).delete()

        res = self.client.get(
            "/api/v1/cms/public/site-settings/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["company_name"], "")
        self.assertEqual(res.data["logo_url"], "")
        self.assertEqual(res.data["logo_width"], 120)
        self.assertEqual(res.data["logo_height"], 40)
        self.assertEqual(res.data["discount_enabled"], False)

    def test_platform_user_without_settings_can_get_gym_profile(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(
            "/api/v1/dashboard/settings/gym-profile/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["gym_name"], "Fitssort Platform")

    def test_platform_user_without_settings_edit_cannot_patch_gym_profile(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.patch(
            "/api/v1/dashboard/settings/gym-profile/",
            {"gym_name": "Hacked"},
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_platform_gym_profile_save_invalidates_public_branding_cache(self):
        key = public_branding_key("public")
        cache.set(key, {"company_name": "STALE"}, timeout=900)

        with schema_context("public"):
            profile = PlatformGymProfile.objects.get(pk=1)
            profile.gym_name = "Updated Platform"
            profile.save()

        self.assertIsNone(cache.get(key))
