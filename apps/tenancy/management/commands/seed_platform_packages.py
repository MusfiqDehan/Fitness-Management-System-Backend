"""Seed core feature catalog and the three default packages.

Defines the canonical feature keys the platform supports and creates
Starter / Growth / Enterprise packages that map to them. Idempotent.
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
    ("attendance.devices", "Access Devices", None),
    ("attendance.access_gate", "Access Gate", "attendance.devices"),
    ("attendance.fingerprints", "Fingerprint Linking", "attendance.devices"),
    ("attendance.iclock", "iClock Ingestion", "attendance.devices"),
    ("instructors", "Instructors", None),
    ("classes", "Classes & Schedule", None),
    ("classes.bookings", "Class Bookings", "classes"),
    ("payments", "Payments & Billing", None),
    ("payments.invoices", "Invoices", "payments"),
    ("payments.gateways", "Payment Gateways", "payments"),
    ("subscriptions", "Subscriptions", None),
    ("crm.contacts", "Contacts", None),
    ("crm.inquiries", "Inquiries", None),
    ("cms.banners", "Banners", None),
    ("cms.blogs", "Blog Posts", None),
    ("branches", "Gym Branches", None),
    ("reports", "Reports & Analytics", None),
    ("reminders", "Reminders & Notifications", None),
    ("settings", "Settings", None),
    ("permissions", "Roles & Permissions", None),
    # Gated capability without a sidebar entry (controls custom-domain self-service).
    ("email_config", "Email Config", None),
    ("public_website", "Landing Page Setup", None),
    ("custom_domain", "Custom Domain", None),
]


PACKAGES = {
    "starter": {
        "name": "Starter",
        "description": "Only dashboard management system",
        "price_monthly": Decimal("2490.00"),
        "price_yearly": Decimal("23904.00"),  # 2490 * 12 * 0.80
        "max_users": 175,
        "max_branches": 1,
        "max_members_per_branch": 175,
        "max_trainers_per_branch": 10,
        "max_employees_per_branch": 10,
        "trial_days": 14,
        "is_public": True,
        "highlight": False,
        "sort_order": 1,
        "badge_label": "14 Days Free Trial",
        "cta_label": "Try for Free",
        "cta_url": "/register",
        "setup_fee": "Tk. 9,990",
        "original_setup_fee": "",
        "original_price_monthly": Decimal("3490.00"),
        "original_price_yearly": None,
        "included_items": [
            "Member Limit - 175",
            "Member Management",
            "Attendance",
            "Payments",
            "Reports",
            "Packages",
            "Instructor",
            "Sms Management",
            "1 Branch",
            "3 Admin",
        ],
        "yearly_discount_percent": None,
        "price_custom_label": "",
        "price_period_label": "",
        "features": [
            "dashboard", "members", "members.attendance", "members.packages",
            "attendance.devices", "attendance.access_gate", "attendance.fingerprints", "attendance.iclock",
            "instructors", "classes", "reports",
            "payments", "payments.invoices", "subscriptions",
            "crm.contacts", "crm.inquiries",
            "settings", "email_config",
        ],
    },
    "growth": {
        "name": "Growth",
        "description": "Dashboard + Website",
        "price_monthly": Decimal("3490.00"),
        "price_yearly": Decimal("33504.00"),  # 3490 * 12 * 0.80
        "max_users": 300,
        "max_branches": 3,
        "max_members_per_branch": 100,
        "max_trainers_per_branch": 10,
        "max_employees_per_branch": 15,
        "trial_days": 0,
        "is_public": True,
        "highlight": True,
        "sort_order": 2,
        "badge_label": "Most Popular",
        "cta_label": "Buy Now",
        "cta_url": "/register",
        "setup_fee": "Tk. 9,990",
        "original_setup_fee": "",
        "original_price_monthly": Decimal("5490.00"),
        "original_price_yearly": None,
        "included_items": [
            "Include Everything In Starter +",
            "Member Limit - 300",
            "Public Website",
            "Class Booking System",
            "Trainer Profiles",
            "Package Display",
            "Inquiry System",
            "Collect lead",
            "Blog, Content & Branding",
        ],
        "yearly_discount_percent": None,
        "price_custom_label": "",
        "price_period_label": "",
        "features": [
            "dashboard", "members", "members.attendance", "members.packages",
            "attendance.devices", "attendance.access_gate", "attendance.fingerprints", "attendance.iclock",
            "instructors", "classes",
            "payments", "payments.invoices", "payments.gateways", "subscriptions",
            "crm.contacts", "crm.inquiries",
            "cms.banners", "cms.blogs",
            "branches", "reports", "settings", "permissions", "email_config", "public_website",
            "custom_domain",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "description": "For gym chains / franchises",
        "price_monthly": Decimal("0.00"),
        "price_yearly": Decimal("0.00"),
        "max_users": 0,  # unlimited
        "max_branches": 0,  # unlimited
        "max_members_per_branch": 0,  # unlimited
        "max_trainers_per_branch": 0,  # unlimited
        "max_employees_per_branch": 0,  # unlimited
        "trial_days": 0,
        "is_public": True,
        "highlight": False,
        "sort_order": 3,
        "badge_label": "",
        "cta_label": "Chat with Us",
        "cta_url": "http://wa.me/+8801341869125",
        "setup_fee": "Tk. 9,990",
        "original_setup_fee": "",
        "original_price_monthly": None,
        "original_price_yearly": None,
        "included_items": [
            "Multi-Branch System",
            "Custom Features",
            "API / Integrations",
            "Dedicated Support",
            "On-Site Setup (Optional)",
        ],
        "yearly_discount_percent": None,
        "price_custom_label": "Custom",
        "price_period_label": "(10k \u2013 30k+)/Month",
        "features": [k for k, _, _ in CORE_FEATURES],  # everything
    },
}


class Command(BaseCommand):
    help = "Seed core features and Starter/Growth/Enterprise packages."

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
                    "max_members_per_branch": info.get("max_members_per_branch", 0),
                    "max_trainers_per_branch": info.get("max_trainers_per_branch", 0),
                    "max_employees_per_branch": info.get("max_employees_per_branch", 0),
                    "trial_days": info["trial_days"],
                    "is_active": True,
                    "is_public": info["is_public"],
                    "highlight": info["highlight"],
                    "sort_order": info["sort_order"],
                    "badge_label": info.get("badge_label", ""),
                    "cta_label": info.get("cta_label", ""),
                    "cta_url": info.get("cta_url", ""),
                    "setup_fee": info.get("setup_fee", ""),
                    "original_setup_fee": info.get("original_setup_fee", ""),
                    "original_price_monthly": info.get("original_price_monthly"),
                    "original_price_yearly": info.get("original_price_yearly"),
                    "included_items": info.get("included_items", []),
                    "yearly_discount_percent": info.get("yearly_discount_percent"),
                    "price_custom_label": info.get("price_custom_label", ""),
                    "price_period_label": info.get("price_period_label", ""),
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
