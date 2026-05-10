"""Seed core feature catalog and the three default packages.

Defines the canonical feature keys the platform supports and creates
Trial / Starter / Enterprise packages that map to them. Idempotent.
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


# Top-level feature keys (mirrored in apps.access for tenant RBAC)
CORE_FEATURES = [
    # key, name, parent_key
    ("dashboard", "Dashboard", None),
    ("members", "Members", None),
    ("members.attendance", "Member Attendance", "members"),
    ("members.packages", "Member Packages", "members"),
    ("instructors", "Instructors", None),
    ("classes", "Classes & Schedule", None),
    ("classes.bookings", "Class Bookings", "classes"),
    ("payments", "Payments & Billing", None),
    ("payments.invoices", "Invoices", "payments"),
    ("crm.contacts", "Contacts", None),
    ("crm.inquiries", "Inquiries", None),
    ("cms.banners", "Banners", None),
    ("cms.blogs", "Blog Posts", None),
    ("clubs", "Gym Clubs / Branches", None),
    ("reports", "Reports & Analytics", None),
    ("reminders", "Reminders & Notifications", None),
    ("settings", "Settings", None),
    ("permissions", "Roles & Permissions", None),
]


PACKAGES = {
    "trial": {
        "name": "Free Trial",
        "description": "7-day full-feature trial. Convert to a paid plan to keep your data flowing.",
        "price_monthly": Decimal("0.00"),
        "price_yearly": Decimal("0.00"),
        "max_users": 5,
        "max_branches": 1,
        "trial_days": 7,
        "is_public": True,
        "highlight": False,
        "sort_order": 1,
        "features": [
            "dashboard", "members", "members.attendance", "members.packages",
            "instructors", "classes", "classes.bookings",
            "payments", "crm.contacts", "crm.inquiries",
            "reminders", "settings",
        ],
    },
    "starter": {
        "name": "Starter",
        "description": "For growing studios — full member management plus marketing tools.",
        "price_monthly": Decimal("29.00"),
        "price_yearly": Decimal("290.00"),
        "max_users": 25,
        "max_branches": 1,
        "trial_days": 0,
        "is_public": True,
        "highlight": True,
        "sort_order": 2,
        "features": [
            "dashboard", "members", "members.attendance", "members.packages",
            "instructors", "classes", "classes.bookings",
            "payments", "payments.invoices",
            "crm.contacts", "crm.inquiries",
            "cms.banners", "cms.blogs",
            "reports", "reminders", "settings", "permissions",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "description": "Multi-branch chains with full RBAC, advanced reports, and priority support.",
        "price_monthly": Decimal("99.00"),
        "price_yearly": Decimal("990.00"),
        "max_users": 0,  # unlimited
        "max_branches": 0,  # unlimited
        "trial_days": 0,
        "is_public": True,
        "highlight": False,
        "sort_order": 3,
        "features": [k for k, _, _ in CORE_FEATURES],  # everything
    },
}


class Command(BaseCommand):
    help = "Seed core features and Trial/Starter/Enterprise packages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--resync-tenants",
            action="store_true",
            help="Also re-sync feature flags for all existing tenants.",
        )

    def handle(self, *args, **options):
        with schema_context("public"), transaction.atomic():
            self._seed_features()
            self._seed_packages()
        if options.get("resync_tenants"):
            self._resync_tenants()
        self.stdout.write(self.style.SUCCESS("Features & packages seeded."))

    def _seed_features(self):
        # First pass: create roots without parents
        existing = {f.key: f for f in Feature.objects.all()}
        for sort, (key, name, parent_key) in enumerate(CORE_FEATURES):
            f = existing.get(key)
            if f is None:
                f = Feature.objects.create(
                    key=key, name=name, sort_order=sort * 10,
                    is_system=True,
                )
                self.stdout.write(f"  Created feature: {key}")
                existing[key] = f
        # Second pass: link parents
        for key, _, parent_key in CORE_FEATURES:
            if not parent_key:
                continue
            f = existing[key]
            parent = existing.get(parent_key)
            if parent and f.parent_id != parent.id:
                f.parent = parent
                f.save(update_fields=["parent"])

    def _seed_packages(self):
        for slug, info in PACKAGES.items():
            pkg, created = PlatformPackage.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": info["name"],
                    "description": info["description"],
                    "price_monthly": info["price_monthly"],
                    "price_yearly": info["price_yearly"],
                    "max_users": info["max_users"],
                    "max_branches": info["max_branches"],
                    "trial_days": info["trial_days"],
                    "is_active": True,
                    "is_public": info["is_public"],
                    "highlight": info["highlight"],
                    "sort_order": info["sort_order"],
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created package: {slug}"))
            # Map features
            wanted_keys = set(info["features"])
            features = {
                f.key: f for f in Feature.objects.filter(key__in=wanted_keys)
            }
            existing_pf = {
                pf.feature.key: pf
                for pf in PlatformPackageFeature.objects.filter(package=pkg).select_related("feature")
            }
            for key in wanted_keys:
                f = features.get(key)
                if not f:
                    continue
                pf = existing_pf.get(key)
                if pf is None:
                    PlatformPackageFeature.objects.create(
                        package=pkg, feature=f, is_enabled=True
                    )
                elif not pf.is_enabled:
                    pf.is_enabled = True
                    pf.save(update_fields=["is_enabled"])
            for key, pf in existing_pf.items():
                if key not in wanted_keys and pf.is_enabled:
                    pf.is_enabled = False
                    pf.save(update_fields=["is_enabled"])

    def _resync_tenants(self):
        with schema_context("public"):
            tenants = list(Tenant.objects.order_by("schema_name"))
        if not tenants:
            self.stdout.write("No tenants to re-sync.")
            return
        for tenant in tenants:
            with schema_context("public"):
                summary = sync_tenant_features(tenant)
            self.stdout.write(
                f"  resynced {tenant.schema_name} (plan={tenant.plan}): "
                f"+{summary['added']} kept={summary['kept']} "
                f"graced={summary['graced']} revoked={summary['revoked']}"
            )
