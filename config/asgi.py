"""ASGI config with Channels protocol routing."""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()

# Import websocket routes only after Django apps are initialized.
from apps.attendance.routing import websocket_urlpatterns as attendance_ws
from apps.reminder.routing import websocket_urlpatterns as notification_ws

application = ProtocolTypeRouter(
	{
		"http": django_asgi_app,
		"websocket": AuthMiddlewareStack(URLRouter(attendance_ws + notification_ws)),
	}
)
