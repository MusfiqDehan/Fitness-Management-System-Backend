from django.db import connection
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_tenants.utils import get_public_schema_name, schema_context

from apps.tenancy.models import AccessDeviceRoute, Tenant

from .models import AccessDevice


def _current_tenant():
    schema_name = connection.schema_name
    if schema_name == get_public_schema_name():
        return None

    with schema_context(get_public_schema_name()):
        return Tenant.objects.only("id", "schema_name").get(schema_name=schema_name)


@receiver(post_save, sender=AccessDevice)
def _sync_access_device_route(sender, instance, **kwargs):
    tenant = _current_tenant()
    if tenant is None:
        return

    with schema_context(get_public_schema_name()):
        AccessDeviceRoute.objects.update_or_create(
            tenant=tenant,
            access_device_id=instance.pk,
            defaults={
                "device_sn": instance.device_sn,
                "is_active": instance.is_active,
            },
        )


@receiver(post_delete, sender=AccessDevice)
def _delete_access_device_route(sender, instance, **kwargs):
    tenant = _current_tenant()
    if tenant is None:
        return

    with schema_context(get_public_schema_name()):
        AccessDeviceRoute.objects.filter(
            tenant=tenant,
            access_device_id=instance.pk,
        ).delete()
