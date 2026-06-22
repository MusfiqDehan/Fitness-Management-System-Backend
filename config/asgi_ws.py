"""WebSocket-only ASGI entrypoint so long-lived /ws connections do not starve API workers."""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from apps.attendance.routing import websocket_urlpatterns as attendance_ws
from apps.reminder.routing import websocket_urlpatterns as notification_ws

application = ProtocolTypeRouter(
    {
        # HTTP is required for Docker/Traefik readiness probes on this port.
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(attendance_ws + notification_ws)),
    }
)
