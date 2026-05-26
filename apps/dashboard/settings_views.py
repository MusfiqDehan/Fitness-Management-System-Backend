"""
Settings and Reminders views for the dashboard app.
Imported and wired in views.py via explicit __all__ re-exports.
"""
from django.db.models import Sum
from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cms.models import SiteSettings
from apps.identity.serializers import CurrentUserSerializer, CurrentUserUpdateSerializer
from apps.membership.models import Member

from .models import (
    GymPreferences,
    GymProfile,
    NotificationPreferences,
    Reminder,
    ReminderTemplate,
)
from .serializers import (
    GymPreferencesSerializer,
    GymProfileSerializer,
    NotificationPreferencesSerializer,
    ReminderSerializer,
    ReminderTemplateSerializer,
)


# ---------------------------------------------------------------
# Settings — Gym Profile
# ---------------------------------------------------------------

class GymProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self):
        obj, _ = GymProfile.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(GymProfileSerializer(self._obj()).data)

    def patch(self, request):
        serializer = GymProfileSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Auto-sync to SiteSettings so the public homepage/navbar/footer stays current.
        profile = serializer.instance
        site_settings, _ = SiteSettings.objects.get_or_create(pk=1)
        site_settings.company_name = profile.gym_name
        site_settings.email = profile.email
        site_settings.phone = profile.phone
        site_settings.address = profile.address
        site_settings.website = profile.website
        site_settings.timezone = profile.timezone
        if profile.logo_url:
            site_settings.logo_url = profile.logo_url
        site_settings.logo_width = profile.logo_width
        site_settings.logo_height = profile.logo_height
        site_settings.save(update_fields=[
            "company_name", "email", "phone", "address", "website", "timezone",
            "logo_url", "logo_width", "logo_height",
        ])

        return Response(serializer.data)


# ---------------------------------------------------------------
# Settings — Notification Preferences
# ---------------------------------------------------------------

class NotificationPreferencesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self):
        obj, _ = NotificationPreferences.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(NotificationPreferencesSerializer(self._obj()).data)

    def patch(self, request):
        serializer = NotificationPreferencesSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------
# Settings — Gym Preferences
# ---------------------------------------------------------------

class GymPreferencesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self):
        obj, _ = GymPreferences.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(GymPreferencesSerializer(self._obj()).data)

    def patch(self, request):
        serializer = GymPreferencesSerializer(self._obj(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------
# Settings — My Account (proxy to identity/me)
# ---------------------------------------------------------------

class MyAccountAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)

    def patch(self, request):
        serializer = CurrentUserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CurrentUserSerializer(request.user).data)


# ---------------------------------------------------------------
# Settings — Change Password
# ---------------------------------------------------------------

class ChangePasswordAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get("current_password", "")
        new_password = request.data.get("new_password", "")

        if not current_password or not new_password:
            return Response(
                {"detail": "current_password and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not request.user.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(new_password) < 8:
            return Response(
                {"detail": "New password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(new_password)
        request.user.password_set_at = dj_timezone.now()
        request.user.save(update_fields=["password", "password_set_at"])
        return Response({"detail": "Password changed successfully."})


# ---------------------------------------------------------------
# Reminders — Templates
# ---------------------------------------------------------------

class ReminderTemplateListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(ReminderTemplateSerializer(ReminderTemplate.objects.all(), many=True).data)

    def post(self, request):
        serializer = ReminderTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ReminderTemplateDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return ReminderTemplate.objects.get(pk=pk)
        except ReminderTemplate.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ReminderTemplateSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ReminderTemplateSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------
# Reminders — Reminder records
# ---------------------------------------------------------------

class ReminderListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Reminder.objects.select_related("member", "member__member_package")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(ReminderSerializer(qs, many=True).data)

    def post(self, request):
        serializer = ReminderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ReminderDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return Reminder.objects.select_related("member", "member__member_package").get(pk=pk)
        except Reminder.DoesNotExist:
            return None

    def patch(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ReminderSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReminderSendAPIView(APIView):
    """Mark a reminder as sent."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            reminder = Reminder.objects.get(pk=pk)
        except Reminder.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        reminder.status = "sent"
        reminder.sent_at = dj_timezone.now()
        reminder.save(update_fields=["status", "sent_at"])
        return Response(ReminderSerializer(reminder).data)


# ---------------------------------------------------------------
# Reminders — Stats
# ---------------------------------------------------------------

class ReminderStatsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import date
        first_of_month = date.today().replace(day=1)

        pending = Reminder.objects.filter(status="pending").count()
        sent_this_month = Reminder.objects.filter(
            status="sent", sent_at__date__gte=first_of_month
        ).count()
        overdue_members = Member.objects.filter(end_date__lt=date.today()).count()
        overdue_amount = (
            Reminder.objects.filter(status="pending", reminder_type="payment_due")
            .aggregate(total=Sum("amount"))["total"] or 0
        )
        active_templates = ReminderTemplate.objects.filter(is_active=True).count()

        return Response({
            "pending": pending,
            "sent_this_month": sent_this_month,
            "overdue_members": overdue_members,
            "overdue_amount": str(overdue_amount),
            "active_templates": active_templates,
        })
