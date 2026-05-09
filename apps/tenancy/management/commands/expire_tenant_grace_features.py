"""Daily sweep: disable feature flags whose grace period has expired."""
from django.core.management.base import BaseCommand

from apps.tenancy.services import expire_grace_periods


class Command(BaseCommand):
    help = "Disable TenantFeatureFlag rows whose grace_until is in the past."

    def handle(self, *args, **options):
        count = expire_grace_periods()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} grace flag(s)."))
