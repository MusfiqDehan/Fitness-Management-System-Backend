"""Public-schema CMS API tests (dual-schema blogs/banners)."""
import shutil
import tempfile

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cms.models import Blog, BlogCategory, SiteBanner
from apps.identity.models import User
from apps.tenancy.models import (
    Domain,
    PlatformGymProfile,
    PlatformRole,
    PlatformRolePermission,
    PlatformUserRole,
    Tenant,
)

TEST_GIF_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="cms-public-schema-tests-")


@override_settings(PUBLIC_DOMAIN="testserver", MEDIA_ROOT=TEST_MEDIA_ROOT)
class PublicSchemaCmsApiTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            cls.public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults=dict(
                    name="Public",
                    slug="public",
                    code="PUBCMS02",
                    owner_email="root@cms-public.test",
                    billing_email="root@cms-public.test",
                    status="active",
                    is_trial=False,
                ),
            )
            Domain.objects.get_or_create(
                domain="testserver",
                tenant=cls.public,
                defaults={"is_primary": True},
            )

            cls.editor = User.objects.create_user(
                email="cms-editor@cms-public.test",
                password="Test@1234",
                tenant=cls.public,
            )
            editor_role = PlatformRole.objects.create(
                name="CMS Editor",
                slug="cms-editor-public",
            )
            PlatformRolePermission.objects.create(
                role=editor_role,
                module_key="platform.cms.banners",
                permission_level="edit",
            )
            PlatformRolePermission.objects.create(
                role=editor_role,
                module_key="platform.cms.blogs",
                permission_level="edit",
            )
            PlatformUserRole.objects.create(user=cls.editor, role=editor_role)

            cls.viewer = User.objects.create_user(
                email="cms-viewer@cms-public.test",
                password="Test@1234",
                tenant=cls.public,
            )
            viewer_role = PlatformRole.objects.create(
                name="CMS Viewer Denied",
                slug="cms-viewer-denied",
            )
            PlatformRolePermission.objects.create(
                role=viewer_role,
                module_key="platform.tenants",
                permission_level="view",
            )
            PlatformUserRole.objects.create(user=cls.viewer, role=viewer_role)

            PlatformGymProfile.objects.update_or_create(
                pk=1,
                defaults={
                    "gym_name": "Fitssort Platform",
                    "email": "contact@fitness.musfiqdehan.com",
                    "phone": "+8801000000000",
                },
            )

            SiteBanner.objects.create(
                title="Platform Hero",
                subtitle="Public schema banner",
                media_type="image",
                desktop_url="https://example.com/platform-hero.jpg",
                is_active=True,
                position=1,
            )
            category = BlogCategory.objects.create(name="Platform News")
            Blog.objects.create(
                title="Hello Platform",
                slug="hello-platform",
                image=SimpleUploadedFile(
                    "hello-platform.gif", TEST_GIF_BYTES, content_type="image/gif"
                ),
                excerpt="Public blog",
                description="Body",
                category=category,
                author=cls.editor,
                status="published",
                published_date=timezone.now(),
                is_show_on_home_page=True,
            )

    def setUp(self):
        cache.clear()

    def test_public_site_banners_allow_any(self):
        res = self.client.get(
            "/api/v1/cms/site-banners/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        titles = [row["title"] for row in res.data.get("results", res.data)]
        self.assertIn("Platform Hero", titles)

    def test_public_blogs_allow_any(self):
        res = self.client.get(
            "/api/v1/cms/blogs/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        slugs = [row["slug"] for row in res.data.get("results", res.data)]
        self.assertIn("hello-platform", slugs)

    def test_platform_user_with_edit_can_create_banner(self):
        self.client.force_authenticate(user=self.editor)
        res = self.client.post(
            "/api/v1/cms/admin/site-banners/create/",
            {
                "title": "New Platform Banner",
                "subtitle": "Created via admin",
                "media_type": "image",
                "desktop_url": "https://example.com/new.jpg",
                "is_active": True,
                "position": 2,
            },
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["title"], "New Platform Banner")

    def test_platform_user_without_cms_permission_denied(self):
        self.client.force_authenticate(user=self.viewer)
        res = self.client.get(
            "/api/v1/cms/admin/site-banners/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_branding_site_settings_not_shadowed_by_cms_include(self):
        res = self.client.get(
            "/api/v1/cms/public/site-settings/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get("company_name"), "Fitssort Platform")
        self.assertFalse(res.data.get("discount_enabled"))
