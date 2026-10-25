import sqlite3

from test_runtime_state import RuntimeFixture
from test_wechat_state import message
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.retention import maintain


NOW = 2000000000


class RetentionTests(RuntimeFixture):
    async def aged(self, days, *, unsettled=False):
        task = await self.admit()
        await self.state.handled("1")
        await self.state.task_finish(task["id"], "completed", "retained result")
        reply = await self.state.claim_reply()
        await self.state.finish_reply(reply["id"], "unknown" if unsettled else "accepted", 7)
        age = NOW - days * 86400
        def age_rows():
            for table, column in (("tasks", "updated_at"), ("inbox", "received_at"), ("outbox", "created_at")):
                self.state.db.execute(f"UPDATE {table} SET {column}=?", (age,))
        await self.state._call(age_rows)
        return task

    async def test_default_plan_never_changes_live_rows_or_requires_stopping_reader(self):
        await self.aged(14)
        before = await self.state.tasks()
        plan = maintain(self.root, self.credentials, now=NOW)
        self.assertFalse(plan["applied"])
        self.assertEqual(plan["eligible_rows"]["task_inputs"], 1)
        self.assertEqual(await self.state.tasks(), before)
        with self.assertRaises(ProtocolError):
            maintain(self.root, self.credentials, apply=True, now=NOW)

    async def test_body_cleanup_preserves_exact_id_deduplication_and_reply_idempotence(self):
        task = await self.aged(14)
        await self.state.close()
        report = maintain(self.root, self.credentials, apply=True, now=NOW)
        self.assertEqual(report["changed_rows"]["task_inputs"], 1)
        await self.restart()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["input"], "")
        replay = await self.state.accept_batch({"ret": 0, "msgs": [message()]}, phase="runtime")
        self.assertEqual(replay["duplicates"], 1)
        self.assertFalse(replay["accepted"])
        self.assertFalse(await self.state.queue_reply(task["id"] + "-final-1", "retained result"))
        with self.assertRaises(ProtocolError):
            await self.state.queue_reply(task["id"] + "-final-1", "different content")

    async def test_unknown_delivery_keeps_critical_result_context_and_task_even_after_thirty_days(self):
        task = await self.aged(60, unsettled=True)
        await self.state.close()
        maintain(self.root, self.credentials, apply=True, now=NOW)
        await self.restart()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["input"], "task")
        row = await self.state._call(lambda: self.state.db.execute("SELECT text,context,state FROM outbox").fetchone())
        self.assertEqual(row, ("retained result", "context-new", "unknown"))
        self.assertIsNone(await self.state.claim_reply())

    async def test_old_settled_summaries_are_removed_but_source_tombstone_prevents_reexecution(self):
        await self.aged(60)
        await self.state.close()
        maintain(self.root, self.credentials, apply=True, now=NOW)
        await self.restart()
        self.assertEqual(await self.state.tasks(), [])
        self.assertEqual(await self.state.delivery_counts(), {})
        replay = await self.state.accept_batch({"ret": 0, "msgs": [message()]}, phase="runtime")
        self.assertFalse(replay["accepted"])
        with self.assertRaises(ProtocolError):
            await self.state.task_intent("1", {"thread_id": "fixture-thread"}, "task")

    async def test_cleanup_storage_failure_rolls_back_all_earlier_body_changes(self):
        task = await self.aged(14)
        await self.state._call(lambda: self.state.db.execute("""CREATE TRIGGER reject_cleanup BEFORE UPDATE ON outbox
            BEGIN SELECT RAISE(ABORT,'injected disk failure'); END"""))
        await self.state.close()
        with self.assertRaises(sqlite3.IntegrityError):
            maintain(self.root, self.credentials, apply=True, now=NOW)
        await self.restart()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["input"], "task")
        text = await self.state._call(lambda: self.state.db.execute("SELECT text FROM inbox").fetchone()[0])
        self.assertNotEqual(text, "")
