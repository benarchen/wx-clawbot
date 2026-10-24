import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from wx_clawbot.channels.diagnostics import echo
from wx_clawbot.channels.http import ProtocolError, TransportError
from wx_clawbot.channels.login import confirm_owner, login, owner_fingerprint
from wx_clawbot.channels.private import load_credentials, read_json, save_credentials
from wx_clawbot.channels.wechat import Credentials, Login
from test_wechat_state import message


class LoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "wechat-login-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")

    async def test_login_intent_precedes_request_and_scan_does_not_confirm_owner(self):
        async def start():
            self.assertEqual(read_json(self.root / "login.json")["phase"], "starting")
            return Login("fixture-code", "fixture-display", time.time())
        api = AsyncMock()
        api.start_login.side_effect = start
        api.login_status.return_value = ("confirmed", self.account)
        with patch("wx_clawbot.channels.login.WechatApi", return_value=api):
            result = await login(self.root, emit=lambda *a, **kw: None)
        self.assertEqual(result["status"], "awaiting_owner_confirmation")
        self.assertFalse(read_json(self.root / "credentials.json")["owner_confirmed"])
        png = next(self.root.glob("*.png"))
        self.assertTrue(png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(png.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ProtocolError):
            confirm_owner(self.root, "wrong-fingerprint")
        confirm_owner(self.root, owner_fingerprint(self.account))
        self.assertEqual(load_credentials(self.root / "credentials.json"), self.account)

    async def test_unconfirmed_owner_never_starts_polling_or_sending(self):
        save_credentials(self.root / "credentials.json", self.account)
        with patch("wx_clawbot.channels.diagnostics.WechatApi") as api:
            with self.assertRaises(ProtocolError):
                await echo(self.root, challenge="WX-TEST-12345678", count=1, timeout=1)
            api.assert_not_called()

    async def test_qr_request_loss_is_unknown_and_cannot_silently_create_another(self):
        api = AsyncMock()
        api.start_login.side_effect = TransportError("connection lost")
        with patch("wx_clawbot.channels.login.WechatApi", return_value=api):
            with self.assertRaises(TransportError):
                await login(self.root, emit=lambda *a, **kw: None)
            self.assertEqual(read_json(self.root / "login.json")["phase"], "unknown")
            with self.assertRaisesRegex(Exception, "outcome unknown"):
                await login(self.root, emit=lambda *a, **kw: None)
        self.assertEqual(api.start_login.await_count, 1)

    async def test_server_expiry_requires_explicit_refresh_even_before_local_deadline(self):
        api = AsyncMock()
        api.start_login.side_effect = [
            Login("first-code", "first-display", time.time()),
            Login("second-code", "second-display", time.time()),
        ]
        api.login_status.return_value = ("expired", None)
        with patch("wx_clawbot.channels.login.WechatApi", return_value=api):
            result = await login(self.root, emit=lambda *a, **kw: None)
            self.assertEqual(result["status"], "expired")
            result = await login(self.root, emit=lambda *a, **kw: None)
            self.assertTrue(result["refresh_required"])
            self.assertEqual(api.start_login.await_count, 1)
            await login(self.root, fresh=True, emit=lambda *a, **kw: None)
        self.assertEqual(api.start_login.await_count, 2)
        self.assertFalse((self.root / "credentials.json").exists())

    async def test_echo_only_accepts_explicit_challenge_and_records_two_distinct_inputs(self):
        save_credentials(self.root / "credentials.json", self.account)
        confirm_owner(self.root, owner_fingerprint(self.account))
        challenge = "WX-TEST-12345678"
        first = message(1, text=challenge)
        second = message(2, text=challenge)
        personal = message(3, text="not a test challenge")
        api = AsyncMock()
        api.updates.side_effect = [
            {"ret": 0, "get_updates_buf": "cursor-a", "msgs": [first, personal]},
            {"ret": 0, "get_updates_buf": "cursor-b", "msgs": [first, second]},
        ]
        api.send_text.return_value = {"ret": 0}
        with patch("wx_clawbot.channels.diagnostics.WechatApi", return_value=api):
            result = await echo(self.root, challenge=challenge, count=2, timeout=2)
        self.assertEqual(result["sent_accepted"], 2)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["context_present"], 2)
        self.assertTrue(result["cursor_advanced"])
        self.assertNotIn("phone_received", result)
        self.assertEqual(api.send_text.await_count, 2)
        self.assertNotEqual(api.send_text.await_args_list[0].kwargs["client_id"],
                            api.send_text.await_args_list[1].kwargs["client_id"])
