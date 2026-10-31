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

    async def test_close_removes_only_owned_app_handlers_and_cancels_receivers(self):
        from iterm2.app import App, invalidate_app
        from iterm2 import notifications
        callback, foreign = object(), object()
        key = (None, 1)
        connection = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        receiver = asyncio.get_running_loop().create_future()
        helper = asyncio.create_task(asyncio.Event().wait())
        setattr(connection, "_Connection__receivers", [(lambda _: True, receiver)])
        setattr(connection, "_Connection__tasks", [helper])
        app = SimpleNamespace(connection=connection, tokens=[(key, callback)])
        with patch.object(App, "instance", app), \
                patch.dict(notifications._handlers, {key: [callback, foreign]}, clear=True), \
                patch("iterm2.connection.gDisconnectCallbacks", [invalidate_app, foreign]) as disconnects:
            await close_connection(connection)
            self.assertEqual(notifications._handlers[key], [foreign])
            self.assertEqual(disconnects, [foreign])
            self.assertIsNone(App.instance)
        self.assertTrue(receiver.cancelled())
        self.assertTrue(helper.cancelled())
