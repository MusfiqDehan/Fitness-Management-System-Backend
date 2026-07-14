from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.base_view import ModelCRUDView

from .models import Notification, NotificationRead
from .serializers import NotificationSerializer
from .utils import (
    get_notification_counts,
    get_scoped_notifications_queryset,
    push_notification_count,
    user_can_access_notification_feed,
)


class CanAccessNotificationFeed(BasePermission):
    message = "Authentication required to access the notification feed."

    def has_permission(self, request, view):
        return user_can_access_notification_feed(request.user)


class NotificationModelActions:
    actions = {
        "mark-read": lambda self, req, pk: self._mark_read(req, pk),
    }

    def _mark_read(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk)
        except Notification.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        _, created = NotificationRead.objects.get_or_create(
            notification=notification,
            user=request.user,
        )
        if created:
            push_notification_count(request.user)
        return Response({"message": "Marked as read"})


class NotificationView(NotificationModelActions, ModelCRUDView):
    permission_classes = [IsAuthenticated, CanAccessNotificationFeed]
    serializer_class = NotificationSerializer
    queryset = Notification.objects.all()

    def _get_scoped_queryset(self, user):
        return get_scoped_notifications_queryset(user)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["read_ids"] = set(
            NotificationRead.objects.filter(user=self.request.user).values_list(
                "notification_id", flat=True
            )
        )
        return ctx

    def _list(self, request):
        status_filter = request.query_params.get("status", "all")
        read_ids = set(
            NotificationRead.objects.filter(user=request.user).values_list(
                "notification_id", flat=True
            )
        )
        queryset = self._get_scoped_queryset(request.user).order_by("-created_at")
        if status_filter == "read":
            queryset = queryset.filter(id__in=read_ids)
        elif status_filter == "unread":
            queryset = queryset.exclude(id__in=read_ids)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def _create(self, request):
        action = request.query_params.get("action")
        if action == "mark-all-read":
            scoped_qs = self._get_scoped_queryset(request.user)
            all_ids = set(scoped_qs.values_list("id", flat=True))
            already_read = set(
                NotificationRead.objects.filter(user=request.user).values_list(
                    "notification_id", flat=True
                )
            )
            unread_ids = all_ids - already_read
            NotificationRead.objects.bulk_create(
                [
                    NotificationRead(notification_id=nid, user=request.user)
                    for nid in unread_ids
                ],
                ignore_conflicts=True,
            )
            if unread_ids:
                push_notification_count(request.user)
            return Response(
                {"message": "All notifications marked as read", "count": len(unread_ids)}
            )
        return Response({"detail": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class NotificationCountView(APIView):
    permission_classes = [IsAuthenticated, CanAccessNotificationFeed]

    def get(self, request):
        return Response(get_notification_counts(request.user))
