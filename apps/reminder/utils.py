from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import connection

from .models import Notification


def user_can_access_notification_feed(user, *, schema_name=None):
    """Any authenticated user may access the notification feed.

    Access to individual notifications is enforced at the queryset level:
    - Admins see all broadcast (recipient=None) notifications.
    - Members/trainers see only notifications targeted at them.
    """
    return bool(getattr(user, 'is_authenticated', False))


def create_notification(
    *,
    notification_type,
    title,
    message='',
    actor_name='',
    actor_email='',
    target_type='',
    target_id='',
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
        target_id=str(target_id) if target_id else '',
        metadata=metadata,
        recipient=recipient,
    )

    schema_name = connection.schema_name
    # Personal notifications go to the user's own WS group; broadcast goes to
    # the schema-wide group that all tenant admins are subscribed to.
    if recipient is not None:
        group_name = f'notifications_{schema_name}_user_{recipient.pk}'
    else:
        group_name = f'notifications_{schema_name}'

    channel_layer = get_channel_layer()
    if channel_layer is not None:
        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    'type': 'notification_message',
                    'data': {
                        'event': 'new_notification',
                        'notification': {
                            'id': notification.id,
                            'notification_type': notification.notification_type,
                            'title': notification.title,
                            'message': notification.message,
                            'actor_name': notification.actor_name,
                            'created_at': notification.created_at.isoformat(),
                        },
                    },
                },
            )
        except Exception:
            pass  # WebSocket push is best-effort; do not fail the main request

    return notification
