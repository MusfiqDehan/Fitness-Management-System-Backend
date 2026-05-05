import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name

from apps.tenancy.models import Tenant


def ensure_superadmin(user_model, email, password, stdout, tenant=None):
    user = user_model.objects.filter(email__iexact=email).first()

    if user:
        if tenant is not None and user.tenant_id is None:
            user.tenant = tenant
            user.save(update_fields=["tenant"])
            stdout.write(f"Linked existing superadmin to tenant: {email}")
            return
        stdout.write(f"Superadmin already exists: {email}")
        return

    user_model.objects.create_superuser(
        email=email,
        password=password,
        tenant=tenant,
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
        # Platform superadmin should live in the public control-plane schema.
        # Allow explicit overrides, but default to public rather than a tenant.
        target_schema = os.environ.get("SUPERADMIN_SCHEMA", "").strip() or get_public_schema_name()

        if target_schema:
            try:
                from django_tenants.utils import schema_context
            except Exception as exc:
                raise CommandError(f"Unable to import django-tenants schema_context: {exc}")

            tenant = Tenant.objects.filter(schema_name=target_schema).first()
            with schema_context(target_schema):
                ensure_superadmin(user_model, email, password, self.stdout, tenant=tenant)
            return

        ensure_superadmin(user_model, email, password, self.stdout)
