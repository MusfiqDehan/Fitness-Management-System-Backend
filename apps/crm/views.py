import logging

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeaturePermission
from apps.tenancy.permissions import IsPlatformFeaturePermission
from utils.base_view import ModelCRUDView
from .email_delivery import resolve_platform_mail_route

from .models import ContactQuery, EmailConfig, TenantEmailConfig
from .serializers import ContactQuerySerializer, EmailConfigSerializer, TenantEmailConfigSerializer

logger = logging.getLogger(__name__)


class ContactQueryAPIView(APIView):
    """
    POST /api/v1/crm/contact/

    Accepts a contact-us form submission from the public landing page,
    persists it, and sends an email notification to the configured
    contact address.  Uses the active EmailConfig from the DB when
    available; falls back to Django settings otherwise.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ContactQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query: ContactQuery = serializer.save()

        self._send_notification(query)

        return Response(
            ContactQuerySerializer(query).data,
            status=status.HTTP_201_CREATED,
        )

    def _send_notification(self, query: ContactQuery) -> None:
        subject = f"New Contact Query from {query.full_name}"
        body = (
            f"Name:    {query.full_name}\n"
            f"Phone:   {query.phone_number}\n"
            f"Email:   {query.email or 'Not provided'}\n"
            f"Package: {query.package_name or 'Not selected'}\n"
            f"\nMessage:\n{query.message or 'No message provided'}"
        )

        from_email, connection, to_email = resolve_platform_mail_route()
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=from_email,
                recipient_list=[to_email],
                connection=connection,
                fail_silently=False,
            )
        except Exception as first_exc:
            fallback_to = getattr(settings, "CONTACT_EMAIL", settings.DEFAULT_FROM_EMAIL)
            try:
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[fallback_to],
                    fail_silently=False,
                )
            except Exception as exc:
                logger.error(
                    "Failed to send contact-query notification email: primary=%s fallback=%s",
                    first_exc,
                    exc,
                )


class TenantEmailConfigView(ModelCRUDView):
    """Tenant-scoped SMTP/email configuration management."""

    queryset = TenantEmailConfig.objects.all()
    serializer_class = TenantEmailConfigSerializer
    permission_classes = [HasFeaturePermission.require("email_config", "view")]

    actions = {
        "activate": lambda self, req, pk: self._action_activate(req, pk),
        "deactivate": lambda self, req, pk: self._action_deactivate(req, pk),
        "restore": lambda self, req, pk: self._action_restore(req, pk),
    }

    def get_permissions(self):
        if self.request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return [HasFeaturePermission.require("email_config", "edit")()]
        return super().get_permissions()

    def _create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(created_by=request.user, updated_by=request.user)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def _update(self, pk, request, partial=True):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(updated_by=request.user)
        return Response(self.get_serializer(instance).data)

    def _action_activate(self, request, pk):
        instance = self.get_object()
        TenantEmailConfig.objects.exclude(pk=instance.pk).update(is_active=False)
        instance.is_active = True
        instance.updated_by = request.user
        instance.save(update_fields=["is_active", "updated_by_id", "updated_at"])
        return Response(self.get_serializer(instance).data)

    def _action_deactivate(self, request, pk):
        instance = self.get_object()
        instance.is_active = False
        instance.updated_by = request.user
        instance.save(update_fields=["is_active", "updated_by_id", "updated_at"])
        return Response(self.get_serializer(instance).data)

    def _action_restore(self, request, pk):
        instance = TenantEmailConfig.all_objects.get(pk=pk)
        instance.restore()
        return Response(self.get_serializer(instance).data)


class EmailConfigView(ModelCRUDView):
    """
    Platform-admin CRUD for EmailConfig.

    GET    /api/v1/crm/email-configs/                      → list
    POST   /api/v1/crm/email-configs/                      → create
    GET    /api/v1/crm/email-configs/<pk>/                  → retrieve
    PATCH  /api/v1/crm/email-configs/<pk>/                  → partial update
    DELETE /api/v1/crm/email-configs/<pk>/                  → soft delete
    POST   /api/v1/crm/email-configs/<pk>/?action=activate   → activate
    POST   /api/v1/crm/email-configs/<pk>/?action=deactivate → deactivate
    POST   /api/v1/crm/email-configs/<pk>/?action=restore    → restore soft-deleted
    """

    queryset = EmailConfig.objects.all()
    serializer_class = EmailConfigSerializer
    permission_classes = [IsPlatformFeaturePermission.require("platform.email_settings", "view")]

    actions = {
        "activate": lambda self, req, pk: self._action_activate(req, pk),
        "deactivate": lambda self, req, pk: self._action_deactivate(req, pk),
        "restore": lambda self, req, pk: self._action_restore(req, pk),
    }

    # ------------------------------------------------------------------ #
    # Write-permission override: tighten to "edit" for mutating methods   #
    # ------------------------------------------------------------------ #

    def get_permissions(self):
        if self.request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return [IsPlatformFeaturePermission.require("platform.email_settings", "edit")()]
        return super().get_permissions()

    # ------------------------------------------------------------------ #
    # CRUD overrides to stamp created_by / updated_by                    #
    # ------------------------------------------------------------------ #

    def _create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(created_by=request.user, updated_by=request.user)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def _update(self, pk, request, partial=True):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(updated_by=request.user)
        return Response(self.get_serializer(instance).data)

    # ------------------------------------------------------------------ #
    # Custom actions                                                      #
    # ------------------------------------------------------------------ #

    def _action_activate(self, request, pk):
        instance = self.get_object()
        # Only one active config at a time
        EmailConfig.objects.exclude(pk=instance.pk).update(is_active=False)
        instance.is_active = True
        instance.updated_by = request.user
        instance.save(update_fields=["is_active", "updated_by_id", "updated_at"])
        return Response(self.get_serializer(instance).data)

    def _action_deactivate(self, request, pk):
        instance = self.get_object()
        instance.is_active = False
        instance.updated_by = request.user
        instance.save(update_fields=["is_active", "updated_by_id", "updated_at"])
        return Response(self.get_serializer(instance).data)

    def _action_restore(self, request, pk):
        instance = EmailConfig.all_objects.get(pk=pk)
        instance.restore()
        return Response(self.get_serializer(instance).data)

