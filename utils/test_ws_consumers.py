import unittest
from unittest.mock import AsyncMock

from utils.ws_consumers import SafeAsyncJsonWebsocketConsumer


class SafeAsyncJsonWebsocketConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_safe_send_json_returns_true_on_success(self):
        consumer = SafeAsyncJsonWebsocketConsumer()
        consumer.send_json = AsyncMock()

        sent = await consumer.safe_send_json({"event": "ping"})

        self.assertTrue(sent)
        consumer.send_json.assert_awaited_once_with({"event": "ping"}, close=False)

    async def test_safe_send_json_swallows_disconnect_errors(self):
        consumer = SafeAsyncJsonWebsocketConsumer()

        class Disconnected(Exception):
            pass

        consumer.send_json = AsyncMock(side_effect=Disconnected("closed protocol"))

        sent = await consumer.safe_send_json({"event": "ping"})

        self.assertFalse(sent)


if __name__ == "__main__":
    unittest.main()
