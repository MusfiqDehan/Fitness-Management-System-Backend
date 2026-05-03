import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


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
        user = user_model.objects.filter(email__iexact=email).first()

        if user:
            self.stdout.write(self.style.SUCCESS(f"Superadmin already exists: {email}"))
            return

        user_model.objects.create_superuser(
            email=email,
            password=password,
        )
        self.stdout.write(self.style.SUCCESS(f"Created superadmin: {email}"))