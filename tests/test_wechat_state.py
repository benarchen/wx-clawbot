import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.messages import parse_text
from wx_clawbot.channels.private import load_credentials, save_credentials
from wx_clawbot.channels.state import ChannelState
from wx_clawbot.channels.wechat import Credentials


def message(native_id=1, *, text="same text", context="context-new", created=100):
    return {"message_id": native_id, "from_user_id": "fixture-owner", "to_user_id": "fixture-bot",
            "message_type": 1, "message_state": 2, "create_time_ms": created, "seq": created,
            "context_token": context, "item_list": [{"type": 1, "text_item": {"text": text}}]}


class StateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "wechat-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")
        self.path = self.root / "state.sqlite3"
        self.state = await ChannelState.open(self.path, self.account)
        self.addAsyncCleanup(self.state.close)

    async def test_same_text_different_ids_both_arrive_but_replayed_ids_do_not(self):
        batch = {"ret": 0, "get_updates_buf": "cursor-1", "msgs": [message(1), message(2)]}
        result = await self.state.accept_batch(batch)
        self.assertEqual(len(result["accepted"]), 2)
        self.assertEqual(await self.state.cursor(), "cursor-1")
        result = await self.state.accept_batch(batch)
        self.assertEqual(result["duplicates"], 2)
        self.assertFalse(result["accepted"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    async def test_unknown_identity_unsupported_media_and_missing_ids_never_enter_inbox(self):
        samples = []
        for field, value in (("from_user_id", "stranger"), ("to_user_id", "another-bot"),
                             ("group_id", "fixture-group"), ("message_id", None),
                             ("message_type", True), ("message_state", 1),
                             ("item_list", [{"type": 2}]), ("seq", 2**63)):
            raw = message();raw[field] = value;samples.append(raw)
        result = await self.state.accept_batch({"ret": 0, "get_updates_buf": "next", "msgs": samples})
        self.assertFalse(result["accepted"])
        self.assertEqual(sum(result["rejected"].values()), len(samples))
        self.assertEqual(await self.state.cursor(), "next")

    async def test_cursor_and_inbox_rollback_together_on_mid_batch_storage_failure(self):
        await self.state._call(lambda: self.state.db.execute("""CREATE TRIGGER fail_second BEFORE INSERT ON inbox
            WHEN NEW.message_id='2' BEGIN SELECT RAISE(ABORT,'injected storage failure'); END"""))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.accept_batch({"ret": 0, "get_updates_buf": "must-not-commit", "msgs": [message(1), message(2)]})
        self.assertEqual(await self.state.cursor(), "")
        count = await self.state._call(lambda: self.state.db.execute("SELECT count(*) FROM inbox").fetchone()[0])
        self.assertEqual(count, 0)

    async def test_older_or_duplicate_message_cannot_replace_newer_reply_context(self):
        await self.state.accept_batch({"ret": 0, "msgs": [message(1, created=200, context="new")]})
        await self.state.accept_batch({"ret": 0, "msgs": [message(2, created=100, context="old")]})
        await self.state.accept_batch({"ret": 0, "msgs": [message(1, created=300, context="replay")]})
        self.assertEqual(await self.state.latest_context(), "new")
        self.assertEqual(await self.state.cursor(), "")

    async def test_unknown_delivery_is_durable_and_not_reissued_with_a_new_client_id(self):
        result = await self.state.accept_batch({"ret": 0, "msgs": [message(1)]})
        incoming = result["accepted"][0]
        self.assertTrue(await self.state.begin_send("delivery-1", incoming, "echo"))
        await self.state.finish_send("delivery-1", "unknown")
        await self.state.close()
        self.state = await ChannelState.open(self.path, self.account)
        self.addAsyncCleanup(self.state.close)
        self.assertFalse(await self.state.begin_send("delivery-2", incoming, "echo"))
        with self.assertRaises(ProtocolError):
            await self.state.finish_send("delivery-1", "accepted")

    async def test_changed_body_under_existing_id_marks_conflict_and_refuses_reply(self):
        await self.state.accept_batch({"ret": 0, "msgs": [message(1)]})
        result = await self.state.accept_batch({"ret": 0, "msgs": [message(1, text="different")]})
        self.assertEqual(result["conflicts"], 1)
        incoming, _ = parse_text(message(1), self.account)
        with self.assertRaises(ProtocolError):
            await self.state.begin_send("delivery-1", incoming, "echo")

    async def test_existing_database_binding_mismatch_does_not_overwrite_owner(self):
        await self.state.close()
        other = Credentials("fixture-bot", "other-owner", self.account.base, "another-token")
        with self.assertRaises(ProtocolError):
            await ChannelState.open(self.path, other)
        self.state = await ChannelState.open(self.path, self.account)
        self.addAsyncCleanup(self.state.close)
        owner = await self.state._call(lambda: self.state.db.execute("SELECT owner FROM channel").fetchone()[0])
        self.assertEqual(owner, "fixture-owner")

    async def test_two_consumers_cannot_share_the_same_private_channel_state(self):
        with self.assertRaisesRegex(ProtocolError, "already owns"):
            await ChannelState.open(self.path, self.account)

    async def test_unrelated_sqlite_database_is_not_migrated_or_cleared(self):
        path = self.root / "foreign.sqlite3"
        db = sqlite3.connect(path);db.execute("CREATE TABLE personal(value TEXT)");db.commit();db.close();path.chmod(0o600)
        with self.assertRaises(ProtocolError):
            await ChannelState.open(path, self.account)
        db = sqlite3.connect(path)
        try:self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("personal",)])
        finally:db.close()

    def test_credentials_are_private_unconfirmed_and_never_overwrite_an_existing_binding(self):
        path = self.root / "credentials.json"
        save_credentials(path, self.account)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ProtocolError):
            load_credentials(path)
        self.assertEqual(load_credentials(path, require_confirmed=False), self.account)
        with self.assertRaises(FileExistsError):
            save_credentials(path, self.account)
        alias = self.root / "alias.json";alias.symlink_to(path)
        with self.assertRaises(ProtocolError):
            load_credentials(alias, require_confirmed=False)

    def test_uint64_message_identity_is_lossless_and_booleans_are_rejected(self):
        integer, _ = parse_text(message(2**64 - 1), self.account)
        string, _ = parse_text(message(str(2**64 - 1)), self.account)
        self.assertEqual(integer.message_id, string.message_id)
        self.assertEqual(integer.message_id, "18446744073709551615")
        self.assertIsNone(parse_text(message(True), self.account)[0])
