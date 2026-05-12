"""Audit unapplied migrations for schema drift that can break deploys.

Focuses on pre-existing DB objects that would make migrations fail, such as:
- AddField when the column already exists
- CreateModel when the table already exists
- AddIndex/AddConstraint when the name already exists

Examples:
    python manage.py audit_migration_drift
    python manage.py audit_migration_drift --schema public --all-tenants
    python manage.py audit_migration_drift --app membership --fail-on-drift
"""

from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.fields import AddField
from django.db.migrations.operations.models import AddConstraint, AddIndex, CreateModel
from django_tenants.utils import schema_context

from apps.tenancy.models import Tenant


@dataclass
class DriftFinding:
    schema: str
    migration: str
    operation: str
    detail: str


class Command(BaseCommand):
    help = "Audit migration-vs-schema drift for unapplied migrations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to inspect (default: default).",
        )
        parser.add_argument(
            "--schema",
            action="append",
            default=[],
            help="Schema name to inspect. Can be repeated.",
        )
        parser.add_argument(
            "--all-tenants",
            action="store_true",
            default=False,
            help="Inspect all tenant schemas (plus any schemas passed via --schema).",
        )
        parser.add_argument(
            "--app",
            action="append",
            default=[],
            help="Limit checks to specific app label(s). Can be repeated.",
        )
        parser.add_argument(
            "--fail-on-drift",
            action="store_true",
            default=False,
            help="Exit with non-zero status when drift is detected.",
        )

    def handle(self, *args, **options):
        database = options["database"]
        app_filter = {a.strip() for a in options["app"] if a.strip()}

        schemas = set(options["schema"] or [])
        if options["all_tenants"]:
            with schema_context("public"):
                schemas.update(Tenant.objects.values_list("schema_name", flat=True))

        if not schemas:
            connection = connections[database]
            schemas.add(getattr(connection, "schema_name", "public") or "public")

        findings: list[DriftFinding] = []
        for schema_name in sorted(schemas):
            findings.extend(
                self._audit_schema(
                    database=database,
                    schema_name=schema_name,
                    app_filter=app_filter,
                )
            )

        if findings:
            self.stdout.write(self.style.WARNING("Potential migration drift detected:"))
            for f in findings:
                self.stdout.write(
                    f"  - [{f.schema}] {f.migration} :: {f.operation} -> {f.detail}"
                )
            self.stdout.write(
                self.style.WARNING(
                    f"Found {len(findings)} drift issue(s)."
                )
            )
            if options["fail_on_drift"]:
                raise CommandError("Migration drift detected.")
        else:
            self.stdout.write(self.style.SUCCESS("No migration drift found."))

    def _audit_schema(
        self,
        *,
        database: str,
        schema_name: str,
        app_filter: set[str],
    ) -> list[DriftFinding]:
        with schema_context(schema_name):
            connection = connections[database]
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)

            table_names = set(connection.introspection.table_names())
            columns_cache: dict[str, set[str]] = {}
            constraints_cache: dict[str, set[str]] = {}
            findings: list[DriftFinding] = []

            for migration, backwards in plan:
                if backwards:
                    continue
                if app_filter and migration.app_label not in app_filter:
                    continue

                migration_name = f"{migration.app_label}.{migration.name}"
                for op in migration.operations:
                    if isinstance(op, AddField):
                        table = self._table_name(migration.app_label, op.model_name)
                        if table in table_names:
                            cols = self._get_columns(connection, table, columns_cache)
                            if op.name in cols:
                                findings.append(
                                    DriftFinding(
                                        schema=schema_name,
                                        migration=migration_name,
                                        operation="AddField",
                                        detail=(
                                            f"column '{op.name}' already exists in table '{table}'"
                                        ),
                                    )
                                )

                    elif isinstance(op, CreateModel):
                        table = op.options.get("db_table") or f"{migration.app_label}_{op.name.lower()}"
                        if table in table_names:
                            findings.append(
                                DriftFinding(
                                    schema=schema_name,
                                    migration=migration_name,
                                    operation="CreateModel",
                                    detail=f"table '{table}' already exists",
                                )
                            )

                    elif isinstance(op, AddIndex):
                        table = self._table_name(migration.app_label, op.model_name)
                        if table in table_names and op.index.name:
                            constraints = self._get_constraints(connection, table, constraints_cache)
                            if op.index.name in constraints:
                                findings.append(
                                    DriftFinding(
                                        schema=schema_name,
                                        migration=migration_name,
                                        operation="AddIndex",
                                        detail=(
                                            f"index/constraint '{op.index.name}' already exists on '{table}'"
                                        ),
                                    )
                                )

                    elif isinstance(op, AddConstraint):
                        table = self._table_name(migration.app_label, op.model_name)
                        if table in table_names and op.constraint.name:
                            constraints = self._get_constraints(connection, table, constraints_cache)
                            if op.constraint.name in constraints:
                                findings.append(
                                    DriftFinding(
                                        schema=schema_name,
                                        migration=migration_name,
                                        operation="AddConstraint",
                                        detail=(
                                            f"constraint '{op.constraint.name}' already exists on '{table}'"
                                        ),
                                    )
                                )

            return findings

    @staticmethod
    def _table_name(app_label: str, model_name: str) -> str:
        try:
            model = apps.get_model(app_label, model_name)
            return model._meta.db_table
        except LookupError:
            return f"{app_label}_{model_name.lower()}"

    @staticmethod
    def _get_columns(connection, table: str, cache: dict[str, set[str]]) -> set[str]:
        if table not in cache:
            with connection.cursor() as cursor:
                description = connection.introspection.get_table_description(cursor, table)
            cache[table] = {c.name for c in description}
        return cache[table]

    @staticmethod
    def _get_constraints(connection, table: str, cache: dict[str, set[str]]) -> set[str]:
        if table not in cache:
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(cursor, table)
            cache[table] = set(constraints.keys())
        return cache[table]
