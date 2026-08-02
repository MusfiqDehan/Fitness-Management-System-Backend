"""Repair shared-schema apps whose migrations are recorded but tables are missing.

This happens when an app was previously TENANT-only (or otherwise recorded in
``public.django_migrations`` without creating public tables), then later added
to ``SHARED_APPS``. ``migrate_schemas --shared`` then no-ops because Django
believes the migrations are already applied.

Examples:
    python manage.py repair_shared_schema_drift
    python manage.py repair_shared_schema_drift --app cms
    python manage.py repair_shared_schema_drift --dry-run
"""

from __future__ import annotations

from django.apps import AppConfig, apps as django_apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context


class Command(BaseCommand):
    help = (
        "Detect and repair SHARED_APPS with applied migration history but "
        "missing tables on the public schema."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            action="append",
            default=[],
            dest="apps",
            help="Limit repair to specific app label(s). Can be repeated.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report drift only; do not rewrite migration history or tables.",
        )

    def handle(self, *args, **options):
        app_filter = {a.strip() for a in options["apps"] if a.strip()}
        dry_run = options["dry_run"]
        public_schema = get_public_schema_name()

        shared_labels = self._shared_app_labels()
        if app_filter:
            shared_labels = [label for label in shared_labels if label in app_filter]

        repaired: list[str] = []
        with schema_context(public_schema):
            existing_tables = set(connection.introspection.table_names())
            for app_label in shared_labels:
                expected = self._expected_tables(app_label)
                if not expected:
                    continue
                if not self._has_applied_migrations(app_label):
                    continue
                missing = sorted(expected - existing_tables)
                if not missing:
                    continue

                self.stdout.write(
                    self.style.WARNING(
                        f"[{public_schema}] {app_label}: migrations applied but "
                        f"missing tables: {', '.join(missing)}"
                    )
                )
                if dry_run:
                    continue

                self.stdout.write(f"Repairing shared app '{app_label}'...")
                call_command(
                    "migrate_schemas",
                    app_label,
                    "zero",
                    shared=True,
                    fake=True,
                    verbosity=1,
                )
                call_command(
                    "migrate_schemas",
                    app_label,
                    shared=True,
                    interactive=False,
                    verbosity=1,
                )
                repaired.append(app_label)
                existing_tables = set(connection.introspection.table_names())

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete; no changes made."))
            return

        if repaired:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Repaired shared schema drift for: {', '.join(repaired)}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("No shared schema drift to repair.")
            )

    @staticmethod
    def _shared_app_labels() -> list[str]:
        labels: list[str] = []
        for entry in settings.SHARED_APPS:
            try:
                config = AppConfig.create(entry)
            except Exception:
                continue
            label = getattr(config, "label", None) or config.name.split(".")[-1]
            if label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _expected_tables(app_label: str) -> set[str]:
        tables: set[str] = set()
        try:
            app_config = django_apps.get_app_config(app_label)
        except LookupError:
            return tables
        for model in app_config.get_models():
            if model._meta.proxy or model._meta.auto_created:
                continue
            tables.add(model._meta.db_table)
        return tables

    @staticmethod
    def _has_applied_migrations(app_label: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM django_migrations WHERE app = %s LIMIT 1",
                [app_label],
            )
            return cursor.fetchone() is not None
