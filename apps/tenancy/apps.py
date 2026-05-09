from django.apps import AppConfig


class TenancyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.tenancy'
    label = 'tenancy'
    verbose_name = 'Tenancy'

    def ready(self):
        # Register signal handlers (auto-sync TenantFeatureFlag on plan change).
        from . import signals  # noqa: F401

