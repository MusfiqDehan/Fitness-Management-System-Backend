from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        token_value = self._extract_token()
        if not token_value:
            await self.close()
            return

        user = await self._get_user_from_token(token_value)
        if user is None:
            await self.close()
            return

        self.scope['user'] = user
        schema_name = await self._get_schema_name()

        self.groups = []

        # Every authenticated user joins their personal notification group.
        personal_group = f'notifications_{schema_name}_user_{user.pk}'
        self.groups.append(personal_group)
        await self.channel_layer.group_add(personal_group, self.channel_name)

        # Admins additionally join the schema-wide broadcast group.
        is_admin = await self._is_admin(user)
        if is_admin:
            broadcast_group = f'notifications_{schema_name}'
            self.groups.append(broadcast_group)
            await self.channel_layer.group_add(broadcast_group, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        for group in getattr(self, 'groups', []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def notification_message(self, event):
        await self.send_json(event.get('data', {}))

    def _extract_token(self):
        query_string = self.scope.get('query_string', b'').decode()
        for part in query_string.split('&'):
            if part.startswith('token='):
                return part[len('token='):]
        return None

    @database_sync_to_async
    def _get_user_from_token(self, token_value):
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
        from rest_framework_simplejwt.tokens import AccessToken

        try:
            token = AccessToken(token_value)
            user_id = token['user_id']
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
        return (
            getattr(user, 'is_superuser', False)
            or getattr(user, 'is_staff', False)
            or getattr(user, 'role', '') == 'admin'
        )
