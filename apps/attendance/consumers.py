from utils.ws_consumers import SafeAsyncJsonWebsocketConsumer


class AttendanceConsumer(SafeAsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("attendance_events", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("attendance_events", self.channel_name)

    async def attendance_event(self, event):
        await self.safe_send_json(
            {
                "event": event.get("event"),
                "payload": event.get("payload", {}),
            }
        )
