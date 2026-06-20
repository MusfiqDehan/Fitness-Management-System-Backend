"""WebSocket-only ASGI entrypoint so long-lived /ws connections do not starve API workers."""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Initialize Django before importing routing modules.
get_asgi_application()

from apps.attendance.routing import websocket_urlpatterns as attendance_ws
from apps.reminder.routing import websocket_urlpatterns as notification_ws

application = ProtocolTypeRouter(
    {
        "websocket": AuthMiddlewareStack(URLRouter(attendance_ws + notification_ws)),
    }
)
