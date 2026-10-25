import sqlite3
import tempfile
import unittest
from pathlib import Path

from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.interactions import APPROVAL, Interaction
from wx_clawbot.runtime_state import RuntimeState


class RecoveryStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp" / "recovery-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime.sqlite3"
        self.credentials = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")
        self.state = await RuntimeState.open(self.path, self.credentials)
        self.addAsyncCleanup(self.state.close)
        self.target = {"thread_id": "fixture-thread", "session_id": "fixture-session"}

    def interaction(self, public_id="r-aaaa", native_id=7):
        return Interaction(public_id, native_id, "fixture-thread", "fixture-turn", APPROVAL,
                           {"command": "fixture operation"}, 600)

    async def persist(self, record, generation="fixture-generation"):
        return await self.state.record_interaction(record, generation=generation, target=self.target, expires_at=2000000000)

    async def test_route_snapshot_survives_restart_and_failed_write_keeps_old_snapshot(self):
        original = {"target": "fixture-session", "revision": 1}
        await self.state.save_routes(original)
        await self.state._call(lambda: self.state.db.execute("""CREATE TRIGGER reject_route BEFORE UPDATE ON routes
            BEGIN SELECT RAISE(ABORT,'injected disk failure'); END"""))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.save_routes({"target": "another-session", "revision": 2})
        await self.state.close()
        self.state = await RuntimeState.open(self.path, self.credentials)
        self.addAsyncCleanup(self.state.close)
        self.assertEqual(await self.state.load_routes(), original)

    async def test_interaction_cannot_be_retargeted_or_change_displayed_operation(self):
        record = self.interaction()
        await self.persist(record)
        record.params = {"command": "changed operation"}
        with self.assertRaises(ProtocolError):
            await self.persist(record)
        self.assertEqual((await self.state.interaction_rows())[0]["state"], "pending")

    async def test_numeric_and_string_native_ids_remain_distinct(self):
        await self.persist(self.interaction("r-aaaa", 7))
        await self.persist(self.interaction("r-bbbb", "7"))
        rows = await self.state._call(lambda: list(self.state.db.execute("SELECT native_key FROM interactions ORDER BY public_id")))
        self.assertNotEqual(rows[0], rows[1])

    async def test_resolved_native_request_cannot_be_revived_by_late_sending_write(self):
        record = self.interaction()
        await self.persist(record)
        record.state = "resolved"
        await self.persist(record)
        record.state = "sending"
        self.assertEqual(await self.persist(record), "resolved")
        self.assertEqual((await self.state.interaction_rows())[0]["state"], "resolved")

    async def test_staling_one_generation_keeps_other_generation_prompt(self):
        await self.persist(self.interaction("r-aaaa"), "generation-a")
        await self.persist(self.interaction("r-bbbb"), "generation-b")
        await self.state.queue_reply("r-aaaa-prompt", "operation A")
        await self.state.queue_reply("r-bbbb-prompt", "operation B")
        await self.state.stale_interactions("generation-a")
        self.assertEqual((await self.state.interaction_rows(generation="generation-a"))[0]["state"], "stale")
        self.assertEqual((await self.state.interaction_rows(generation="generation-b"))[0]["state"], "pending")
        self.assertEqual(await self.state.delivery_counts(), {"pending": 1, "superseded": 1})

    async def test_restart_stales_pending_interactions_and_legacy_prompts_without_answering(self):
        await self.persist(self.interaction())
        await self.state.queue_reply("r-aaaa-prompt", "current prompt")
        await self.state.queue_reply("r-bbbb-prompt", "legacy prompt without interaction row")
        await self.state.close()
        self.state = await RuntimeState.open(self.path, self.credentials)
        self.addAsyncCleanup(self.state.close)
        self.assertEqual((await self.state.interaction_rows())[0]["state"], "stale")
        self.assertEqual(await self.state.delivery_counts(), {"superseded": 2})

    async def test_stale_request_can_only_advance_to_native_resolved(self):
        record = self.interaction()
        await self.persist(record)
        await self.state.stale_interactions("fixture-generation")
        record.state = "pending"
        self.assertEqual(await self.persist(record), "stale")
        record.state = "resolved"
        self.assertEqual(await self.persist(record), "resolved")

    async def test_uncertain_answer_cannot_be_reopened_for_an_opposite_decision(self):
        record = self.interaction()
        await self.persist(record)
        record.state = "unknown"
        await self.persist(record)
        record.state = "pending"
        self.assertEqual(await self.persist(record), "unknown")
        record.state = "resolved"
        self.assertEqual(await self.persist(record), "resolved")
