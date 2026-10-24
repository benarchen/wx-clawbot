"""In-memory protocol peer tests. These do not validate real terminal behavior."""

import asyncio
import json
import unittest

from wx_clawbot.agents.rpc import ConnectionLost, JsonRpc, OutcomeUnknown, RpcError


class MemoryTransport:
    def __init__(self, reader):
        self.reader = reader
        self.sent = asyncio.Queue()
        self.closed = False

    async def send(self, data):
        self.sent.put_nowait(json.loads(data))

    async def recv(self):
        return await self.reader.readline()

    async def close(self):
        self.closed = True


class RpcTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reader = asyncio.StreamReader()
        self.writer = MemoryTransport(self.reader)
        self.rpc = JsonRpc(self.writer, event_limit=2)
        self.addAsyncCleanup(self.rpc.close)

    def reply(self, message):
        self.reader.feed_data((json.dumps(message) + "\n").encode())

    async def test_out_of_order_responses_are_correlated(self):
        first = asyncio.create_task(self.rpc.request("first", {}))
        second = asyncio.create_task(self.rpc.request("second", {}))
        a, b = await self.writer.sent.get(), await self.writer.sent.get()
        self.reply({"id": b["id"], "result": "B"})
        self.reply({"method": "turn/started", "params": {"threadId": "fixture"}})
        self.reply({"id": a["id"], "result": "A"})
        self.assertEqual(await asyncio.gather(first, second), ["A", "B"])
        self.assertEqual((await self.rpc.next_event())["method"], "turn/started")

    async def test_string_and_integer_request_ids_remain_distinct(self):
        task = asyncio.create_task(self.rpc.request("fixture", {}, timeout=0.2))
        request = await self.writer.sent.get()
        self.reply({"id": str(request["id"]), "result": "wrong"})
        self.reply({"id": request["id"], "result": "right"})
        self.assertEqual(await task, "right")
        self.assertNotEqual(JsonRpc.key(1), JsonRpc.key("1"))
        with self.assertRaises(ConnectionLost):
            JsonRpc.key(True)

    async def test_server_request_is_not_mistaken_for_response(self):
        self.reply({"id": "approval", "method": "item/commandExecution/requestApproval", "params": {}})
        event = await self.rpc.next_event()
        self.assertEqual(event["id"], "approval")
        self.assertTrue(self.writer.sent.empty())

    async def test_timeout_is_unknown_without_replay(self):
        task = asyncio.create_task(self.rpc.request("submit", {}, timeout=0.01))
        request = await self.writer.sent.get()
        with self.assertRaises(OutcomeUnknown):
            await task
        self.reply({"id": request["id"], "result": {"accepted": True}})
        await asyncio.sleep(0)
        self.assertTrue(self.writer.sent.empty())
        self.assertFalse(self.rpc.pending)

    async def test_eof_fails_pending_and_event_consumers(self):
        task = asyncio.create_task(self.rpc.request("fixture", {}))
        await self.writer.sent.get()
        self.reader.feed_eof()
        with self.assertRaises(ConnectionLost):
            await task
        with self.assertRaises(ConnectionLost):
            await self.rpc.next_event()

    async def test_rpc_error_preserves_code(self):
        task = asyncio.create_task(self.rpc.request("fixture", {}))
        request = await self.writer.sent.get()
        self.reply({"id": request["id"], "error": {"code": -32001, "message": "overloaded"}})
        with self.assertRaises(RpcError) as raised:
            await task
        self.assertEqual(raised.exception.code, -32001)

    async def test_invalid_payload_fails_closed(self):
        task = asyncio.create_task(self.rpc.request("fixture", {}))
        await self.writer.sent.get()
        self.reader.feed_data(b"not-json\n")
        with self.assertRaises(ConnectionLost):
            await task

    async def test_event_overflow_fails_without_silent_drop(self):
        for i in range(3):
            self.reply({"method": "fixture", "params": {"sequence": i}})
        await asyncio.sleep(0)
        self.assertIsInstance(self.rpc.failure, ConnectionLost)
        self.assertEqual(self.rpc.events.qsize(), 2)
