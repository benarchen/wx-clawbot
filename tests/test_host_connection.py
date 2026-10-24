import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.hosts.connection import close_connection


class HostConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_is_cancelled_before_websocket_close(self):
        reader = asyncio.create_task(asyncio.Event().wait())
        await asyncio.sleep(0)

        async def close():
            self.assertTrue(reader.cancelled())

        connection = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock(side_effect=close)))
        setattr(connection, "_Connection__dispatch_forever_future", reader)
        await close_connection(connection)
        connection.websocket.close.assert_awaited_once()
