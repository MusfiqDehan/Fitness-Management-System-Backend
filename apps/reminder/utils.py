from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import connection
from django.db.models import Q

from .models import Notification, NotificationRead


def user_can_access_notification_feed(user, *, schema_name=None):
    """Any authenticated user may access the notification feed.

    Access to individual notifications is enforced at the queryset level:
    - Admins see all broadcast (recipient=None) notifications.
    - Members/trainers see only notifications targeted at them.
    """
    return bool(getattr(user, "is_authenticated", False))


def is_tenant_admin(user) -> bool:
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
        or getattr(user, "role", "") == "admin"
    )


def get_scoped_notifications_queryset(user):
    if is_tenant_admin(user):
        return Notification.objects.filter(Q(recipient__isnull=True) | Q(recipient=user))
    return Notification.objects.filter(recipient=user)


def get_notification_counts(user) -> dict[str, int]:
    """Return {total, unread} for the user's scoped notification feed."""
    base_qs = get_scoped_notifications_queryset(user)
    total = base_qs.count()
    read_count = NotificationRead.objects.filter(
        user=user,
        notification_id__in=base_qs.values("id"),
    ).count()
    return {"total": total, "unread": total - read_count}


def personal_ws_group(schema_name: str, user_id: int) -> str:
    return f"notifications_{schema_name}_user_{user_id}"


def broadcast_ws_group(schema_name: str) -> str:
    return f"notifications_{schema_name}"


def get_tenant_admin_user_ids() -> list[int]:
    from apps.identity.models import User

    return list(
        User.objects.filter(
            Q(is_superuser=True) | Q(is_staff=True) | Q(role="admin")
        ).values_list("id", flat=True)
    )


def push_ws_notification_data(group_name: str, data: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {"type": "notification_message", "data": data},
        )
    except Exception:
        pass  # WebSocket push is best-effort; do not fail the main request


def push_notification_count(user, *, schema_name: str | None = None) -> None:
    schema_name = schema_name or connection.schema_name
    counts = get_notification_counts(user)
    push_ws_notification_data(
        personal_ws_group(schema_name, user.pk),
        {
            "event": "count_updated",
            "total": counts["total"],
            "unread": counts["unread"],
        },
    )


def push_notification_count_for_user_id(user_id: int, *, schema_name: str | None = None) -> None:
    from apps.identity.models import User

    schema_name = schema_name or connection.schema_name
    user = User.objects.filter(pk=user_id).first()
    if user is not None:
        push_notification_count(user, schema_name=schema_name)


def push_notification_counts_for_admins(*, schema_name: str | None = None) -> None:
    schema_name = schema_name or connection.schema_name
    from apps.identity.models import User

    admin_ids = get_tenant_admin_user_ids()
    for user in User.objects.filter(pk__in=admin_ids):
        push_notification_count(user, schema_name=schema_name)


def create_notification(
    *,
    notification_type,
    title,
    message="",
    actor_name="",
    actor_email="",
    target_type="",
    target_id="",
    metadata=None,
    recipient=None,
):
    """Create a Notification in the currently active schema and push via WebSocket.

    Pass ``recipient`` (a User instance) to create a personal notification visible
    only to that user.  When ``recipient`` is None the notification is a broadcast
    visible to all tenant admins.
    """
    notification = Notification.objects.create(
        notification_type=notification_type,
        title=title,
        message=message,
        actor_name=actor_name,
        actor_email=actor_email,
        target_type=target_type,
        target_id=str(target_id) if target_id else "",
        metadata=metadata,
        recipient=recipient,
    )

    schema_name = connection.schema_name
    notification_payload = {
        "id": notification.id,
        "notification_type": notification.notification_type,
        "title": notification.title,
        "message": notification.message,
        "actor_name": notification.actor_name,
        "created_at": notification.created_at.isoformat(),
    }

    if recipient is not None:
        group_name = personal_ws_group(schema_name, recipient.pk)
        push_ws_notification_data(
            group_name,
            {"event": "new_notification", "notification": notification_payload},
        )
        push_notification_count(recipient, schema_name=schema_name)
    else:
        push_ws_notification_data(
            broadcast_ws_group(schema_name),
            {"event": "new_notification", "notification": notification_payload},
        )
        push_notification_counts_for_admins(schema_name=schema_name)

    return notification
