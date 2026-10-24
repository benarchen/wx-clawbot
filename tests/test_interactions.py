import asyncio
import copy
import unittest
from unittest.mock import AsyncMock

from wx_clawbot.interactions import APPROVAL, QUESTION, InteractionBroker


def approval(request_id=1):
    return {"id": request_id, "method": APPROVAL, "params": {
        "threadId": "thread-a", "turnId": "turn-a", "itemId": "item-a",
        "command": "printf fixture", "availableDecisions": ["accept", "cancel"],
    }}


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.0
        self.rpc = AsyncMock()
        self.broker = InteractionBroker(self.rpc, "thread-a", clock=lambda: self.now, ttl=10)

    async def answer(self, record, value, **overrides):
        return await self.broker.answer(record.public_id, value, **{
            "generation": self.broker.generation, "thread_id": "thread-a", **overrides})

    async def test_concurrent_opposite_answers_send_only_once_without_claiming_winner(self):
        record = self.broker.register(approval())
        results = await asyncio.gather(self.answer(record, "accept"), self.answer(record, "cancel"),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.rpc.respond.assert_awaited_once_with(1, {"decision": "accept"})
        self.assertEqual(record.state, "awaiting_native")
        self.broker.resolved({"method": "serverRequest/resolved", "params": {
            "threadId": "thread-a", "requestId": 1}})
        self.assertEqual(record.state, "resolved")

    async def test_desktop_resolution_prevents_bridge_answer(self):
        record = self.broker.register(approval("1"))
        self.assertIsNone(self.broker.resolved({"method": "serverRequest/resolved", "params": {
            "threadId": "other", "requestId": "1"}}))
        self.broker.resolved({"method": "serverRequest/resolved", "params": {
            "threadId": "thread-a", "requestId": "1"}})
        with self.assertRaises(ValueError):
            await self.answer(record, "accept")
        self.rpc.respond.assert_not_awaited()

    async def test_expiry_disconnect_and_wrong_binding_never_send(self):
        record = self.broker.register(approval())
        for overrides in ({"thread_id": "other"}, {"generation": "old"}):
            with self.assertRaises(ValueError):
                await self.answer(record, "accept", **overrides)
        self.now = record.deadline
        with self.assertRaisesRegex(ValueError, "expired"):
            await self.answer(record, "accept")
        self.assertEqual(record.state, "stale")
        another = self.broker.register(approval(2))
        self.broker.disconnect()
        with self.assertRaises(ValueError):
            await self.answer(another, "accept")
        self.rpc.respond.assert_not_awaited()

    async def test_uncertain_send_cannot_be_replied_to_again(self):
        record = self.broker.register(approval())
        self.rpc.respond.side_effect = ConnectionError("send outcome unknown")
        with self.assertRaises(ConnectionError):
            await self.answer(record, "accept")
        self.assertEqual(record.state, "unknown")
        with self.assertRaises(ValueError):
            await self.answer(record, "cancel")
        self.assertEqual(self.rpc.respond.await_count, 1)

    async def test_native_resolution_during_send_is_not_overwritten(self):
        record = self.broker.register(approval())
        async def resolved(*args):
            self.broker.resolved({"method": "serverRequest/resolved", "params": {
                "threadId": "thread-a", "requestId": 1}})
        self.rpc.respond.side_effect = resolved
        await self.answer(record, "accept")
        self.assertEqual(record.state, "resolved")

    async def test_permanent_grants_and_unoffered_actions_rejected(self):
        record = self.broker.register(approval())
        for value in ("acceptForSession", "decline", {"acceptWithExecpolicyAmendment": {}}, True):
            with self.assertRaises(ValueError):
                await self.answer(record, value)
        self.rpc.respond.assert_not_awaited()
        self.assertEqual(record.state, "pending")

    def test_typed_ids_and_reused_id_payload_rejected(self):
        event = approval()
        first = self.broker.register(event)
        self.assertIs(first, self.broker.register(copy.deepcopy(event)))
        second = self.broker.register(approval("1"))
        self.assertNotEqual(first.public_id, second.public_id)
        event["params"]["turnId"] = "different"
        with self.assertRaises(ValueError):
            self.broker.register(event)
        self.assertEqual(first.turn_id, "turn-a")

    async def test_multiple_questions_free_text_and_invalid_answers(self):
        event = {"id": 5, "method": QUESTION, "params": {
            "threadId": "thread-a", "turnId": "turn-a", "itemId": "question-a",
            "questions": [{"id": "choice", "options": [{"label": "A"}, {"label": "B"}]},
                          {"id": "note", "options": None}],
        }}
        record = self.broker.register(event)
        for value in ({"choice": ["A"]}, {"choice": ["UNKNOWN"], "note": ["text"]},
                      {"choice": ["A", "B"], "note": ["text"]},
                      {"choice": ["A"], "note": [""]}):
            with self.assertRaises(ValueError):
                await self.answer(record, value)
        await self.answer(record, {"choice": ["B"], "note": ["a free response"]})
        self.rpc.respond.assert_awaited_once_with(5, {"answers": {
            "choice": {"answers": ["B"]}, "note": {"answers": ["a free response"]}}})

    def test_unsupported_or_cross_thread_requests_never_register(self):
        for event in ({"id": 1, "method": "unknown", "params": {}},
                      {"id": True, "method": APPROVAL, "params": {}},
                      {"id": 1, "method": APPROVAL, "params": {"threadId": "other"}}):
            with self.assertRaises((ValueError, ConnectionError)):
                self.broker.register(event)
        self.assertFalse(self.broker.records)
