"""Unit tests for tenant custom-domain self-service.

These cover the security-critical pieces without requiring a tenant database:
- domain syntax / reservation validation
- DNS TXT verification result handling (resolver mocked)
- the effective-enablement gating formula (model lookups mocked)
"""
from unittest import mock

from django.test import SimpleTestCase

from apps.dashboard.custom_domain_views import _validate_domain
from apps.tenancy.dns_verification import (
    generate_verification_token,
    verify_txt_record,
)


class DomainValidationTests(SimpleTestCase):
    def test_accepts_subdomain(self):
        domain, error = _validate_domain("Gym.YourCompany.com")
        self.assertEqual(error, "")
        self.assertEqual(domain, "gym.yourcompany.com")

    def test_strips_trailing_dot(self):
        domain, error = _validate_domain("gym.example.com.")
        self.assertEqual(error, "")
        self.assertEqual(domain, "gym.example.com")

    def test_rejects_scheme(self):
        _, error = _validate_domain("https://gym.example.com")
        self.assertNotEqual(error, "")

    def test_rejects_path(self):
        _, error = _validate_domain("gym.example.com/login")
        self.assertNotEqual(error, "")

    def test_rejects_blank(self):
        _, error = _validate_domain("   ")
        self.assertNotEqual(error, "")

    def test_rejects_platform_domain(self):
        _, error = _validate_domain("acme.fitssort.com")
        self.assertNotEqual(error, "")

    def test_accepts_apex_domain(self):
        domain, error = _validate_domain("yourcompany.com")
        self.assertEqual(error, "")
        self.assertEqual(domain, "yourcompany.com")

    def test_relative_txt_host(self):
        from apps.dashboard.custom_domain_views import _relative_txt_host

        self.assertEqual(_relative_txt_host("example.com"), "_fitssort-verify")
        self.assertEqual(
            _relative_txt_host("hello-gym.musfiqdehan.com"),
            "_fitssort-verify.hello-gym",
        )

    def test_rejects_bare_tld(self):
        _, error = _validate_domain("localhost")
        self.assertNotEqual(error, "")


class TokenTests(SimpleTestCase):
    def test_token_is_unique_and_long(self):
        a = generate_verification_token()
        b = generate_verification_token()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 32)


def _fake_answer(value: str):
    rdata = mock.Mock()
    rdata.strings = [value.encode("utf-8")]
    return rdata


class DnsVerificationTests(SimpleTestCase):
    def _patch_resolver(self, *, answers=None, exc=None):
        resolver = mock.Mock()
        if exc is not None:
            resolver.resolve.side_effect = exc
        else:
            resolver.resolve.return_value = answers or []
        return mock.patch(
            "apps.tenancy.dns_verification.dns.resolver.Resolver",
            return_value=resolver,
        )

    def test_matching_token_succeeds(self):
        token = "abc123"
        with self._patch_resolver(answers=[_fake_answer(token)]):
            ok, error = verify_txt_record("_fitssort-verify.gym.example.com", token)
        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_mismatched_token_fails(self):
        with self._patch_resolver(answers=[_fake_answer("wrong-value")]):
            ok, error = verify_txt_record("_fitssort-verify.gym.example.com", "abc123")
        self.assertFalse(ok)
        self.assertNotEqual(error, "")

    def test_missing_record_fails_gracefully(self):
        import dns.resolver

        with self._patch_resolver(exc=dns.resolver.NXDOMAIN()):
            ok, error = verify_txt_record("_fitssort-verify.gym.example.com", "abc123")
        self.assertFalse(ok)
        self.assertNotEqual(error, "")

    def test_empty_token_rejected(self):
        ok, error = verify_txt_record("_fitssort-verify.gym.example.com", "")
        self.assertFalse(ok)
        self.assertNotEqual(error, "")


class RoutingCheckTests(SimpleTestCase):
    def _patch_resolver(self, *, cname=None, a=None, cname_exc=None, a_exc=None):
        resolver = mock.Mock()

        def _resolve(name, rdtype, *args, **kwargs):
            if rdtype == "CNAME":
                if cname_exc is not None:
                    raise cname_exc
                answers = []
                if cname is not None:
                    rdata = mock.Mock()
                    rdata.target = cname
                    answers = [rdata]
                return answers
            if rdtype == "A":
                if a_exc is not None:
                    raise a_exc
                answers = []
                if a is not None:
                    rdata = mock.Mock()
                    rdata.__str__ = mock.Mock(return_value=str(a))
                    answers = [rdata]
                return answers
            raise AssertionError(f"Unexpected rdtype {rdtype}")

        resolver.resolve.side_effect = _resolve
        return mock.patch(
            "apps.tenancy.dns_verification.dns.resolver.Resolver",
            return_value=resolver,
        )

    def test_cname_match_is_ready(self):
        from apps.tenancy.dns_verification import check_domain_routing

        with self._patch_resolver(cname="fitssort.com."):
            ok, error = check_domain_routing(
                "gym.example.com", cname_target="fitssort.com", a_target="1.2.3.4"
            )
        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_a_match_is_ready(self):
        from apps.tenancy.dns_verification import check_domain_routing
        import dns.resolver

        with self._patch_resolver(cname_exc=dns.resolver.NoAnswer(), a="185.202.223.12"):
            ok, error = check_domain_routing(
                "gym.example.com",
                cname_target="fitssort.com",
                a_target="185.202.223.12",
            )
        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_missing_routing_is_advisory(self):
        from apps.tenancy.dns_verification import check_domain_routing
        import dns.resolver

        with self._patch_resolver(
            cname_exc=dns.resolver.NXDOMAIN(),
            a_exc=dns.resolver.NXDOMAIN(),
        ):
            ok, error = check_domain_routing(
                "gym.example.com",
                cname_target="fitssort.com",
                a_target="185.202.223.12",
            )
        self.assertFalse(ok)
        self.assertIn("does not point", error)


class EffectiveEnablementTests(SimpleTestCase):
    """Exercise the three-way gate with all model lookups mocked."""

    def _run(self, *, tenant_enabled, global_enabled, settings_exists=True,
             feature_exists=False, flag_enabled=False):
        from apps.tenancy import services

        tenant = mock.Mock()
        tenant.custom_domain_enabled = tenant_enabled

        settings_row = None
        if settings_exists:
            settings_row = mock.Mock()
            settings_row.enable_custom_domains = global_enabled

        settings_qs = mock.Mock()
        settings_qs.filter.return_value.first.return_value = settings_row

        feature_qs = mock.Mock()
        feature_qs.filter.return_value.exists.return_value = feature_exists

        with mock.patch("apps.tenancy.models.PlatformSettings") as ps, \
                mock.patch("apps.tenancy.models.Feature") as feat, \
                mock.patch.object(services, "tenant_has_feature", return_value=flag_enabled):
            ps.objects = settings_qs
            feat.objects = feature_qs
            return services.custom_domain_effectively_enabled(tenant)

    def test_all_off(self):
        self.assertFalse(self._run(tenant_enabled=False, global_enabled=False))

    def test_tenant_off_global_on(self):
        self.assertFalse(self._run(tenant_enabled=False, global_enabled=True))

    def test_tenant_on_global_off(self):
        self.assertFalse(self._run(tenant_enabled=True, global_enabled=False))

    def test_no_settings_row_is_off(self):
        self.assertFalse(
            self._run(tenant_enabled=True, global_enabled=True, settings_exists=False)
        )

    def test_both_on_no_feature_is_enabled(self):
        self.assertTrue(
            self._run(tenant_enabled=True, global_enabled=True, feature_exists=False)
        )

    def test_both_on_feature_exists_flag_off(self):
        self.assertFalse(
            self._run(
                tenant_enabled=True, global_enabled=True,
                feature_exists=True, flag_enabled=False,
            )
        )

    def test_both_on_feature_exists_flag_on(self):
        self.assertTrue(
            self._run(
                tenant_enabled=True, global_enabled=True,
                feature_exists=True, flag_enabled=True,
            )
        )

    def test_none_tenant_is_off(self):
        from apps.tenancy import services

        self.assertFalse(services.custom_domain_effectively_enabled(None))
