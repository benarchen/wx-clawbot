"""Real Unix WebSocket against a synthetic peer, separate from native acceptance."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from websockets.asyncio.server import unix_serve

from wx_clawbot.agents.codex import CodexConnection


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "w02-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        # macOS Unix socket addresses must stay short even in isolated checkouts.
        self.socket_temp = tempfile.TemporaryDirectory(prefix="wx-sock-", dir="/tmp")
        self.addCleanup(self.socket_temp.cleanup)
        self.socket = Path(self.socket_temp.name) / "rpc.sock"
        self.methods = []
        self.requests = []
        self.server_version = "0.164.0"
        self.thread = {"id": "fixture-thread", "cwd": str(Path(self.temp.name)),
                       "status": {"type": "idle"}, "sessionId": "fixture-session",
                       "model": "fixture-model", "modelProvider": "fixture-provider",
                       "canAcceptDirectInput": True}
        self.resume_changes = {}
        self.resume_error = None
        self.list_rows = [self.thread]
        self.loaded_page = {"data": ["fixture-thread"], "nextCursor": None}

        async def peer(websocket):
            async for raw in websocket:
                message = json.loads(raw)
                self.methods.append(message["method"])
                self.requests.append(message)
                if message["method"] == "initialize":
                    result = {"userAgent": "fixture/" + self.server_version,
                              "platformFamily": "unix", "platformOs": "macos",
                              "codexHome": "/example/private-runtime"}
                elif message["method"] == "thread/read":
                    result = {"thread": {**self.thread, "id": message["params"]["threadId"]}}
                elif message["method"] == "thread/resume":
                    if self.resume_error is not None:
                        await websocket.send(json.dumps({"id": message["id"], "error": self.resume_error}))
                        continue
                    result = {"thread": {**self.thread, **self.resume_changes}}
                elif message["method"] == "thread/list":
                    result = {"data": self.list_rows, "nextCursor": None}
                elif message["method"] == "thread/loaded/list":
                    result = self.loaded_page
                elif message["method"] == "turn/start":
                    result = {"turn": {"id": "fixture-turn", "status": "inProgress"}}
                else:
                    continue
                await websocket.send(json.dumps({"id": message["id"], "result": result}))

        self.server = await unix_serve(peer, self.socket)
        os.chmod(self.socket, 0o600)
        self.addAsyncCleanup(self.stop_server)

    async def stop_server(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_handshake_and_metadata_read_never_start_or_resume(self):
        connection = await CodexConnection.connect(self.socket)
        try:
            self.assertEqual((await connection.inspect("fixture-thread"))["id"], "fixture-thread")
        finally:
            await connection.close()
        self.assertEqual(self.methods, ["initialize", "initialized", "thread/read"])
        self.assertEqual(connection.server_version, "0.164.0")
        self.assertFalse(connection.capabilities.image_input)

    async def test_unverified_version_is_rejected_before_any_task(self):
        self.server_version = "0.999.0"
        with self.assertRaisesRegex(ValueError, "schema baseline"):
            await CodexConnection.connect(self.socket)
        self.assertEqual(self.methods, ["initialize"])

    async def test_verified_0165_handshake_and_read_do_not_submit_tasks(self):
        self.server_version = "0.165.0"
        connection = await CodexConnection.connect(self.socket)
        try:
            self.assertEqual(connection.server_version, "0.165.0")
            self.assertTrue(connection.capabilities.image_input)
            self.assertEqual((await connection.inspect("fixture-thread"))["id"], "fixture-thread")
        finally:
            await connection.close()
        self.assertEqual(self.methods, ["initialize", "initialized", "thread/read"])

    async def test_verified_0166_handshake_and_read_do_not_submit_tasks(self):
        self.server_version = "0.166.0"
        connection = await CodexConnection.connect(self.socket)
        try:
            self.assertEqual(connection.server_version, "0.166.0")
            self.assertTrue(connection.capabilities.image_input)
            self.assertEqual((await connection.inspect("fixture-thread"))["id"], "fixture-thread")
        finally:
            await connection.close()
        self.assertEqual(self.methods, ["initialize", "initialized", "thread/read"])

    async def test_non_private_socket_is_rejected_before_connect(self):
        os.chmod(self.socket, 0o666)
        with self.assertRaisesRegex(ValueError, "private"):
            await CodexConnection.connect(self.socket)
        self.assertEqual(self.methods, [])

    async def test_project_listing_rejects_out_of_scope_native_result(self):
        self.list_rows = [{**self.thread, "cwd": "/example/outside-project"}]
        connection = await CodexConnection.connect(self.socket)
        try:
            with self.assertRaisesRegex(ValueError, "project scope"):
                await connection.list_project_threads(Path(self.temp.name))
        finally:
            await connection.close()

    async def test_observe_loaded_preserves_identity_and_model(self):
        connection = await CodexConnection.connect(self.socket)
        try:
            after = await connection.observe_loaded("fixture-thread", Path(self.temp.name))
            self.assertEqual(after, self.thread)
        finally:
            await connection.close()
        resume = next(r for r in self.requests if r["method"] == "thread/resume")
        self.assertEqual(resume["params"], {"threadId": "fixture-thread", "excludeTurns": True})

    async def test_stored_thread_is_not_resumed_as_an_original_terminal(self):
        self.thread["status"] = {"type": "notLoaded"}
        connection = await CodexConnection.connect(self.socket)
        try:
            with self.assertRaisesRegex(ValueError, "not loaded"):
                await connection.observe_loaded("fixture-thread", Path(self.temp.name))
        finally:
            await connection.close()
        self.assertNotIn("thread/resume", self.methods)

    async def test_subscription_identity_change_is_rejected(self):
        self.resume_changes = {"model": "unexpected-model"}
        connection = await CodexConnection.connect(self.socket)
        try:
            with self.assertRaisesRegex(ValueError, "identity or model changed"):
                await connection.observe_loaded("fixture-thread", Path(self.temp.name))
        finally:
            await connection.close()

    async def test_idle_submission_preserves_config_and_returns_native_receipt(self):
        connection = await CodexConnection.connect(self.socket)
        try:
            result = await connection.submit_idle("fixture-thread", Path(self.temp.name), "fixture input", "stable-id")
            self.assertEqual(result.turn_id, "fixture-turn")
            self.assertEqual(result.client_submission_id, "stable-id")
        finally:
            await connection.close()
        request = next(r for r in self.requests if r["method"] == "turn/start")
        self.assertEqual(request["params"], {"threadId": "fixture-thread",
                                          "input": [{"type": "text", "text": "fixture input"}],
                                          "clientUserMessageId": "stable-id"})

    async def test_busy_or_read_only_native_input_is_not_submitted(self):
        for status, accepts in [("active", True), ("idle", False)]:
            self.thread.update(status={"type": status}, canAcceptDirectInput=accepts)
            connection = await CodexConnection.connect(self.socket)
            try:
                with self.assertRaises(ValueError):
                    await connection.submit_idle("fixture-thread", Path(self.temp.name), "fixture input", "stable-id")
            finally:
                await connection.close()
        self.assertNotIn("turn/start", self.methods)

    async def test_native_subscription_denial_is_not_reported_as_observing(self):
        from wx_clawbot.agents.rpc import RpcError

        self.resume_error = {"code": -32003, "message": "subscription denied by peer"}
        connection = await CodexConnection.connect(self.socket)
        try:
            with self.assertRaises(RpcError) as raised:
                await connection.observe_loaded("fixture-thread", Path(self.temp.name))
            self.assertEqual(raised.exception.code, -32003)
        finally:
            await connection.close()

    async def test_failed_but_loaded_original_can_be_observed_without_hydrating_a_copy(self):
        self.thread["status"] = {"type": "systemError"}
        connection = await CodexConnection.connect(self.socket)
        try:
            self.assertEqual(await connection.observe_loaded("fixture-thread", Path(self.temp.name)), self.thread)
        finally:
            await connection.close()
        self.assertEqual(self.methods.count("thread/loaded/list"), 2)
        self.assertNotIn("thread/start", self.methods)

    async def test_system_error_without_live_membership_is_not_resumed(self):
        self.thread["status"] = {"type": "systemError"}
        self.loaded_page = {"data": ["other-thread"], "nextCursor": None}
        connection = await CodexConnection.connect(self.socket)
        try:
            with self.assertRaisesRegex(ValueError, "not loaded"):
                await connection.observe_loaded("fixture-thread", Path(self.temp.name))
        finally:
            await connection.close()
        self.assertNotIn("thread/resume", self.methods)

    async def test_loaded_membership_rejects_invalid_pages_and_cursor_loops(self):
        connection = await CodexConnection.connect(self.socket)
        try:
            for page in ({"data": [None]}, {"data": [] , "nextCursor": 7}, {"data": [], "nextCursor": "repeated"}):
                self.loaded_page = page
                with self.assertRaises(ValueError):
                    await connection.is_loaded("fixture-thread")
        finally:
            await connection.close()
