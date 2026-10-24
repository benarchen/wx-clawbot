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
        self.socket = Path(self.temp.name) / "rpc.sock"
        self.methods = []
        self.server_version = "0.164.0"

        async def peer(websocket):
            async for raw in websocket:
                message = json.loads(raw)
                self.methods.append(message["method"])
                if message["method"] == "initialize":
                    result = {"userAgent": "fixture/" + self.server_version,
                              "platformFamily": "unix", "platformOs": "macos",
                              "codexHome": "/example/private-runtime"}
                elif message["method"] == "thread/read":
                    result = {"thread": {"id": message["params"]["threadId"]}}
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

    async def test_unverified_version_is_rejected_before_any_task(self):
        self.server_version = "0.999.0"
        with self.assertRaisesRegex(ValueError, "schema baseline"):
            await CodexConnection.connect(self.socket)
        self.assertEqual(self.methods, ["initialize"])

    async def test_non_private_socket_is_rejected_before_connect(self):
        os.chmod(self.socket, 0o666)
        with self.assertRaisesRegex(ValueError, "private"):
            await CodexConnection.connect(self.socket)
        self.assertEqual(self.methods, [])
