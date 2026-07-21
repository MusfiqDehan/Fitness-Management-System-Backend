"""Unit tests for Traefik custom-domain YAML sync (no Traefik / DB required)."""
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.tenancy.traefik_custom_domains import (
    render_custom_domains_yaml,
    sync_traefik_custom_domains,
)


class RenderYamlTests(SimpleTestCase):
    def test_empty_domains(self):
        yaml = render_custom_domains_yaml([])
        self.assertIn("routers: {}", yaml)
        self.assertIn("AUTO-GENERATED", yaml)

    def test_renders_host_and_cert_resolver(self):
        yaml = render_custom_domains_yaml(["hello-gym.musfiqdehan.com"])
        self.assertIn("Host(`hello-gym.musfiqdehan.com`)", yaml)
        self.assertIn("certResolver: customdomains", yaml)
        self.assertIn("cd-hello-gym-musfiqdehan-com-https:", yaml)
        self.assertIn("cd-hello-gym-musfiqdehan-com-api:", yaml)
        self.assertIn("cd-hello-gym-musfiqdehan-com-ws:", yaml)
        self.assertIn("frontend@docker", yaml)
        self.assertIn("backend@docker", yaml)
        self.assertIn("backend-ws@docker", yaml)
        self.assertIn("redirect-to-https@file", yaml)
        self.assertIn("!PathPrefix(`/.well-known/acme-challenge/`)", yaml)


class SyncTests(SimpleTestCase):
    @override_settings(TRAEFIK_CUSTOM_DOMAINS_PATH="")
    def test_writes_atomic_file(self):
        target = Path(self.get_temp_dir()) / "custom-domains.yml"
        with mock.patch(
            "apps.tenancy.traefik_custom_domains.list_verified_custom_domains",
            return_value=["gym.example.com"],
        ):
            written = sync_traefik_custom_domains(path=target)
        self.assertEqual(written, target)
        text = target.read_text(encoding="utf-8")
        self.assertIn("Host(`gym.example.com`)", text)
        self.assertFalse(list(target.parent.glob(".custom-domains.*.tmp")))

    def get_temp_dir(self) -> str:
        import tempfile

        return tempfile.mkdtemp()
