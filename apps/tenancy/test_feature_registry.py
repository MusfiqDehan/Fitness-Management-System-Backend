"""Drift-detection tests for the canonical feature registry.

These tests do NOT need a database — they assert the in-memory registry stays
in sync with the platform module list and the seed_tenant_roles full-access
list. CI catches drift before deploy.
"""
from django.test import SimpleTestCase

from apps.tenancy.constants import (
    PLATFORM_MODULE_EMAIL_SETTINGS,
    PLATFORM_MODULE_KEYS,
    PLATFORM_ROLE_PLATFORM_MANAGER,
    PREDEFINED_PLATFORM_ROLE_PERMISSIONS,
)
from apps.tenancy.feature_registry import (
    PLATFORM_REGISTRY,
    SHARED_FEATURES,
    TENANT_REGISTRY,
    build_api_payload,
    iter_platform_leaf_keys,
    iter_tenant_leaf_keys,
)
from apps.access.management.commands.seed_tenant_roles import (
    FULL_ACCESS_FEATURE_KEYS,
)


class FeatureRegistryConsistencyTests(SimpleTestCase):
    def test_every_platform_registry_key_is_a_known_module(self):
        unknown = [k for k in iter_platform_leaf_keys() if k not in PLATFORM_MODULE_KEYS]
        self.assertEqual(
            unknown,
            [],
            f"PLATFORM_REGISTRY references modules missing from PLATFORM_MODULES: {unknown}",
        )

    def test_every_tenant_registry_key_is_in_full_access_list(self):
        # The frontend will filter sidebar items via hasFeature() against the
        # tenant's enabled features; if a sidebar key isn't in the master list,
        # it could never be granted to anyone.
        unknown = [k for k in iter_tenant_leaf_keys() if k not in FULL_ACCESS_FEATURE_KEYS]
        self.assertEqual(
            unknown,
            [],
            f"TENANT_REGISTRY references features missing from FULL_ACCESS_FEATURE_KEYS: {unknown}",
        )

    def test_shared_features_have_required_fields(self):
        for item in SHARED_FEATURES:
            for field in ("key", "name", "route", "icon"):
                self.assertIn(
                    field,
                    item,
                    f"SHARED_FEATURES entry missing '{field}': {item}",
                )

    def test_api_payload_shape(self):
        payload = build_api_payload()
        self.assertSetEqual(set(payload.keys()), {"platform", "tenant", "shared"})
        for scope in ("platform", "tenant"):
            for group in payload[scope]:
                self.assertIn("group", group)
                self.assertIn("items", group)
                for it in group["items"]:
                    self.assertIn("key", it)
                    self.assertIn("name", it)
                    self.assertTrue(
                        it.get("route"),
                        f"{scope} item {it!r} has empty route in API payload",
                    )

    def test_no_duplicate_routes_within_a_scope(self):
        for scope in ("platform", "tenant"):
            payload = build_api_payload()
            routes = [it["route"] for grp in payload[scope] for it in grp["items"]]
            dupes = [r for r in routes if routes.count(r) > 1]
            self.assertEqual(
                sorted(set(dupes)),
                [],
                f"Duplicate routes in {scope} scope: {dupes}",
            )

    def test_tenant_registry_is_not_empty(self):
        # Sanity guard against accidental wipe.
        self.assertGreater(len(TENANT_REGISTRY), 0)
        self.assertGreater(len(PLATFORM_REGISTRY), 0)

    def test_platform_modules_are_fully_covered_by_registry(self):
        """Bidirectional check: every PLATFORM_MODULES key must be listed in
        PLATFORM_REGISTRY so the platform-team permission matrix shows it.
        """
        missing = [k for k in PLATFORM_MODULE_KEYS if k not in iter_platform_leaf_keys()]
        self.assertEqual(
            missing,
            [],
            f"PLATFORM_MODULES keys not present in PLATFORM_REGISTRY: {missing}",
        )

    def test_full_access_feature_keys_are_fully_covered_by_registry(self):
        """Bidirectional check: every key tenants can be granted should be
        addressable from the sidebar (or explicitly excluded). Keys missing
        from the registry will never appear in the role-permission matrix.
        """
        shared_keys = {it["key"] for it in SHARED_FEATURES}
        covered = set(iter_tenant_leaf_keys()) | shared_keys
        missing = [k for k in FULL_ACCESS_FEATURE_KEYS if k not in covered]
        self.assertEqual(
            missing,
            [],
            f"FULL_ACCESS_FEATURE_KEYS not present in TENANT_REGISTRY or SHARED_FEATURES: {missing}",
        )

    def test_platform_manager_default_can_see_email_settings(self):
        level = PREDEFINED_PLATFORM_ROLE_PERMISSIONS[PLATFORM_ROLE_PLATFORM_MANAGER][
            PLATFORM_MODULE_EMAIL_SETTINGS
        ]
        self.assertIn(
            level,
            {"view", "edit", "full"},
            "Platform manager must have at least view access to platform.email_settings",
        )
