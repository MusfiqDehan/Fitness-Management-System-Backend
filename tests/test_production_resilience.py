"""Production health and resilience tests."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, SimpleTestCase, override_settings
from django.urls import resolve

from apps.attendance.views import IclockCdataAPIView, IclockGetRequestAPIView


class ReadinessHealthTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_readiness_ok_when_dependencies_available(self):
        response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["database"]["ok"])
        self.assertTrue(payload["checks"]["redis"]["ok"])

    @patch("config.health._check_database", side_effect=RuntimeError("db down"))
    def test_readiness_503_when_database_fails(self, _mock_db):
        response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["checks"]["database"]["ok"])

    @patch("config.health._check_redis", side_effect=RuntimeError("redis down"))
    def test_readiness_503_when_redis_fails(self, _mock_redis):
        response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["checks"]["redis"]["ok"])


class TenantHealthRegressionTests(SimpleTestCase):
    def test_tenant_health_unchanged(self):
        response = Client().get("/api/v1/health/tenant/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("schema_name", payload)
        self.assertIn("scope", payload)


class PgBouncerSettingsTests(SimpleTestCase):
    def test_database_has_conn_max_age(self):
        from django.conf import settings

        self.assertIn("CONN_MAX_AGE", settings.DATABASES["default"])

    def test_pgbouncer_host_in_docker_fallback_list(self):
        # Production compose sets DATABASE_URL host to pgbouncer:6432 and USE_PGBOUNCER=1.
        import os

        enabled = os.environ.get("USE_PGBOUNCER", "").strip().lower() in ("1", "true", "yes", "on")
        if enabled:
            from django.conf import settings

            self.assertEqual(settings.DATABASES["default"].get("CONN_MAX_AGE"), 0)


class AdmsUrlRoutingTests(SimpleTestCase):
    def test_iclock_cdata_resolves_to_view(self):
        match = resolve("/iclock/cdata")
        self.assertEqual(match.func.view_class, IclockCdataAPIView)

    def test_root_cdata_resolves_to_view(self):
        match = resolve("/cdata")
        self.assertEqual(match.func.view_class, IclockCdataAPIView)

    def test_getrequest_resolves_to_view(self):
        match = resolve("/iclock/getrequest")
        self.assertEqual(match.func.view_class, IclockGetRequestAPIView)

    def test_iclock_cdata_accepts_no_trailing_slash(self):
        response = Client().get("/iclock/cdata", {"SN": "UNKNOWN-SN"})
        self.assertIn(response.status_code, {404, 200})
        self.assertNotEqual(response.status_code, 301)


class DrfThrottleCacheTests(SimpleTestCase):
    def test_scoped_throttle_rate_configured(self):
        from django.conf import settings

        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        self.assertIn("tenant_auth", rates)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": "redis://redis:6379/2",
                "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
                "KEY_PREFIX": "gym",
            }
        }
    )
    def test_redis_cache_backend_usable_for_throttles(self):
        cache.set("throttle-probe", 1, 10)
        self.assertEqual(cache.get("throttle-probe"), 1)
