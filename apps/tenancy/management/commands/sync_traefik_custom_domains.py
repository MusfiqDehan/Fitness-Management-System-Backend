from django.core.management.base import BaseCommand

from apps.tenancy.traefik_custom_domains import (
    list_verified_custom_domains,
    sync_traefik_custom_domains,
)


class Command(BaseCommand):
    help = (
        "Regenerate Traefik dynamic routers for verified tenant custom domains "
        "(HTTP-01 Let's Encrypt via the customdomains resolver)."
    )

    def handle(self, *args, **options):
        domains = list_verified_custom_domains()
        path = sync_traefik_custom_domains()
        if path is None:
            self.stderr.write(
                self.style.ERROR(
                    "Failed to write Traefik custom-domains config "
                    "(check TRAEFIK_CUSTOM_DOMAINS_PATH and mount permissions)."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {len(domains)} domain(s) → {path}"
            )
        )
        for d in domains:
            self.stdout.write(f"  - {d}")
