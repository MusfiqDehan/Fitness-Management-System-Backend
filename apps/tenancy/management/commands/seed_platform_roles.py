"""Seed predefined platform roles and their default permissions.

Idempotent — safe to re-run. Creates `superadmin`, `platform_manager`,
`support_agent` roles in the public schema and assigns the default
permission matrix from `apps.tenancy.constants`.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.tenancy.constants import PREDEFINED_PLATFORM_ROLE_PERMISSIONS
from apps.tenancy.models import PlatformRole, PlatformRolePermission


PREDEFINED_ROLES = {
    "superadmin": {
        "name": "Superadmin",
        "description": "Full platform-wide access; can manage all tenants, packages, and platform users.",
        "color": "#dc2626",
    },
    "platform_manager": {
        "name": "Platform Manager",
        "description": "Manages tenants and packages, with limited audit visibility.",
        "color": "#2563eb",
    },
    "support_agent": {
        "name": "Support Agent",
        "description": "Read-only tenant access plus support ticket handling.",
        "color": "#16a34a",
    },
}


class Command(BaseCommand):
    help = "Seed predefined platform roles and their default permissions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Reset permissions to defaults even if they were edited.",
        )

    def handle(self, *args, **options):
        reset = options["reset"]
        with transaction.atomic():
            for slug, info in PREDEFINED_ROLES.items():
                role, created = PlatformRole.objects.update_or_create(
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
                else:
                    self.stdout.write(f"Role exists: {slug}")

                permissions_for_role = PREDEFINED_PLATFORM_ROLE_PERMISSIONS.get(slug, {})
                for module_key, level in permissions_for_role.items():
                    obj, perm_created = PlatformRolePermission.objects.get_or_create(
                        role=role,
                        module_key=module_key,
                        defaults={"permission_level": level},
                    )
                    if not perm_created and reset and obj.permission_level != level:
                        obj.permission_level = level
                        obj.save(update_fields=["permission_level"])
                        self.stdout.write(f"  Reset {module_key} -> {level}")
                    elif perm_created:
                        self.stdout.write(f"  Added {module_key} = {level}")

        self.stdout.write(self.style.SUCCESS("Platform roles seeded."))
