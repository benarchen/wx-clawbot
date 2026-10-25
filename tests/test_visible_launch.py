import asyncio
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.config import Project
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchError, LaunchRegistry, VisibleStarter
from wx_clawbot.launcher import launch_argv


class VisibleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "w05-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        cwd = self.root / "project ' $(touch NEVER)"
        cwd.mkdir()
        self.project = Project("fixture", cwd)
        self.executable = self.root / "codex"
        self.executable.write_bytes(b"\xcf\xfa\xed\xfe")
        self.executable.chmod(0o700)
        self.home = self.root / "native home"
        self.home.mkdir()
        self.registry = LaunchRegistry(self.root / "registry ' $(touch NEVER)")
        self.identity = "a" * 32
        self.endpoint = {"window_id": "fixture-window", "tab_id": "fixture-tab", "terminal_id": "fixture-terminal"}

    async def start(self, callback, identity=None, **kwargs):
        return await VisibleStarter(self.registry, callback).start(self.identity if identity is None else identity, self.project,
                            self.project.root, self.executable, self.home, **kwargs)

    async def test_intent_is_durable_before_host_call_and_host_ack_is_not_ready(self):
        async def create(command):
            self.assertEqual(self.registry.load(self.identity)["phase"], "starting")
            self.assertEqual((self.registry.root / (self.identity + ".json")).stat().st_mode & 0o777, 0o600)
            return self.endpoint
        result = await self.start(create)
        self.assertEqual(result["phase"], "handshaking")
        self.assertNotIn("thread_id", result)

    async def test_repeated_request_and_new_controller_do_not_create_another_terminal(self):
        callback = AsyncMock(return_value=self.endpoint)
        first = await self.start(callback)
        self.assertEqual(await self.start(callback), first)
        self.assertEqual(callback.await_count, 1)

    async def test_lost_host_ack_leaves_unknown_and_does_not_repeat_side_effect(self):
        callback = AsyncMock(side_effect=ConnectionError("ack lost after creation"))
        with self.assertRaises(ConnectionError):
            await self.start(callback)
        self.assertEqual(self.registry.load(self.identity)["phase"], "unknown")
        self.assertEqual((await self.start(callback))["phase"], "unknown")
        self.assertEqual(callback.await_count, 1)

    async def test_cancelled_launch_still_requires_reconciliation(self):
        callback = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await self.start(callback)
        self.assertEqual((await self.start(callback))["phase"], "unknown")
        self.assertEqual(callback.await_count, 1)

    async def test_invalid_launch_identity_is_refused_before_lock_or_host_mutation(self):
        callback = AsyncMock()
        for value in ("../escaped", "", "A" * 32, "x" * 32):
            with self.assertRaises(LaunchError):
                await self.start(callback, identity=value)
        callback.assert_not_called()
        self.assertFalse((self.root / "escaped.lock").exists())

    async def test_incomplete_or_overwriting_host_receipt_cannot_mark_ready(self):
        for index, endpoint in enumerate(({"terminal_id": "partial"}, {**self.endpoint, "launch_id": "b" * 32})):
            identity = str(index) * 32
            with self.assertRaises(LaunchError):
                await self.start(AsyncMock(return_value=endpoint), identity=identity)
            self.assertEqual(self.registry.load(identity)["phase"], "unknown")

    async def test_same_launch_identity_cannot_change_its_target(self):
        callback = AsyncMock(return_value=self.endpoint)
        await self.start(callback, title="first")
        with self.assertRaises(LaunchError):
            await self.start(callback, title="changed")
        self.assertEqual(callback.await_count, 1)

    async def test_fixed_entry_command_and_exec_argv_do_not_expand_user_content(self):
        record = self.registry.prepare(self.identity, self.project, self.project.root, self.executable,
                                       self.home, "title $(touch NEVER)")
        command = shlex.split(self.registry.command(self.identity))
        self.assertEqual(command[0], str(Path(sys.executable).absolute()))
        self.assertEqual(command[1:3], ["-m", "wx_clawbot.launcher"])
        self.assertNotIn(str(self.project.root), command)
        self.assertNotIn(record["title"], command)
        before = os.environ.get("PATH")
        argv = launch_argv(record)
        self.assertEqual(argv[0], "/usr/bin/env")
        self.assertIn(str(self.project.root), argv)
        self.assertIn("WX-LAUNCH-" + self.identity, argv[-1])
        self.assertFalse(any(flag in argv for flag in ("--model", "-c", "--remote")))
        self.assertEqual(os.environ.get("PATH"), before)
        self.assertFalse((self.root / "NEVER").exists())

    async def test_iterm_uses_a_new_owned_window_then_only_its_own_tabs(self):
        tab = SimpleNamespace(tab_id="fixture-tab", current_session=SimpleNamespace(session_id="fixture-terminal"))
        window = SimpleNamespace(window_id="fixture-owned", current_tab=tab, async_create_tab=AsyncMock(return_value=tab))
        app = SimpleNamespace(get_window_by_id=lambda identity: window if identity == "fixture-owned" else None,
                              current_window=SimpleNamespace(window_id="user-working-window"))
        with patch("iterm2.async_get_app", AsyncMock(return_value=app)), \
             patch("iterm2.Window.async_create", AsyncMock(return_value=window)) as create:
            starter = ItermWindowStarter(object())
            await starter("first command")
            await starter("second command")
        self.assertEqual(create.await_count, 1)
        window.async_create_tab.assert_awaited_once_with(command="second command")
