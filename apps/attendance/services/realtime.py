from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def publish_attendance_event(event: str, payload: dict) -> None:
    """Publish attendance-domain events to websocket subscribers."""
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        "attendance_events",
        {
            "type": "attendance.event",
            "event": event,
            "payload": payload,
        },
    )
