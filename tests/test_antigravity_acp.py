"""Offline unit and synthetic-subprocess contract tests for Antigravity ACP backend."""

import asyncio
import copy
import json
import struct
import tempfile
import unittest
import urllib.parse
import zlib
from pathlib import Path

from wx_clawbot.agents.acp_rpc import StdioJsonRpc
from wx_clawbot.agents.antigravity import AntigravityConnection, canonicalize_agy_cwd
from wx_clawbot.agents.rpc import ConnectionLost
from wx_clawbot.interactions import ACP_APPROVAL, InteractionBroker


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "antigravity-acp-contract.json").read_text())


def png_bytes() -> bytes:
    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack("!IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class FakeStdin:
    def __init__(self, on_message):
        self.on_message = on_message
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes):
        if self.closed:
            raise BrokenPipeError("stdin closed")
        self.buffer.extend(data)
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            if line.strip():
                self.on_message(json.loads(line.decode("utf-8")))

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        self.closed = True


class FakeAcpServerProcess:
    """In-process fake ACP server speaking exact newline-delimited JSON-RPC 2.0."""

    def __init__(self, *, handler=None):
        self.pid = 42424
        self.returncode = None
        self.stdout = asyncio.StreamReader(limit=StdioJsonRpc.MAX_MESSAGE)
        self.stderr = asyncio.StreamReader()
        self.stdin = FakeStdin(self._on_client_message)
        self.received = []
        self.handler = handler
        self._waiter = asyncio.get_running_loop().create_future()
        self._tasks = []

    def send(self, payload: dict):
        self.stdout.feed_data((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    def crash(self):
        self.returncode = 1
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        if not self._waiter.done():
            self._waiter.set_result(1)

    def _on_client_message(self, msg: dict):
        self.received.append(msg)
        if self.handler is not None:
            task = asyncio.create_task(self.handler(self, msg))
            self._tasks.append(task)

    async def wait(self):
        if self.returncode is None:
            self.returncode = 0
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            if not self._waiter.done():
                self._waiter.set_result(0)
        return await self._waiter

    def terminate(self):
        self.crash()

    def kill(self):
        self.crash()


class AntigravityAcpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve(strict=True)
        self.proj = self.root / "sample-one"
        self.proj.mkdir()
        self.fake_bin = self.root / "agy"
        self.fake_bin.write_text("#!/bin/sh\nexit 0\n")
        self.fake_bin.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def default_handler(self, *, sessions_list=None, prompt_hook=None, init_override=None):
        state = {
            "session_new": copy.deepcopy(FIXTURE["session_new_result"]),
            "model": "gemini-4-neon",
            "thought_level": "high",
            "cancel_event": asyncio.Event(),
        }

        async def handle(proc: FakeAcpServerProcess, msg: dict):
            method = msg.get("method")
            req_id = msg.get("id")
            params = msg.get("params") or {}
            if method == "initialize":
                res = copy.deepcopy(init_override if init_override is not None else FIXTURE["initialize_result"])
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": res})
            elif method == "session/new":
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": copy.deepcopy(state["session_new"])})
            elif method == "session/resume":
                res = copy.deepcopy(state["session_new"])
                res["sessionId"] = params.get("sessionId")
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": res})
            elif method == "session/list":
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": {"sessions": list(sessions_list or [])}})
            elif method == "session/set_config_option":
                cid, val = params["configId"], params["value"]
                opts = copy.deepcopy(state["session_new"]["configOptions"])
                if cid == "model":
                    state["model"] = val
                    if val == "gemini-3.8-flash":
                        opts[1]["options"] = [o for o in opts[1]["options"] if o["value"] != "xhigh"]
                        if state["thought_level"] == "xhigh":
                            state["thought_level"] = "high"
                elif cid == "thought_level":
                    state["thought_level"] = val
                opts[0]["currentValue"] = state["model"]
                opts[1]["currentValue"] = state["thought_level"]
                state["session_new"]["configOptions"] = opts
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": {"configOptions": opts}})
            elif method == "session/cancel":
                state["cancel_event"].set()
            elif method == "session/prompt":
                if prompt_hook is not None:
                    await prompt_hook(proc, msg, state)
                else:
                    sid = params["sessionId"]
                    proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                        "sessionId": sid,
                        "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OK_PART1 "}},
                    }})
                    proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                        "sessionId": sid,
                        "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OK_PART2"}},
                    }})
                    proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                        "sessionId": sid,
                        "update": {"sessionUpdate": "usage_update", "used": 1200, "size": 100000},
                    }})
                    proc.send({"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "end_turn"}})

        return handle, state

    async def connect_fake(self, handler):
        proc = FakeAcpServerProcess(handler=handler)

        async def spawn(_exe, _cwd):
            return proc

        conn = await AntigravityConnection.connect(self.fake_bin, cwd=self.proj, spawn=spawn)
        return conn, proc

    async def test_connect_validates_protocol_and_capabilities(self):
        handler, _ = self.default_handler()
        conn, _ = await self.connect_fake(handler)
        try:
            self.assertEqual(conn.server_version, "1.5.14")
            self.assertTrue(conn.capabilities.image_input)
            self.assertTrue(conn.capabilities.bridge_queue)
            self.assertFalse(conn.capabilities.queue)
            self.assertFalse(conn.capabilities.external_observe)
            self.assertIsNotNone(conn.runtime_identity)
        finally:
            await conn.close()

        bad_init = copy.deepcopy(FIXTURE["initialize_result"])
        bad_init["protocolVersion"] = 99
        bad_handler, _ = self.default_handler(init_override=bad_init)
        with self.assertRaises(ValueError):
            await self.connect_fake(bad_handler)

    async def test_canonicalize_cwd_and_active_sessions_scope_filtering(self):
        cn_dir = self.proj / "中文 目录"
        cn_dir.mkdir()
        outside = self.root / "outside-proj"
        outside.mkdir()
        forbidden_dir = self.proj / "openclaw-local"
        forbidden_dir.mkdir()
        encoded_cn = urllib.parse.quote(str(cn_dir), safe="/")
        self.assertEqual(canonicalize_agy_cwd(encoded_cn), cn_dir)
        self.assertIsNone(canonicalize_agy_cwd(str(forbidden_dir)))
        self.assertIsNone(canonicalize_agy_cwd(str(self.proj / "nonexistent")))
        handler, _ = self.default_handler()
        conn, _ = await self.connect_fake(handler)
        try:
            s_in = await conn.create_session(cn_dir, title="中文会话")
            rows = conn.list_active_sessions({self.proj})
            self.assertEqual([r["id"] for r in rows], [s_in.session_id])
            self.assertEqual(rows[0]["cwd"], str(cn_dir))
            self.assertEqual(conn.list_active_sessions({outside}), [])
        finally:
            await conn.close()

    async def test_text_and_single_image_turns_and_busy_rejection(self):
        seen_prompts = []
        hold = asyncio.Event()

        async def hook(proc, msg, _state):
            params = msg["params"]
            seen_prompts.append(params["prompt"])
            if len(seen_prompts) == 2:
                await hold.wait()
            sid = params["sessionId"]
            proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": sid,
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "DONE"}},
            }})
            proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}})

        handler, _ = self.default_handler(prompt_hook=hook)
        conn, _ = await self.connect_fake(handler)
        try:
            session = await conn.create_session(self.proj, title="图测")
            img_path = self.root / "sample.png"
            img_path.write_bytes(png_bytes())
            receipt = await conn.submit_idle(
                session.session_id,
                self.proj,
                "分析截图",
                "wx-task-1",
                input_items=[{"type": "localImage", "path": str(img_path)}, {"type": "text", "text": "分析截图"}],
            )
            ev = await conn.next_event(timeout=5)
            self.assertEqual(ev["method"], "agy/turn/completed")
            self.assertEqual(ev["params"]["turnId"], receipt.turn_id)
            self.assertEqual(ev["params"]["status"], "completed")
            self.assertEqual(ev["params"]["text"], "DONE")
            self.assertEqual(seen_prompts[0][0]["type"], "image")
            self.assertEqual(seen_prompts[0][0]["mimeType"], "image/png")

            # Reject invalid non-image or multiple images
            bad_file = self.root / "bad.bin"
            bad_file.write_bytes(b"NOT_AN_IMAGE")
            with self.assertRaises(ValueError):
                await conn.submit_idle(session.session_id, self.proj, "x", "wx-task-bad",
                                       input_items=[{"type": "localImage", "path": str(bad_file)}])
            with self.assertRaises(ValueError):
                await conn.submit_idle(session.session_id, self.proj, "x", "wx-task-two",
                                       input_items=[{"type": "localImage", "path": str(img_path)},
                                                    {"type": "localImage", "path": str(img_path)}])

            # Busy session rejects concurrent submit_idle
            await conn.submit_idle(session.session_id, self.proj, "first", "wx-task-2")
            with self.assertRaises(ValueError):
                await conn.submit_idle(session.session_id, self.proj, "second", "wx-task-3")
            hold.set()
            ev2 = await conn.next_event(timeout=5)
            self.assertEqual(ev2["params"]["status"], "completed")
        finally:
            hold.set()
            await conn.close()

    async def test_cancel_turn_emits_interrupted(self):
        async def hook(proc, msg, state):
            await state["cancel_event"].wait()
            proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "cancelled"}})

        handler, _ = self.default_handler(prompt_hook=hook)
        conn, _ = await self.connect_fake(handler)
        try:
            session = await conn.create_session(self.proj)
            await conn.submit_idle(session.session_id, self.proj, "long run", "wx-task-c")
            await conn.cancel_turn(session.session_id)
            ev = await conn.next_event(timeout=5)
            self.assertEqual(ev["method"], "agy/turn/completed")
            self.assertEqual(ev["params"]["status"], "interrupted")
        finally:
            await conn.close()

    async def test_permission_request_enforces_one_time_only_decisions(self):
        perm_responses = []
        perm_done = asyncio.Event()

        async def hook(proc, msg, _state):
            if "method" not in msg and msg.get("id") == 99:
                perm_responses.append(msg)
                perm_done.set()
                return
            if msg.get("method") == "session/prompt":
                req = copy.deepcopy(FIXTURE["permission_request"])
                req["params"]["sessionId"] = msg["params"]["sessionId"]
                proc.send(req)
                await perm_done.wait()
                proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}})

        handler, _ = self.default_handler(prompt_hook=hook)

        async def full_handler(proc, msg):
            if "method" not in msg:
                await hook(proc, msg, {})
            else:
                await handler(proc, msg)

        conn, _ = await self.connect_fake(full_handler)
        try:
            session = await conn.create_session(self.proj)
            await conn.submit_idle(session.session_id, self.proj, "run echo", "wx-task-p")
            ev = await conn.next_event(timeout=5)
            self.assertEqual(ev["method"], ACP_APPROVAL)
            broker = InteractionBroker(conn.rpc, session.session_id)
            record = broker.register(ev)
            await broker.answer(record.public_id, "accept", generation=broker.generation, thread_id=session.session_id)
            comp = await conn.next_event(timeout=5)
            self.assertEqual(comp["params"]["status"], "completed")
            # Must choose allow_once, never allow_always
            self.assertEqual(perm_responses[0]["result"], {"outcome": {"outcome": "selected", "optionId": "allow_once_id"}})

            # Reject if server only offers allow_always
            only_always = copy.deepcopy(ev)
            only_always["id"] = 100
            only_always["params"]["options"] = [{"optionId": "always", "name": "Always", "kind": "allow_always"}]
            rec2 = broker.register(only_always)
            with self.assertRaises(ValueError):
                broker._result(rec2, "accept")
            # Deny still safely falls back to cancelled when reject_once is absent
            self.assertEqual(broker._result(rec2, "decline"), {"outcome": {"outcome": "cancelled"}})
        finally:
            perm_done.set()
            await conn.close()

    async def test_model_catalog_and_set_model_and_effort(self):
        handler, _ = self.default_handler()
        conn, _ = await self.connect_fake(handler)
        try:
            session = await conn.create_session(self.proj)
            catalog = conn.model_catalog(session.session_id)
            self.assertIn("gemini-4-neon", catalog)
            self.assertIn("gemini-3.8-flash", catalog)
            updated = await conn.set_model_and_effort(session.session_id, self.proj, "gemini-3.8-flash", "low")
            self.assertEqual(updated["model"], "gemini-3.8-flash")
            self.assertEqual(updated["reasoningEffort"], "low")
            # Full modelId accepted too
            updated2 = await conn.set_model_and_effort(session.session_id, self.proj, "gemini-4-neon-medium")
            self.assertEqual(updated2["model"], "gemini-4-neon")
            self.assertEqual(updated2["reasoningEffort"], "medium")
            # Unsupported effort rejected
            with self.assertRaises(LookupError):
                await conn.set_model_and_effort(session.session_id, self.proj, "gemini-3.8-flash", "xhigh")
            # Unknown model rejected
            with self.assertRaises(KeyError):
                await conn.set_model_and_effort(session.session_id, self.proj, "no-such-model")
        finally:
            await conn.close()

    async def test_subprocess_crash_mid_turn_never_fakes_completion(self):
        started = asyncio.Event()

        async def hook(proc, msg, _state):
            started.set()
            await asyncio.sleep(30)

        handler, _ = self.default_handler(prompt_hook=hook)
        conn, proc = await self.connect_fake(handler)
        try:
            session = await conn.create_session(self.proj)
            await conn.submit_idle(session.session_id, self.proj, "work", "wx-task-crash")
            await asyncio.wait_for(started.wait(), timeout=5)
            proc.crash()
            await asyncio.sleep(0.1)
            self.assertIsNone(conn.runtime_identity)
            with self.assertRaises(ConnectionLost):
                await conn.next_event(timeout=1)
        finally:
            await conn.close()

    async def test_same_buffer_chunk_and_prompt_result_never_loses_text_and_pump_survives_timeout(self):
        perm_done = asyncio.Event()
        turn_count = {"n": 0}

        async def hook(proc, msg, _state):
            if "method" not in msg and msg.get("id") == 99:
                perm_done.set()
                return
            if msg.get("method") == "session/prompt":
                turn_count["n"] += 1
                sid = msg["params"]["sessionId"]
                if turn_count["n"] == 1:
                    # Feed agent_message_chunk AND end_turn response in ONE single buffer chunk
                    # (reproduces the exact OS pipe burst ordering race).
                    burst = (
                        json.dumps({
                            "jsonrpc": "2.0",
                            "method": "session/update",
                            "params": {
                                "sessionId": sid,
                                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "BURST_OK"}},
                            },
                        }) + "\n"
                        + json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}}) + "\n"
                    ).encode("utf-8")
                    proc.stdout.feed_data(burst)
                else:
                    req = copy.deepcopy(FIXTURE["permission_request"])
                    req["params"]["sessionId"] = sid
                    proc.send(req)
                    await perm_done.wait()
                    proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}})

        handler, _ = self.default_handler(prompt_hook=hook)

        async def full_handler(proc, msg):
            if "method" not in msg:
                await hook(proc, msg, {})
            else:
                await handler(proc, msg)

        conn, _ = await self.connect_fake(full_handler)
        try:
            # Force _pump() to experience a real TimeoutError cycle before any request arrives.
            orig_next = conn.rpc.next_event
            timed_out = asyncio.Event()

            async def fast_timeout_once(*, timeout=5):
                if not timed_out.is_set():
                    timed_out.set()
                    raise TimeoutError()
                return await orig_next(timeout=0.05)

            conn.rpc.next_event = fast_timeout_once
            await asyncio.sleep(0.1)
            self.assertFalse(conn._pump_task.done(), "_pump() must never exit on idle TimeoutError")

            session = await conn.create_session(self.proj)
            await conn.submit_idle(session.session_id, self.proj, "burst", "wx-burst-1")
            ev1 = await conn.next_event(timeout=5)
            self.assertEqual(ev1["method"], "agy/turn/completed")
            self.assertEqual(ev1["params"]["text"], "BURST_OK")

            # Verify _pump() is STILL alive after TimeoutError and forwards permission requests.
            await conn.submit_idle(session.session_id, self.proj, "perm", "wx-perm-2")
            ev2 = await conn.next_event(timeout=5)
            self.assertEqual(ev2["method"], ACP_APPROVAL)
            broker = InteractionBroker(conn.rpc, session.session_id)
            rec = broker.register(ev2)
            await broker.answer(rec.public_id, "accept", generation=broker.generation, thread_id=session.session_id)
            ev3 = await conn.next_event(timeout=5)
            self.assertEqual(ev3["params"]["status"], "completed")
        finally:
            perm_done.set()
            await conn.close()

    async def test_idle_eviction_closes_unfocused_sessions_and_active_list_filters_tmp(self):
        closed_ids = []
        now = {"t": 1000.0}
        counter = {"n": 0}

        async def handle(proc: FakeAcpServerProcess, msg: dict):
            method = msg.get("method")
            req_id = msg.get("id")
            params = msg.get("params") or {}
            if method == "initialize":
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": copy.deepcopy(FIXTURE["initialize_result"])})
            elif method == "session/new":
                counter["n"] += 1
                res = copy.deepcopy(FIXTURE["session_new_result"])
                res["sessionId"] = f"evict-sess-{counter['n']}"
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": res})
            elif method == "session/close":
                closed_ids.append(params["sessionId"])
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": {}})

        conn, _ = await self.connect_fake(handle)
        conn.clock = lambda: now["t"]
        conn.idle_ttl = 86400
        try:
            s1 = await conn.create_session(self.proj, title="受保护会话")
            s2 = await conn.create_session(self.proj, title="闲置会话")
            tmp_dir = self.proj / ".tmp" / "scratch"
            tmp_dir.mkdir(parents=True)
            await conn.create_session(tmp_dir, title="临时目录会话")

            # list_active_sessions excludes .tmp subdirs
            active_ids = [r["id"] for r in conn.list_active_sessions({self.proj})]
            self.assertEqual(set(active_ids), {s1.session_id, s2.session_id})

            # Advance 25 hours: s1 is protected, s2 is evicted and closed in memory
            now["t"] += 25 * 3600
            evicted = await conn.evict_idle_sessions(protected_session_ids={s1.session_id})
            self.assertIn(s2.session_id, evicted)
            self.assertNotIn(s1.session_id, evicted)
            self.assertIn(s2.session_id, closed_ids)
            self.assertEqual([r["id"] for r in conn.list_active_sessions({self.proj})], [s1.session_id])
        finally:
            await conn.close()
