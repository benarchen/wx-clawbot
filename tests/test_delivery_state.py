import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_runtime_state import RuntimeFixture
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.wechat import DeliveryUnknown
from wx_clawbot.delivery import Sender


class DeliveryStateTests(RuntimeFixture):
    async def test_unknown_requires_explicit_retry_and_never_changes_execution(self):
        task = await self.admit()
        await self.state.task_finish(task["id"], "completed", "original result")
        before = await self.state.tasks()
        api = SimpleNamespace(send_text=AsyncMock(side_effect=[DeliveryUnknown("lost ACK"), {"ret": 0, "message_id": 7}]))
        sender = Sender(self.state, api)
        self.assertTrue(await sender.once())
        self.assertFalse(await sender.once())
        with self.assertRaises(ProtocolError):
            await self.state.retry_reply(task["id"] + "-final-1")
        self.assertEqual(api.send_text.await_count, 1)
        await self.state.retry_reply(task["id"] + "-final-1", confirm_unknown=True)
        self.assertTrue(await sender.once())
        self.assertEqual(await self.state.tasks(), before)
        attempts = await self.state.delivery_attempts(task["id"] + "-final-1")
        self.assertEqual([a["state"] for a in attempts], ["unknown", "accepted"])
        self.assertEqual(attempts[1]["authorization"], "operator_confirmed_possible_duplicate")
        self.assertNotEqual(attempts[0]["client_id"], attempts[1]["client_id"])
        self.assertEqual([call.kwargs["text"] for call in api.send_text.await_args_list], ["original result"] * 2)

    async def test_attempt_intent_failure_prevents_http_send(self):
        await self.admit()
        await self.state.queue_reply("event", "reply")
        await self.state._call(lambda: self.state.db.execute("""CREATE TRIGGER reject_attempt BEFORE INSERT ON delivery_attempts
            BEGIN SELECT RAISE(ABORT,'injected disk failure'); END"""))
        api = SimpleNamespace(send_text=AsyncMock())
        with self.assertRaises(sqlite3.IntegrityError):
            await Sender(self.state, api).once()
        api.send_text.assert_not_awaited()
        self.assertEqual(await self.state.delivery_counts(), {"pending": 1})
        self.assertEqual(await self.state.delivery_attempts("event"), [])

    async def test_attempt_and_outbox_outcome_rollback_together(self):
        await self.admit()
        await self.state.queue_reply("event", "reply")
        await self.state.claim_reply()
        await self.state._call(lambda: self.state.db.execute("""CREATE TRIGGER reject_finish BEFORE UPDATE ON delivery_attempts
            BEGIN SELECT RAISE(ABORT,'injected disk failure'); END"""))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.finish_reply("event", "accepted", 7)
        self.assertEqual(await self.state.delivery_counts(), {"sending": 1})
        self.assertEqual((await self.state.delivery_attempts("event"))[0]["state"], "sending")

    async def test_prepared_retry_survives_restart_but_uncertain_attempt_does_not_replay(self):
        await self.admit()
        await self.state.queue_reply("event", "reply")
        await self.state.claim_reply()
        await self.state.finish_reply("event", "rejected")
        await self.state.retry_reply("event")
        await self.restart()
        api = SimpleNamespace(send_text=AsyncMock(return_value={"ret": 0}))
        self.assertTrue(await Sender(self.state, api).once())
        self.assertEqual([a["state"] for a in await self.state.delivery_attempts("event")], ["rejected", "accepted"])
        self.assertEqual(api.send_text.await_count, 1)

    async def test_retry_is_bounded_and_double_retry_cannot_enqueue_two_attempts(self):
        await self.admit()
        await self.state.queue_reply("event", "reply")
        for number in range(3):
            if number:
                await self.state.retry_reply("event")
                with self.assertRaises(ProtocolError):
                    await self.state.retry_reply("event")
            claimed = await self.state.claim_reply()
            self.assertEqual(claimed["attempt"], number)
            await self.state.finish_reply("event", "rejected")
        with self.assertRaises(ProtocolError):
            await self.state.retry_reply("event")
        self.assertEqual(len(await self.state.delivery_attempts("event")), 3)

    async def test_fifo_does_not_change_if_wall_clock_moves_backwards(self):
        await self.admit()
        with patch("wx_clawbot.runtime_state.time.time", return_value=200):
            await self.state.queue_reply("first", "first reply")
        with patch("wx_clawbot.runtime_state.time.time", return_value=100):
            await self.state.queue_reply("second", "second reply")
        first = await self.state.claim_reply()
        self.assertEqual(first["id"], "first")
        await self.state.finish_reply(first["id"], "accepted")
        self.assertEqual((await self.state.claim_reply())["id"], "second")
