"""Shared helpers for Channels WebSocket consumers."""

from __future__ import annotations

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class SafeAsyncJsonWebsocketConsumer(AsyncJsonWebsocketConsumer):
    """Async JSON consumer that ignores send attempts on closed connections."""

    async def safe_send_json(self, content, *, close: bool = False) -> bool:
        try:
            await self.send_json(content, close=close)
            return True
        except Exception as exc:
            # Client navigated away or the socket closed during an in-flight DB call.
            logger.debug("WebSocket send skipped (client disconnected): %s", exc)
            return False
