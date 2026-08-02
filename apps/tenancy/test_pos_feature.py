"""Registry drift coverage for the `pos` tenant feature.

Subclasses the canonical consistency suite so every base invariant re-runs
alongside the POS-specific assertions.
"""
from apps.tenancy.test_feature_registry import FeatureRegistryConsistencyTests


class FeatureRegistryPosTests(FeatureRegistryConsistencyTests):
    def test_pos_key_in_registry_and_role_seed(self):
        from apps.access.management.commands.seed_tenant_roles import FULL_ACCESS_FEATURE_KEYS
        from apps.tenancy.feature_registry import iter_tenant_leaf_keys

        self.assertIn("pos", FULL_ACCESS_FEATURE_KEYS)
        self.assertIn("pos", iter_tenant_leaf_keys())

    def test_pos_in_platform_package_seed(self):
        from apps.tenancy.management.commands.seed_platform_packages import CORE_FEATURES, PACKAGES

        core_keys = {key for key, _, _ in CORE_FEATURES}
        self.assertIn("pos", core_keys)
        # POS is core counter functionality, not an upsell tier.
        for slug in ("starter", "growth", "enterprise"):
            self.assertIn("pos", PACKAGES[slug]["features"])

    def test_pos_is_a_flat_top_level_key(self):
        """Dotted keys render as indented sub-permissions in the platform
        feature panel. POS is a top-level surface, so the key must stay flat
        and must not be declared with a parent in CORE_FEATURES."""
        from apps.tenancy.management.commands.seed_platform_packages import CORE_FEATURES

        self.assertNotIn(".", "pos")
        parents = {key: parent for key, _, parent in CORE_FEATURES}
        self.assertIsNone(parents["pos"])

    def test_pos_ships_a_sidebar_route(self):
        from apps.tenancy.feature_registry import build_api_payload

        finance = next(
            group for group in build_api_payload()["tenant"] if group["group"] == "Finance"
        )
        pos = next(item for item in finance["items"] if item["key"] == "pos")
        self.assertEqual(pos["route"], "/pos")
        self.assertEqual(pos["name"], "POS")
        self.assertEqual(pos["icon"], "ShoppingCart")

    def test_manager_role_can_operate_the_till(self):
        """POS checkout goes through the payment API, so a role granted `pos`
        is only useful if it also has `payments` at edit."""
        from apps.access.management.commands.seed_tenant_roles import PREDEFINED_TENANT_ROLES

        for slug, info in PREDEFINED_TENANT_ROLES.items():
            permissions = info["permissions"]
            if permissions == "FULL_ACCESS" or "pos" not in permissions:
                continue
            self.assertEqual(
                permissions.get("payments"),
                "edit",
                f"role '{slug}' grants pos but cannot create payments",
            )
