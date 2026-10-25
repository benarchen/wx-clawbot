import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.state import ChannelState
from wx_clawbot.channels.wechat import Credentials, DeliveryUnknown
from wx_clawbot.delivery import Sender
from wx_clawbot.runtime_state import RuntimeState
from test_wechat_state import message


class RuntimeFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp" / "runtime-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.credentials = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")
        self.state = await RuntimeState.open(self.root / "runtime.sqlite3", self.credentials)
        self.addAsyncCleanup(self.state.close)

    async def admit(self, native_id=1):
        await self.state.accept_batch({"ret": 0, "msgs": [message(native_id)]}, phase="runtime")
        return await self.state.task_intent(str(native_id), {"thread_id": "fixture-thread", "session_id": "fixture-session"}, "task")

    async def restart(self):
        await self.state.close()
        self.state = await RuntimeState.open(self.root / "runtime.sqlite3", self.credentials)
        self.addAsyncCleanup(self.state.close)


class RuntimeTests(RuntimeFixture):
    async def test_only_fresh_owner_message_can_be_admitted_and_identity_cannot_be_retargeted(self):
        with self.assertRaises(ProtocolError):
            await self.state.task_intent("1", {"thread_id": "fixture-thread"}, "task")
        first = await self.admit()
        self.assertIsNone(await self.state.task_intent("1", {"session_id": "fixture-session", "thread_id": "fixture-thread"}, "task"))
        with self.assertRaises(ProtocolError):
            await self.state.task_intent("1", {"thread_id": "another-thread"}, "task")
        await self.restart()
        self.assertEqual((await self.state.tasks(task_id=first["id"]))["state"], "unknown")
        self.assertIsNone(await self.state.task_intent("1", {"thread_id": "fixture-thread", "session_id": "fixture-session"}, "task"))

    async def test_restart_never_replays_unprocessed_inbox_or_unknown_sends(self):
        await self.state.accept_batch({"ret": 0, "msgs": [message(7)]}, phase="runtime")
        await self.state.queue_reply("event-1", "reply")
        claimed = await self.state.claim_reply()
        self.assertIsNotNone(claimed)
        await self.restart()
        self.assertIsNone(await self.state.claim_reply())
        self.assertEqual(await self.state.delivery_counts(), {"unknown": 1})
        with self.assertRaises(ProtocolError):
            await self.state.task_intent("7", {"thread_id": "fixture-thread"}, "task")

    async def test_terminal_and_final_reply_commit_or_rollback_together(self):
        task = await self.admit()
        await self.state._call(lambda: self.state.db.execute("""CREATE TRIGGER fail_reply BEFORE INSERT ON outbox
            BEGIN SELECT RAISE(ABORT,'injected storage failure'); END"""))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.task_finish(task["id"], "completed", "result")
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "prepared")
        self.assertEqual(await self.state.delivery_counts(), {})

    async def test_final_supersedes_unsent_progress_and_late_acceptance_cannot_overtake_it(self):
        task = await self.admit()
        await self.state.queue_reply("ack", "queued", task_id=task["id"], kind="accepted")
        self.assertTrue(await self.state.task_finish(task["id"], "completed", "result"))
        self.assertFalse(await self.state.queue_reply("late-ack", "queued", task_id=task["id"], kind="accepted"))
        self.assertFalse(await self.state.task_finish(task["id"], "failed", "conflicting late result"))
        self.assertEqual((await self.state.claim_reply())["text"], "result")
        self.assertEqual(await self.state.delivery_counts(), {"sending": 1, "superseded": 1})

    async def test_long_result_is_preserved_in_order_without_rerunning_task(self):
        task = await self.admit()
        text = "甲" * 8000 + "乙" * 8000
        await self.state.task_finish(task["id"], "completed", text)
        parts = []
        for index in range(3):
            reply = await self.state.claim_reply()
            self.assertTrue(reply["text"].startswith(f"〔{index+1}/3〕\n"))
            parts.append(reply["text"].split("\n", 1)[1])
            await self.state.finish_reply(reply["id"], "accepted", index + 1)
        self.assertEqual("".join(parts), text)
        self.assertIsNone(await self.state.claim_reply())

    async def test_diagnostic_and_runtime_cannot_poll_same_binding_concurrently(self):
        with self.assertRaisesRegex(ProtocolError, "already owns"):
            await ChannelState.open(self.root / "state.sqlite3", self.credentials)

    async def test_seed_transfers_only_cursor_and_context_without_importing_diagnostic_tasks(self):
        # Separate new directory: the old diagnostic file is not a schema-migration target.
        root = self.root / "seed"
        old = await ChannelState.open(root / "state.sqlite3", self.credentials)
        await old.accept_batch({"ret": 0, "msgs": [message(10)], "get_updates_buf": "saved-cursor"})
        await old.close()
        original = (root / "state.sqlite3").read_bytes()
        new = await RuntimeState.open(root / "runtime.sqlite3", self.credentials)
        try:
            self.assertEqual(await new.cursor(), "saved-cursor")
            self.assertEqual(await new.latest_context(), "context-new")
            self.assertEqual(await new.tasks(), [])
            count = await new._call(lambda: new.db.execute("SELECT count(*) FROM inbox").fetchone()[0])
            self.assertEqual(count, 0)
        finally:
            await new.close()
        self.assertEqual((root / "state.sqlite3").read_bytes(), original)

    async def test_unknown_delivery_has_no_automatic_send_retry_and_no_task_dependency(self):
        await self.state.accept_batch({"ret": 0, "msgs": [message()]}, phase="runtime")
        await self.state.queue_reply("event", "reply")
        api = SimpleNamespace(send_text=AsyncMock(side_effect=DeliveryUnknown("lost ACK")))
        sender = Sender(self.state, api)
        self.assertTrue(await sender.once())
        self.assertFalse(await sender.once())
        self.assertEqual(api.send_text.await_count, 1)
        self.assertEqual(await self.state.delivery_counts(), {"unknown": 1})
        self.assertEqual(await self.state.tasks(), [])

    async def test_unbound_context_waits_and_uses_latest_confirmed_owner_context(self):
        await self.state.queue_reply("event", "reply")
        self.assertIsNone(await self.state.claim_reply())
        await self.state.accept_batch({"ret": 0, "msgs": [message(context="fresh")]}, phase="runtime")
        self.assertEqual((await self.state.claim_reply())["context"], "fresh")

    async def test_pruned_body_keeps_message_deduplication_and_conflict_detection(self):
        await self.state.accept_batch({"ret": 0, "msgs": [message()]}, phase="runtime")
        await self.state._call(lambda: self.state.db.execute("UPDATE inbox SET text='' WHERE message_id='1'"))
        replay = await self.state.accept_batch({"ret": 0, "msgs": [message()]}, phase="runtime")
        self.assertEqual(replay["duplicates"], 1)
        self.assertEqual(replay["conflicts"], 0)
        self.assertFalse(replay["accepted"])
        changed = await self.state.accept_batch({"ret": 0, "msgs": [message(text="changed")]}, phase="runtime")
        self.assertEqual(changed["conflicts"], 1)
        self.assertFalse(changed["accepted"])
