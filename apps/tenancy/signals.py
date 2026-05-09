"""Tenancy signal handlers — auto-sync TenantFeatureFlag rows on plan change."""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Tenant
from .services import sync_tenant_features


# Track the previous `plan` value so we know whether to re-sync after save.
_PLAN_BEFORE_SAVE_KEY = "_tenancy_plan_before_save"


@receiver(pre_save, sender=Tenant)
def _capture_previous_plan(sender, instance, **kwargs):
    if not instance.pk:
        setattr(instance, _PLAN_BEFORE_SAVE_KEY, None)
        return
    try:
        previous = sender.objects.only("plan").get(pk=instance.pk)
        setattr(instance, _PLAN_BEFORE_SAVE_KEY, previous.plan)
    except sender.DoesNotExist:
        setattr(instance, _PLAN_BEFORE_SAVE_KEY, None)


@receiver(post_save, sender=Tenant)
def _sync_features_on_tenant_save(sender, instance, created, **kwargs):
    previous_plan = getattr(instance, _PLAN_BEFORE_SAVE_KEY, None)
    plan_changed = created or previous_plan != instance.plan
    if not plan_changed:
        return
    # Wrapped in try to avoid breaking tenant creation in environments
    # without seeded packages (initial migrations, tests).
    try:
        sync_tenant_features(instance)
    except Exception:
        pass
