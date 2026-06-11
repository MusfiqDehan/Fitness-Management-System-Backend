"""Shared helpers for query-count regression tests in tenant schemas."""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django_tenants.utils import schema_context

from apps.tenancy.models import Domain, Feature, Tenant, TenantFeatureFlag


class TenantQueryTestMixin:
    """Mixin for tests that exercise list endpoints inside a tenant schema."""

    SCHEMA_NAME = "tenant_query_opt_test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with schema_context("public"):
            Tenant.objects.filter(schema_name=cls.SCHEMA_NAME).delete()
            with connection.cursor() as cursor:
                cursor.execute(
                    'DROP SCHEMA IF EXISTS "%s" CASCADE' % cls.SCHEMA_NAME
                )
            cls.tenant = Tenant.objects.create(
                schema_name=cls.SCHEMA_NAME,
                name="Query Opt Tenant",
                slug="query-opt-tenant",
                code="QUERYOPT",
                owner_email="owner@queryopt.test",
                billing_email="owner@queryopt.test",
                status="active",
                is_trial=False,
            )
            Domain.objects.create(
                domain="queryopt.localhost",
                tenant=cls.tenant,
                is_primary=True,
            )

    @classmethod
    def tearDownClass(cls):
        connection.set_schema_to_public()
        super().tearDownClass()
        with schema_context("public"):
            tenant = Tenant.objects.filter(schema_name=cls.SCHEMA_NAME).first()
            if tenant is not None:
                tenant.delete(force_drop=True)
            with connection.cursor() as cursor:
                cursor.execute(
                    'DROP SCHEMA IF EXISTS "%s" CASCADE' % cls.SCHEMA_NAME
                )

    def setUp(self):
        connection.set_tenant(self.tenant)

    def tearDown(self):
        connection.set_schema_to_public()

    @staticmethod
    def enable_feature(tenant, feature_key: str):
        with schema_context("public"):
            feature, _ = Feature.objects.get_or_create(
                key=feature_key,
                defaults={"name": feature_key, "sort_order": 0},
            )
            TenantFeatureFlag.objects.update_or_create(
                tenant=tenant,
                feature=feature,
                defaults={
                    "is_enabled": True,
                    "source": TenantFeatureFlag.SOURCE_OVERRIDE,
                },
            )

    @staticmethod
    def assert_query_count_bounded(callable_fn, max_queries: int):
        with CaptureQueriesContext(connection) as context:
            callable_fn()
        assert len(context) <= max_queries, (
            f"Expected at most {max_queries} queries, got {len(context)}"
        )
