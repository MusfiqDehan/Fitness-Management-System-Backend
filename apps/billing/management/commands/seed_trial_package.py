"""Idempotently seed the default Trial package and its features.

Mirrors the sidebar entries the user expects to see immediately after
accepting a tenant invitation:
  Overview, Attendance, Reports, Members Overview, All Members,
  Payments, Packages, Reminders, Schedule, Instructors, Settings.

Run on every deploy from `entrypoint.sh` after `sync_features` so the
referenced Feature rows already exist.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context

from apps.tenancy.models import (
    Feature,
    PlatformPackage,
    PlatformPackageFeature,
    Tenant,
)
from apps.tenancy.services import sync_tenant_features


# Sidebar label  →  feature key
TRIAL_FEATURE_KEYS = [
    "dashboard",            # Overview
    "members.attendance",   # Attendance
    "reports",              # Reports
    "members",              # Members Overview + All Members
    "payments",             # Payments
    "members.packages",     # Packages
    "reminders",            # Reminders
    "classes",              # Schedule
    "instructors",          # Instructors
    "settings",             # Settings
]

TRIAL_DEFAULTS = {
    "name": "Free Trial",
    "description": (
        "7-day trial with the essentials: members, attendance, payments, "
        "schedule and reports."
    ),
    "price_monthly": Decimal("0.00"),
    "price_yearly": Decimal("0.00"),
    "max_users": 5,
    "max_branches": 1,
    "trial_days": 7,
    "is_active": True,
    "is_public": True,
    "sort_order": 1,
    "highlight": False,
}


class Command(BaseCommand):
    help = "Create / refresh the 'trial' platform package with its default features."

    def add_arguments(self, parser):
        parser.add_argument(
            "--resync-tenants",
            action="store_true",
            help="Also re-sync feature flags for existing tenants on the trial plan.",
        )

    def handle(self, *args, **options):
        with schema_context("public"), transaction.atomic():
            package, created = PlatformPackage.objects.update_or_create(
                slug="trial",
                defaults=TRIAL_DEFAULTS,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Created' if created else 'Updated'} package 'trial' (id={package.id})."
                )
            )

            features = {
                f.key: f for f in Feature.objects.filter(key__in=TRIAL_FEATURE_KEYS)
            }
            missing = [k for k in TRIAL_FEATURE_KEYS if k not in features]
            if missing:
                self.stdout.write(
                    self.style.WARNING(
                        "Skipping unknown feature keys (run sync_features first): "
                        + ", ".join(missing)
                    )
                )

            wanted_ids = {features[k].id for k in TRIAL_FEATURE_KEYS if k in features}
            existing = {
                pf.feature_id: pf
                for pf in PlatformPackageFeature.objects.filter(package=package)
            }

            added = re_enabled = disabled = 0
            for fid in wanted_ids:
                pf = existing.get(fid)
                if pf is None:
                    PlatformPackageFeature.objects.create(
                        package=package, feature_id=fid, is_enabled=True
                    )
                    added += 1
                elif not pf.is_enabled:
                    pf.is_enabled = True
                    pf.save(update_fields=["is_enabled"])
                    re_enabled += 1
            for fid, pf in existing.items():
                if fid not in wanted_ids and pf.is_enabled:
                    pf.is_enabled = False
                    pf.save(update_fields=["is_enabled"])
                    disabled += 1

            self.stdout.write(
                f"  features: +{added} added, {re_enabled} re-enabled, "
                f"{disabled} disabled, total enabled={len(wanted_ids)}"
            )

        if options.get("resync_tenants"):
            self._resync_trial_tenants()

        self.stdout.write(self.style.SUCCESS("Trial package seed complete."))

    def _resync_trial_tenants(self):
        with schema_context("public"):
            # Include plan="free" tenants — "free" is a legacy alias for "trial"
            # created before the billing system was introduced.
            trial_tenants = list(Tenant.objects.filter(plan__in=["trial", "free"]))
        if not trial_tenants:
            self.stdout.write("No trial/free tenants to re-sync.")
            return
        for tenant in trial_tenants:
            with schema_context("public"):
                summary = sync_tenant_features(tenant)
            self.stdout.write(
                f"  resynced {tenant.schema_name} (plan={tenant.plan}): "
                f"+{summary['added']} kept={summary['kept']} "
                f"graced={summary['graced']} revoked={summary['revoked']}"
            )
