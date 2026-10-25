import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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

    async def test_closed_connection_cannot_leave_stale_app_singleton_for_reconnect(self):
        from iterm2.app import App

        connection = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        with patch.object(App, "instance", SimpleNamespace(connection=connection)):
            await close_connection(connection)
            self.assertIsNone(App.instance)

    async def test_closing_another_connection_does_not_invalidate_live_app(self):
        from iterm2.app import App

        connection = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        app = SimpleNamespace(connection=object())
        with patch.object(App, "instance", app):
            await close_connection(connection)
            self.assertIs(App.instance, app)
