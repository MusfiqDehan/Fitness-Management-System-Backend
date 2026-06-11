"""Tests for Redis cache infrastructure and hot-path caching."""

from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.tenancy.services import tenant_has_feature
from utils import cache_helpers
from utils.timezone_middleware import TimezoneMiddleware


class CacheKeyHelperTests(SimpleTestCase):
    def test_tenant_scoped_keys_include_identifiers(self):
        self.assertEqual(cache_helpers.tenant_feature_key(42), "tff:42:enabled_keys")
        self.assertEqual(
            cache_helpers.permission_map_key("tenant_a", 7),
            "perm:tenant_a:7:map",
        )
        self.assertEqual(
            cache_helpers.public_branches_key("tenant_a", minimal=True, homepage=True),
            "tenant:tenant_a:branches:minimal:homepage",
        )

    def test_access_me_key_includes_version(self):
        cache.clear()
        cache_helpers.bump_tenant_access_me_version("tenant_a")
        key = cache_helpers.access_me_key("tenant_a", 5)
        self.assertTrue(key.endswith(":v1"))


class CacheBackendSelectionTests(SimpleTestCase):
    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "cache-backend-test",
            }
        }
    )
    def test_locmem_backend_is_usable(self):
        cache.set("probe", "ok", 30)
        self.assertEqual(cache.get("probe"), "ok")


class TenantFeatureCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = SimpleNamespace(id=99, schema_name="cache_feature_test")

    def test_tenant_has_feature_uses_cache(self):
        with patch(
            "apps.tenancy.services._load_tenant_enabled_feature_keys",
            return_value={"members"},
        ) as loader:
            self.assertTrue(tenant_has_feature(self.tenant, "members"))
            self.assertTrue(tenant_has_feature(self.tenant, "members"))
            loader.assert_called_once()

    def test_invalidate_tenant_features_forces_reload(self):
        with patch(
            "apps.tenancy.services._load_tenant_enabled_feature_keys",
            return_value={"members"},
        ) as loader:
            self.assertTrue(tenant_has_feature(self.tenant, "members"))
            loader.reset_mock()
            with patch("apps.tenancy.models.Tenant.objects.filter") as tenant_filter:
                tenant_filter.return_value.values_list.return_value.first.return_value = (
                    "cache_feature_test"
                )
                cache_helpers.invalidate_tenant_features(self.tenant.id)
            self.assertTrue(tenant_has_feature(self.tenant, "members"))
            loader.assert_called_once()


class TimezoneMiddlewareCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.middleware = TimezoneMiddleware(get_response=lambda request: None)

    def test_timezone_resolution_is_cached(self):
        tenant = SimpleNamespace(schema_name="tenant_tz", timezone="Asia/Dhaka")
        with patch("utils.timezone_middleware.connection") as mock_connection:
            mock_connection.tenant = tenant
            with patch.object(
                TimezoneMiddleware,
                "_compute_timezone",
                return_value="Asia/Dhaka",
            ) as compute:
                first = self.middleware._resolve_timezone()
                second = self.middleware._resolve_timezone()
                self.assertEqual(first, "Asia/Dhaka")
                self.assertEqual(second, "Asia/Dhaka")
                compute.assert_called_once()


class PublicPackageCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_public_packages_key_roundtrip(self):
        cache_helpers.invalidate_public_packages()
        sentinel = [{"slug": "starter"}]
        cache.set(cache_helpers.public_packages_key(), sentinel, 60)
        self.assertEqual(cache.get(cache_helpers.public_packages_key()), sentinel)


class StatsScopeTokenTests(SimpleTestCase):
    def test_admin_and_branch_manager_do_not_share_scope(self):
        admin = SimpleNamespace(
            id=1,
            is_authenticated=True,
            is_superuser=False,
            is_staff=True,
            role="admin",
        )
        branch_manager = SimpleNamespace(
            id=2,
            is_authenticated=True,
            is_superuser=False,
            is_staff=False,
            role="staff",
        )
        with patch(
            "utils.tenancy_helpers.get_branch_manager_scope_ids",
            return_value=[10, 12],
        ):
            admin_scope = cache_helpers.stats_scope_token(admin, None)
            manager_scope = cache_helpers.stats_scope_token(branch_manager, None)
        self.assertEqual(admin_scope, "admin:all")
        self.assertEqual(manager_scope, "bm:2:10,12:all")
        self.assertNotEqual(admin_scope, manager_scope)


class CacheSmokeTests(SimpleTestCase):
    def test_public_branch_cache_invalidates_on_signal_helper(self):
        cache.clear()
        schema = "tenant_smoke"
        payload = [{"id": 1, "name": "Main"}]
        cache.set(
            cache_helpers.public_branches_key(schema, minimal=False, homepage=False),
            payload,
            600,
        )
        cache_helpers.invalidate_public_branches(schema)
        self.assertIsNone(
            cache.get(cache_helpers.public_branches_key(schema, minimal=False, homepage=False))
        )

    def test_permission_invalidation_clears_cached_map(self):
        cache.clear()
        schema = "tenant_smoke"
        user_id = 42
        cache.set(cache_helpers.permission_map_key(schema, user_id), {"members": "view"}, 300)
        cache_helpers.invalidate_user_permissions(schema, user_id)
        self.assertIsNone(cache.get(cache_helpers.permission_map_key(schema, user_id)))


class AuthCacheIntegrationTests(SimpleTestCase):
    def test_brute_force_counter_uses_default_cache(self):
        cache.clear()
        cache_key = "tenant-auth-fail:test@example.com"
        cache.set(cache_key, 2, 900)
        self.assertEqual(cache.get(cache_key), 2)
        cache.delete(cache_key)
        self.assertIsNone(cache.get(cache_key))

    def test_drf_scoped_throttle_rate_is_configured(self):
        self.assertIn("tenant_auth", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
