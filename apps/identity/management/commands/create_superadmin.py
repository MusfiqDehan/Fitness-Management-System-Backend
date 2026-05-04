import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


def ensure_superadmin(user_model, email, password, stdout):
    user = user_model.objects.filter(email__iexact=email).first()

    if user:
        stdout.write(f"Superadmin already exists: {email}")
        return

    user_model.objects.create_superuser(
        email=email,
        password=password,
    )
    stdout.write(f"Created superadmin: {email}")


class Command(BaseCommand):
    help = "Create the default superadmin account if it does not exist."

    def handle(self, *args, **options):
        email = os.environ.get("SUPERADMIN_EMAIL", "").strip()
        password = os.environ.get("SUPERADMIN_PASSWORD", "")

        if not email:
            raise CommandError("SUPERADMIN_EMAIL is not set.")
        if not password:
            raise CommandError("SUPERADMIN_PASSWORD is not set.")

        user_model = get_user_model()
        # For django-tenants setups, this allows creating the superadmin
        # directly in a tenant schema (e.g. gym_local) instead of public.
        target_schema = (
            os.environ.get("SUPERADMIN_SCHEMA", "").strip()
            or os.environ.get("DEFAULT_TENANT_SCHEMA", "").strip()
        )

        if target_schema:
            try:
                from django_tenants.utils import schema_context
            except Exception as exc:
                raise CommandError(f"Unable to import django-tenants schema_context: {exc}")

            with schema_context(target_schema):
                ensure_superadmin(user_model, email, password, self.stdout)
            return

        ensure_superadmin(user_model, email, password, self.stdout)