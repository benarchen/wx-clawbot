import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.agents.rpc import OutcomeUnknown


class NativeQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "queue-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.connection = AsyncMock()
        self.connection.inspect.return_value = {"cwd": str(self.project), "status": {"type": "active"}}
        self.items = []
        self.calls = []
        self.connection.rpc.request.side_effect = self.peer
        self.queue = NativeQueue(self.connection, "thread-a", self.project)

    async def peer(self, method, params):
        self.calls.append((method, params))
        self.assertEqual(params["threadId"], "thread-a")
        if method == "thread/queue/list":
            return {"data": list(self.items), "nextCursor": None}
        if method == "thread/queue/add":
            item = {"id": "queue-1", "clientUserMessageId": params["clientUserMessageId"]}
            self.items.append(item)
            return {"queuedSubmission": item}
        if method == "thread/queue/delete":
            self.items = [item for item in self.items if item["id"] != params["queuedSubmissionId"]]
            return {"deleted": True}
        if method == "thread/turns/list":
            return {"data": [{"id": "turn-running", "status": "inProgress"}]}
        if method == "turn/interrupt":
            return {}
        raise AssertionError(method)

    async def test_busy_input_is_queued_and_existing_submission_is_not_resubmitted(self):
        item = await self.queue.add("a real task", "client-1")
        self.assertEqual(item["clientUserMessageId"], "client-1")
        with self.assertRaisesRegex(ValueError, "already queued"):
            await self.queue.add("changed task", "client-1")
        self.assertEqual(sum(method == "thread/queue/add" for method, _ in self.calls), 1)

    async def test_full_queue_rejects_without_add(self):
        self.items = [{"id": str(i), "clientUserMessageId": "client-" + str(i)} for i in range(10)]
        with self.assertRaisesRegex(ValueError, "full"):
            await self.queue.add("eleventh task", "client-11")
        self.assertFalse(any(method == "thread/queue/add" for method, _ in self.calls))

    async def test_cancel_requires_matching_native_queue_identity(self):
        await self.queue.add("task", "client-1")
        self.assertTrue(await self.queue.delete("queue-1"))
        self.assertFalse(await self.queue.delete("queue-1"))
        self.assertEqual(sum(method == "thread/queue/delete" for method, _ in self.calls), 1)

    async def test_wrong_project_or_unloaded_thread_never_queues(self):
        for thread in ({"cwd": str(self.project.parent), "status": {"type": "active"}},
                       {"cwd": str(self.project), "status": {"type": "notLoaded"}}):
            self.connection.inspect.return_value = thread
            with self.assertRaises(ValueError):
                await self.queue.add("task", "client-1")
        self.connection.rpc.request.assert_not_awaited()

    async def test_unknown_add_outcome_is_not_replayed(self):
        async def lost(method, params):
            if method == "thread/queue/add":
                raise OutcomeUnknown("accepted but receipt lost")
            return await self.peer(method, params)
        self.connection.rpc.request.side_effect = lost
        with self.assertRaises(OutcomeUnknown):
            await self.queue.add("task", "client-1")
        self.assertEqual(sum(call.args[0] == "thread/queue/add"
                             for call in self.connection.rpc.request.await_args_list), 1)

    async def test_interrupt_is_independent_of_a_blocked_ordinary_submission(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_add(method, params):
            if method == "thread/queue/add":
                entered.set()
                await release.wait()
            return await self.peer(method, params)
        self.connection.rpc.request.side_effect = slow_add
        task = asyncio.create_task(self.queue.add("task", "client-1"))
        try:
            await asyncio.wait_for(entered.wait(), .5)
            receipt = await asyncio.wait_for(self.queue.request_interrupt("turn-running"), .5)
            self.assertEqual(receipt, {})  # Not a claim that execution has stopped.
            self.assertFalse(task.done())
        finally:
            release.set()
            await task

    async def test_wrong_active_turn_is_not_interrupted(self):
        with self.assertRaises(ValueError):
            await self.queue.request_interrupt("turn-old")
        self.assertFalse(any(method == "turn/interrupt" for method, _ in self.calls))

    async def test_invalid_snapshot_and_receipt_fail_closed(self):
        self.connection.rpc.request.side_effect = None
        for result in ({"data": [], "nextCursor": "more"}, {"data": [{}]},
                       {"data": [{"id": "same", "clientUserMessageId": "a"},
                                 {"id": "same", "clientUserMessageId": "b"}]}):
            self.connection.rpc.request.return_value = result
            with self.assertRaises(ValueError):
                await self.queue.list()
