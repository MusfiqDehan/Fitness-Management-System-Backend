"""Seed predefined tenant roles inside the current tenant schema.

Predefined roles (idempotent):
  * admin     — full on everything
  * manager   — edit on members/classes/payments/crm; view on reports
  * instructor — view members; edit classes/schedule
  * editor    — edit cms.banners, cms.blogs; view dashboard
  * viewer    — view-only on dashboard / members / classes

Run with:

    python manage.py tenant_command seed_tenant_roles --schema=<schema>

Or for all tenants:

    python manage.py all_tenants_command seed_tenant_roles
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.access.models import Role, RolePermission


PREDEFINED_TENANT_ROLES = {
    "admin": {
        "name": "Admin",
        "description": "Full access to everything in this tenant.",
        "color": "#dc2626",
        "permissions": "FULL_ACCESS",  # special marker
    },
    "manager": {
        "name": "Manager",
        "description": "Operational manager — manages members, classes, payments.",
        "color": "#2563eb",
        "permissions": {
            "dashboard": "view",
            "members": "edit",
            "members.attendance": "edit",
            "members.packages": "edit",
            "attendance.devices": "edit",
            "attendance.access_gate": "edit",
            "attendance.fingerprints": "edit",
            "instructors": "edit",
            "classes": "edit",
            "classes.bookings": "edit",
            "payments": "edit",
            "payments.invoices": "view",
            "crm.contacts": "edit",
            "crm.inquiries": "edit",
            "reports": "view",
            "reminders": "edit",
        },
    },
    "instructor": {
        "name": "Instructor",
        "description": "Teaches classes — manages schedule and views members.",
        "color": "#16a34a",
        "permissions": {
            "dashboard": "view",
            "members": "view",
            "members.attendance": "view",
            "attendance.devices": "view",
            "attendance.access_gate": "view",
            "attendance.fingerprints": "view",
            "classes": "edit",
            "classes.bookings": "edit",
        },
    },
    "editor": {
        "name": "Content Editor",
        "description": "Manages CMS content (banners and blog posts).",
        "color": "#a855f7",
        "permissions": {
            "dashboard": "view",
            "cms.banners": "edit",
            "cms.blogs": "edit",
        },
    },
    "viewer": {
        "name": "Viewer",
        "description": "Read-only dashboard access.",
        "color": "#64748b",
        "permissions": {
            "dashboard": "view",
            "members": "view",
            "classes": "view",
            "reports": "view",
        },
    },
    "branch_manager": {
        "name": "Branch Manager",
        "description": "Manages a single gym branch — its members, trainers, classes and attendance.",
        "color": "#0891b2",
        "permissions": {
            "dashboard": "view",
            "branches": "view",
            "members": "edit",
            "members.attendance": "edit",
            "members.packages": "view",
            "attendance.devices": "edit",
            "attendance.access_gate": "edit",
            "attendance.fingerprints": "edit",
            "instructors": "edit",
            "classes": "edit",
            "classes.bookings": "edit",
            "payments": "view",
            "crm.contacts": "edit",
            "reports": "view",
            "reminders": "edit",
        },
    },
}


# Master feature list used when expanding FULL_ACCESS for the admin role
FULL_ACCESS_FEATURE_KEYS = [
    "dashboard",
    "members", "members.attendance", "members.packages",
    "attendance.devices", "attendance.access_gate", "attendance.fingerprints", "attendance.iclock",
    "instructors",
    "classes", "classes.bookings",
    "payments", "payments.invoices", "payments.gateways",
    "crm.contacts", "crm.inquiries",
    "cms.banners", "cms.blogs",
    "branches",
    "reports", "reminders",
    "settings", "permissions",
]


class Command(BaseCommand):
    help = "Seed predefined roles (admin, manager, instructor, editor, viewer) in the current tenant schema."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Reset role permissions to defaults if they differ.",
        )

    def handle(self, *args, **options):
        # access_role lives only in tenant schemas, not in the public schema.
        schema = connection.schema_name  # set by django-tenants middleware/commands
        if schema == "public":
            self.stdout.write(self.style.WARNING("Skipping public schema (no access_role table)."))
            return

        reset = options["reset"]
        with transaction.atomic():
            for slug, info in PREDEFINED_TENANT_ROLES.items():
                role, created = Role.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "name": info["name"],
                        "description": info["description"],
                        "color": info["color"],
                        "is_system": True,
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created role: {slug}"))

                permissions = info["permissions"]
                if permissions == "FULL_ACCESS":
                    permissions = {k: "full" for k in FULL_ACCESS_FEATURE_KEYS}

                for feature_key, level in permissions.items():
                    obj, perm_created = RolePermission.objects.get_or_create(
                        role=role,
                        feature_key=feature_key,
                        defaults={"permission_level": level},
                    )
                    if not perm_created and reset and obj.permission_level != level:
                        obj.permission_level = level
                        obj.save(update_fields=["permission_level"])
                        self.stdout.write(f"  Reset {feature_key} -> {level}")
                    elif perm_created:
                        self.stdout.write(f"  Added {feature_key} = {level}")

        self.stdout.write(self.style.SUCCESS("Tenant roles seeded."))
