"""Sync the canonical TENANT_REGISTRY into the public-schema `Feature` table.

Idempotent. Run on every deploy:

    python manage.py sync_features

What it does:
  * For every key in `TENANT_REGISTRY` + `SHARED_FEATURES`, upsert a Feature row
    in the public schema.
  * The first registry entry to mention a key wins for `name` / `sort_order`.
  * Keys that no longer exist in the registry are NOT deleted unless --prune is
    passed.  Without --prune they are flagged via stdout so an operator can decide.
  * Pass --prune to delete orphaned Feature rows (and their TenantFeatureFlag
    children via ON DELETE CASCADE) instead of just warning.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context

from apps.tenancy.feature_registry import (
    SHARED_FEATURES,
    TENANT_REGISTRY,
)
from apps.tenancy.models import Feature


class Command(BaseCommand):
    help = "Upsert tenant Feature rows from the canonical feature registry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prune",
            action="store_true",
            default=False,
            help="Delete Feature rows whose key is no longer in the registry.",
        )

    def handle(self, *args, **options):
        prune = options["prune"]
        sort_order = 0
        seen_keys: set[str] = set()
        with schema_context("public"), transaction.atomic():
            for group in TENANT_REGISTRY:
                group_label = group.get("group", "")
                for item in group.get("children", []):
                    key = item["key"]
                    if key in seen_keys:
                        sort_order += 1
                        continue
                    seen_keys.add(key)
                    sort_order += 1
                    obj, created = Feature.objects.update_or_create(
                        key=key,
                        defaults={
                            "name": item["name"],
                            "description": group_label,
                            "sort_order": sort_order,
                            "is_system": True,
                        },
                    )
                    self.stdout.write(
                        ("+ " if created else "= ") + f"{key} ({item['name']})"
                    )
            for item in SHARED_FEATURES:
                key = item["key"]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                sort_order += 1
                obj, created = Feature.objects.update_or_create(
                    key=key,
                    defaults={
                        "name": item["name"],
                        "description": "Shared",
                        "sort_order": sort_order,
                        "is_system": True,
                    },
                )
                self.stdout.write(
                    ("+ " if created else "= ") + f"{key} ({item['name']}) [shared]"
                )

            # Detect (and optionally delete) orphans.
            orphan_qs = Feature.objects.exclude(key__in=seen_keys)
            for orphan in orphan_qs:
                if prune:
                    self.stdout.write(
                        self.style.WARNING(
                            f"- pruned orphan: '{orphan.key}' deleted from DB"
                        )
                    )
                    orphan.delete()
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"! orphan: '{orphan.key}' is in DB but missing from registry"
                            " (run with --prune to delete)"
                        )
                    )
        self.stdout.write(self.style.SUCCESS(f"Synced {len(seen_keys)} feature(s)."))
