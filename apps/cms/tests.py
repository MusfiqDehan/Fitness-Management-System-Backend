import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase, APIRequestFactory, force_authenticate

from apps.dashboard.views import FileUploadView
from apps.identity.models import User
from apps.tenancy.models import Domain, Feature, Tenant, TenantFeatureFlag

from .models import Blog, BlogCategory, PromoBanner, SiteBanner
from .views import (
	BlogCategoryCreateAPIView,
	BlogCategoryListAPIView,
	DashboardBlogCreateAPIView,
	DashboardBlogDeleteAPIView,
	DashboardBlogListAPIView,
	DashboardBlogRetrieveAPIView,
	DashboardBlogUpdateAPIView,
	PromoBannerCreateAPIView,
	PromoBannerDeleteAPIView,
	PromoBannerListAPIView,
	PromoBannerRetrieveAPIView,
	PromoBannerUpdateAPIView,
	PublicBlogDetailView,
	PublicBlogListView,
	PublicPromoBannerListView,
	PublicSiteBannerListView,
	SiteBannerCreateAPIView,
	SiteBannerDeleteAPIView,
	SiteBannerListAPIView,
	SiteBannerRetrieveAPIView,
	SiteBannerUpdateAPIView,
)


TEST_GIF_BYTES = (
	b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
	b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
	b"\x00\x02\x02D\x01\x00;"
)
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="cms-banner-tests-")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class CMSBannerApiTests(APITestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

	def setUp(self):
		with schema_context("public"):
			self.public = Tenant.objects.create(
				schema_name="public",
				name="Public",
				slug="public",
				code="PUBCMS01",
				owner_email="root@cms.test",
				billing_email="root@cms.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain="testserver",
				tenant=self.public,
				defaults={"is_primary": True},
			)

			self.tenant = Tenant.objects.create(
				schema_name="cms_banner_test",
				name="CMS Banner Tenant",
				slug="cms-banner-tenant",
				code="CMSBANNER1",
				owner_email="admin@cms.test",
				billing_email="admin@cms.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.create(domain="api.testserver", tenant=self.tenant, is_primary=True)
			for key, name in (("cms.banners", "Banner Manager"), ("cms.blogs", "Blog Manager")):
				feature, _ = Feature.objects.get_or_create(
					key=key,
					defaults={"name": name, "description": f"{name} access"},
				)
				TenantFeatureFlag.objects.get_or_create(
					tenant=self.tenant,
					feature=feature,
					defaults={
						"is_enabled": True,
						"source": TenantFeatureFlag.SOURCE_OVERRIDE,
					},
				)

		with schema_context(self.tenant.schema_name):
			self.user = User.objects.create_superuser(
				email="admin@cms.test",
				password="StrongPass123!",
				tenant=self.tenant,
			)

		self.factory = APIRequestFactory()

	def _call_tenant_view(self, view, method, path, data=None, *, user=None, format="json", **kwargs):
		request_factory = getattr(self.factory, method.lower())
		request = request_factory(path, data=data, format=format)
		request.tenant = self.tenant
		if user is not None:
			force_authenticate(request, user=user)
		with schema_context(self.tenant.schema_name):
			return view(request, **kwargs)

	def test_site_banner_admin_crud_cycle(self):
		create_response = self._call_tenant_view(
			SiteBannerCreateAPIView.as_view(),
			"post",
			reverse("cms:site-banner-create"),
			{
				"title": "Summer Strength",
				"subtitle": "Join before June ends",
				"media_type": "image",
				"desktop_url": "https://example.com/hero-desktop.jpg",
				"tablet_url": "https://example.com/hero-tablet.jpg",
				"mobile_url": "https://example.com/hero-mobile.jpg",
				"cta_text": "Join Now",
				"cta_link": "/packages",
				"alt_text": "Members training with kettlebells",
				"start_date": "2026-05-01",
				"end_date": "2026-05-31",
				"position": 1,
				"is_active": True,
			},
			user=self.user,
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		created_payload = create_response.data
		banner_id = created_payload["id"]
		self.assertEqual(created_payload["alt_text"], "Members training with kettlebells")

		list_response = self._call_tenant_view(
			SiteBannerListAPIView.as_view(),
			"get",
			reverse("cms:site-banner-list"),
			user=self.user,
		)
		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data["count"], 1)

		detail_response = self._call_tenant_view(
			SiteBannerRetrieveAPIView.as_view(),
			"get",
			reverse("cms:site-banner-detail", args=[banner_id]),
			user=self.user,
			pk=banner_id,
		)
		self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
		self.assertEqual(detail_response.data["title"], "Summer Strength")

		update_response = self._call_tenant_view(
			SiteBannerUpdateAPIView.as_view(),
			"patch",
			reverse("cms:site-banner-update", args=[banner_id]),
			{
				"title": "Summer Strength Reloaded",
				"end_date": "2026-06-15",
				"is_active": False,
			},
			user=self.user,
			pk=banner_id,
		)
		self.assertEqual(update_response.status_code, status.HTTP_200_OK)
		updated_payload = update_response.data
		self.assertEqual(updated_payload["title"], "Summer Strength Reloaded")
		self.assertFalse(updated_payload["is_active"])

		delete_response = self._call_tenant_view(
			SiteBannerDeleteAPIView.as_view(),
			"delete",
			reverse("cms:site-banner-delete", args=[banner_id]),
			user=self.user,
			pk=banner_id,
		)
		self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

	def test_site_banner_create_accepts_local_media_paths(self):
		create_response = self._call_tenant_view(
			SiteBannerCreateAPIView.as_view(),
			"post",
			reverse("cms:site-banner-create"),
			{
				"title": "Hero with Local Media",
				"subtitle": "Uploaded via dashboard",
				"media_type": "image",
				"desktop_url": "/media/uploads/hero-desktop.jpg",
				"laptop_url": "/media/uploads/hero-laptop.jpg",
				"tablet_url": "/media/uploads/hero-tablet.jpg",
				"mobile_url": "/media/uploads/hero-mobile.jpg",
				"cta_text": "Join Today",
				"cta_link": "/hello",
				"alt_text": "Hero banner",
				"is_active": True,
			},
			user=self.user,
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(create_response.data["desktop_url"], "/media/uploads/hero-desktop.jpg")

	def test_site_banner_video_create_accepts_uploaded_media_paths(self):
		create_response = self._call_tenant_view(
			SiteBannerCreateAPIView.as_view(),
			"post",
			reverse("cms:site-banner-create"),
			{
				"title": "Hero Video",
				"subtitle": "Looped gym reel",
				"media_type": "video",
				"desktop_url": "/media/uploads/hero-desktop.mp4",
				"tablet_url": "/media/uploads/hero-tablet.mp4",
				"mobile_url": "/media/uploads/hero-mobile.mp4",
				"cta_text": "Watch Now",
				"cta_link": "/pricing",
				"alt_text": "Members training in a cinematic hero video",
				"is_active": True,
			},
			user=self.user,
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(create_response.data["media_type"], "video")
		self.assertEqual(create_response.data["desktop_url"], "/media/uploads/hero-desktop.mp4")

	def test_promo_banner_admin_crud_cycle(self):
		create_response = self._call_tenant_view(
			PromoBannerCreateAPIView.as_view(),
			"post",
			reverse("cms:promo-banner-create"),
			{
				"banner_type": "popup_modal",
				"title": "Newsletter Offer",
				"subtitle": "Get 10% off your first month",
				"image_url": "https://example.com/promo-default.jpg",
				"desktop_image_url": "https://example.com/promo-desktop.jpg",
				"tablet_image_url": "https://example.com/promo-tablet.jpg",
				"mobile_image_url": "https://example.com/promo-mobile.jpg",
				"cta_text": "Subscribe",
				"link_url": "/newsletter",
				"alt_text": "Promotional newsletter popup",
				"start_date": "2026-05-01",
				"end_date": "2026-05-31",
				"is_active": True,
			},
			user=self.user,
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		created_payload = create_response.data
		banner_id = created_payload["id"]
		self.assertEqual(created_payload["cta_text"], "Subscribe")

		list_response = self._call_tenant_view(
			PromoBannerListAPIView.as_view(),
			"get",
			reverse("cms:promo-banner-list"),
			user=self.user,
		)
		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data["count"], 1)

		detail_response = self._call_tenant_view(
			PromoBannerRetrieveAPIView.as_view(),
			"get",
			reverse("cms:promo-banner-detail", args=[banner_id]),
			user=self.user,
			pk=banner_id,
		)
		self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
		self.assertEqual(detail_response.data["title"], "Newsletter Offer")

		update_response = self._call_tenant_view(
			PromoBannerUpdateAPIView.as_view(),
			"patch",
			reverse("cms:promo-banner-update", args=[banner_id]),
			{
				"title": "Newsletter Offer Extended",
				"is_active": False,
			},
			user=self.user,
			pk=banner_id,
		)
		self.assertEqual(update_response.status_code, status.HTTP_200_OK)
		updated_payload = update_response.data
		self.assertEqual(updated_payload["title"], "Newsletter Offer Extended")
		self.assertFalse(updated_payload["is_active"])

		delete_response = self._call_tenant_view(
			PromoBannerDeleteAPIView.as_view(),
			"delete",
			reverse("cms:promo-banner-delete", args=[banner_id]),
			user=self.user,
			pk=banner_id,
		)
		self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

	def test_promo_banner_create_accepts_local_media_paths(self):
		create_response = self._call_tenant_view(
			PromoBannerCreateAPIView.as_view(),
			"post",
			reverse("cms:promo-banner-create"),
			{
				"banner_type": "popup_modal",
				"title": "Website Top Banner",
				"subtitle": "Local upload URL support",
				"image_url": "/media/uploads/default-promo.jpg",
				"desktop_image_url": "/media/uploads/desktop-promo.jpg",
				"tablet_image_url": "/media/uploads/tablet-promo.jpg",
				"mobile_image_url": "/media/uploads/mobile-promo.jpg",
				"cta_text": "Join",
				"link_url": "/hello",
				"alt_text": "Promo banner image",
				"is_active": True,
			},
			user=self.user,
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(create_response.data["image_url"], "/media/uploads/default-promo.jpg")
		self.assertEqual(create_response.data["desktop_image_url"], "/media/uploads/desktop-promo.jpg")

	def test_public_banner_endpoints_filter_by_schedule(self):
		today = timezone.now().date()

		with schema_context(self.tenant.schema_name):
			SiteBanner.objects.create(
				title="Live Hero",
				subtitle="Visible now",
				desktop_url="https://example.com/live-hero.jpg",
				alt_text="Live hero banner",
				position=1,
				start_date=today,
				end_date=today + timedelta(days=5),
				is_active=True,
			)
			SiteBanner.objects.create(
				title="Future Hero",
				subtitle="Starts later",
				desktop_url="https://example.com/future-hero.jpg",
				alt_text="Future hero banner",
				position=2,
				start_date=today + timedelta(days=2),
				end_date=today + timedelta(days=10),
				is_active=True,
			)
			PromoBanner.objects.create(
				banner_type="top_bar",
				title="Live Topbar",
				desktop_image_url="https://example.com/live-topbar.jpg",
				link_url="/offers",
				alt_text="Live top bar",
				start_date=today,
				end_date=today + timedelta(days=5),
				is_active=True,
			)
			PromoBanner.objects.create(
				banner_type="top_bar",
				title="Expired Topbar",
				desktop_image_url="https://example.com/expired-topbar.jpg",
				link_url="/expired",
				alt_text="Expired top bar",
				start_date=today - timedelta(days=10),
				end_date=today - timedelta(days=1),
				is_active=True,
			)

		site_response = self._call_tenant_view(
			PublicSiteBannerListView.as_view(),
			"get",
			reverse("cms:public-site-banners"),
		)
		self.assertEqual(site_response.status_code, status.HTTP_200_OK)
		site_payload = site_response.data
		self.assertEqual(len(site_payload["results"]), 1)
		self.assertEqual(site_payload["results"][0]["title"], "Live Hero")

		promo_response = self._call_tenant_view(
			PublicPromoBannerListView.as_view(),
			"get",
			reverse("cms:public-promo-banners") + "?banner_type=top_bar",
		)
		self.assertEqual(promo_response.status_code, status.HTTP_200_OK)
		promo_payload = promo_response.data
		self.assertEqual(len(promo_payload["results"]), 1)
		self.assertEqual(promo_payload["results"][0]["title"], "Live Topbar")

	def test_dashboard_upload_accepts_banner_image(self):
		upload_response = self._call_tenant_view(
			FileUploadView.as_view(),
			"post",
			reverse("dashboard:file-upload"),
			{
				"file": SimpleUploadedFile(
					"banner.gif",
					TEST_GIF_BYTES,
					content_type="image/gif",
				)
			},
			user=self.user,
			format="multipart",
		)

		self.assertEqual(upload_response.status_code, status.HTTP_201_CREATED)
		upload_payload = upload_response.data
		self.assertIn("file_url", upload_payload)
		self.assertIn("/media/uploads/", upload_payload["file_url"])

	def test_blog_category_and_blog_admin_crud_cycle(self):
		category_create_response = self._call_tenant_view(
			BlogCategoryCreateAPIView.as_view(),
			"post",
			reverse("cms:blog-category-create"),
			{"name": "Fitness"},
			user=self.user,
		)
		self.assertEqual(category_create_response.status_code, status.HTTP_201_CREATED)
		category_id = category_create_response.data["id"]

		category_list_response = self._call_tenant_view(
			BlogCategoryListAPIView.as_view(),
			"get",
			reverse("cms:blog-category-list"),
			user=self.user,
		)
		self.assertEqual(category_list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(category_list_response.data["count"], 1)

		blog_create_response = self._call_tenant_view(
			DashboardBlogCreateAPIView.as_view(),
			"post",
			reverse("cms:blog-create"),
			{
				"title": "Progressive Overload Guide",
				"slug": "progressive-overload-guide",
				"excerpt": "How to progress safely every week.",
				"description": "Detailed blog description for overload principles.",
				"status": "draft",
				"is_show_on_home_page": True,
				"category_id": category_id,
				"image": SimpleUploadedFile("blog.gif", TEST_GIF_BYTES, content_type="image/gif"),
			},
			user=self.user,
			format="multipart",
		)
		self.assertEqual(blog_create_response.status_code, status.HTTP_201_CREATED)
		blog_id = blog_create_response.data["id"]
		self.assertEqual(blog_create_response.data["category"]["id"], category_id)
		self.assertEqual(blog_create_response.data["status"], "draft")

		blog_list_response = self._call_tenant_view(
			DashboardBlogListAPIView.as_view(),
			"get",
			reverse("cms:blog-list"),
			user=self.user,
		)
		self.assertEqual(blog_list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(blog_list_response.data["count"], 1)

		blog_detail_response = self._call_tenant_view(
			DashboardBlogRetrieveAPIView.as_view(),
			"get",
			reverse("cms:blog-detail", args=[blog_id]),
			user=self.user,
			pk=blog_id,
		)
		self.assertEqual(blog_detail_response.status_code, status.HTTP_200_OK)
		self.assertEqual(blog_detail_response.data["title"], "Progressive Overload Guide")

		blog_update_response = self._call_tenant_view(
			DashboardBlogUpdateAPIView.as_view(),
			"patch",
			reverse("cms:blog-update", args=[blog_id]),
			{
				"status": "published",
				"excerpt": "Updated summary.",
				"category_id": category_id,
			},
			user=self.user,
			pk=blog_id,
		)
		self.assertEqual(blog_update_response.status_code, status.HTTP_200_OK)
		self.assertEqual(blog_update_response.data["status"], "published")
		self.assertIsNotNone(blog_update_response.data["published_date"])

		blog_delete_response = self._call_tenant_view(
			DashboardBlogDeleteAPIView.as_view(),
			"delete",
			reverse("cms:blog-delete", args=[blog_id]),
			user=self.user,
			pk=blog_id,
		)
		self.assertEqual(blog_delete_response.status_code, status.HTTP_204_NO_CONTENT)

	def test_public_blog_endpoints_only_show_published_posts(self):
		with schema_context(self.tenant.schema_name):
			category = BlogCategory.objects.create(name="Wellness", slug="wellness")
			Blog.objects.create(
				title="Published Recovery",
				slug="published-recovery",
				image=SimpleUploadedFile("published.gif", TEST_GIF_BYTES, content_type="image/gif"),
				category=category,
				excerpt="Visible post",
				description="Published details",
				status="published",
				published_date=timezone.now(),
			)
			Blog.objects.create(
				title="Draft Recovery",
				slug="draft-recovery",
				image=SimpleUploadedFile("draft.gif", TEST_GIF_BYTES, content_type="image/gif"),
				category=category,
				excerpt="Hidden post",
				description="Draft details",
				status="draft",
			)

		public_list_response = self._call_tenant_view(
			PublicBlogListView.as_view(),
			"get",
			reverse("cms:public-blog-list"),
		)
		self.assertEqual(public_list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(public_list_response.data["count"], 1)
		self.assertEqual(public_list_response.data["results"][0]["slug"], "published-recovery")

		public_detail_response = self._call_tenant_view(
			PublicBlogDetailView.as_view(),
			"get",
			reverse("cms:public-blog-detail", args=["published-recovery"]),
			slug="published-recovery",
		)
		self.assertEqual(public_detail_response.status_code, status.HTTP_200_OK)

		draft_detail_response = self._call_tenant_view(
			PublicBlogDetailView.as_view(),
			"get",
			reverse("cms:public-blog-detail", args=["draft-recovery"]),
			slug="draft-recovery",
		)
		self.assertEqual(draft_detail_response.status_code, status.HTTP_404_NOT_FOUND)
