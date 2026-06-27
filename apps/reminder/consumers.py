from channels.db import database_sync_to_async

from utils.ws_consumers import SafeAsyncJsonWebsocketConsumer

from .utils import (
    broadcast_ws_group,
    get_notification_counts,
    personal_ws_group,
)


class NotificationConsumer(SafeAsyncJsonWebsocketConsumer):
    async def connect(self):
        token_value = self._extract_token()
        if not token_value:
            await self.close()
            return

        user = await self._get_user_from_token(token_value)
        if user is None:
            await self.close()
            return

        self.scope["user"] = user
        schema_name = await self._get_schema_name()

        self.groups = []

        personal_group = personal_ws_group(schema_name, user.pk)
        self.groups.append(personal_group)
        await self.channel_layer.group_add(personal_group, self.channel_name)

        is_admin = await self._is_admin(user)
        if is_admin:
            broadcast_group = broadcast_ws_group(schema_name)
            self.groups.append(broadcast_group)
            await self.channel_layer.group_add(broadcast_group, self.channel_name)

        await self.accept()
        counts = await database_sync_to_async(get_notification_counts)(user)
        await self.safe_send_json(
            {
                "event": "count_updated",
                "total": counts["total"],
                "unread": counts["unread"],
            }
        )

    async def disconnect(self, close_code):
        for group in getattr(self, "groups", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def notification_message(self, event):
        await self.safe_send_json(event.get("data", {}))

    def _extract_token(self):
        query_string = self.scope.get("query_string", b"").decode()
        for part in query_string.split("&"):
            if part.startswith("token="):
                return part[len("token=") :]
        return None

    @database_sync_to_async
    def _get_user_from_token(self, token_value):
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
        from rest_framework_simplejwt.tokens import AccessToken

        try:
            token = AccessToken(token_value)
            user_id = token["user_id"]
        except (TokenError, InvalidToken, KeyError):
            return None
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def _get_schema_name(self):
        from django.db import connection

        return connection.schema_name

    @database_sync_to_async
    def _is_admin(self, user):
        from .utils import is_tenant_admin

        return is_tenant_admin(user)
