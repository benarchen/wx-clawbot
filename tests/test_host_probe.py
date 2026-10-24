import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.hosts.iterm2 import probe


class HostProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_timeout_does_not_claim_api_disabled(self):
        with patch("iterm2.Connection.async_create", new=AsyncMock(side_effect=TimeoutError)):
            result = await probe()
        self.assertEqual(result["phase"], "connect")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("不能据此判断", result["next_step"])

    async def test_list_timeout_reports_phase_and_closes_connection(self):
        connection = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        with patch("iterm2.Connection.async_create", new=AsyncMock(return_value=connection)), \
                patch("iterm2.async_get_app", new=AsyncMock(side_effect=TimeoutError)):
            result = await probe()
        self.assertEqual(result["phase"], "list_sessions")
        connection.websocket.close.assert_awaited_once()
