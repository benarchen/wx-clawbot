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
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchError, LaunchPending, LaunchRegistry, VisibleStarter, reconcile_launch
from wx_clawbot.channels.private import write_json
from wx_clawbot.hosts.discovery import TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity
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
        self.assertEqual(command[1:4], ["-I", "-m", "wx_clawbot.launcher"])
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

    async def test_bridge_manifest_is_verified_but_not_inherited_by_external_codex(self):
        from wx_clawbot.launcher import main
        record = self.registry.prepare(self.identity, self.project, self.project.root, self.executable, self.home)
        record['phase'] = 'starting'
        self.registry.save(record)
        with patch.dict(os.environ, {'WX_CLAWBOT_RELEASE_MANIFEST': '/fixture/release.json'}), \
                patch('wx_clawbot.release.verify_active') as verify, \
                patch('wx_clawbot.launcher.read_process', return_value=ProcessIdentity(123, (1, 2), '/fixture/python', 101)), \
                patch('wx_clawbot.launcher.os.chdir'), \
                patch('wx_clawbot.launcher.os.execv', side_effect=lambda *_:
                    self.assertNotIn('WX_CLAWBOT_RELEASE_MANIFEST', os.environ)) as execute:
            main(['--registry', str(self.registry.root), '--launch-id', self.identity])
            verify.assert_called_once()
            execute.assert_called_once()

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

    async def handshake_fixture(self):
        callback = AsyncMock(return_value=self.endpoint)
        await self.start(callback)
        process = ProcessIdentity(123, (1, 2), str(self.executable), 101)
        endpoint = TerminalEndpoint("fixture-terminal", process, "codex_candidate")
        write_json(self.registry.root / (self.identity + ".boot.json"),
                   {"launch_id": self.identity, "pid": 123, "started": [1, 2], "tty_device": 101})
        directory = SimpleNamespace(discover=AsyncMock(return_value=[endpoint]), validate=AsyncMock(return_value=True),
                                    current_thread_id=AsyncMock(return_value="fixture-thread"))
        thread = {"id": "fixture-thread", "sessionId": "fixture-session", "cwd": str(self.project.root),
                  "preview": "WX-LAUNCH-" + self.identity, "status": {"type": "idle"}, "model": "fixture-model"}
        turn = {"status": "completed", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": "WX-LAUNCH-" + self.identity + "\nbootstrap"}]},
            {"type": "agentMessage", "text": "WX-LAUNCH-" + self.identity}]}
        native = SimpleNamespace(runtime_identity=(1, 2), list_project_threads=AsyncMock(return_value={"data": [thread]}),
                                 inspect=AsyncMock(return_value=thread), read_turns=AsyncMock(return_value={"data": [turn]}),
                                 is_loaded=AsyncMock(return_value=True))
        return directory, native, turn

    async def test_ready_requires_actual_boot_provenance_and_unique_completed_native_handshake(self):
        directory, native, _ = await self.handshake_fixture()
        binding = await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertEqual(binding.thread_id, "fixture-thread")
        self.assertEqual(self.registry.load(self.identity)["phase"], "ready")

    async def test_ready_launch_restores_native_identity_without_reassigning_host_provenance(self):
        directory, native, _ = await self.handshake_fixture()
        await reconcile_launch(self.registry, self.identity, directory, native)
        old = directory.discover.return_value[0]
        new = TerminalEndpoint("restored-terminal", old.process, old.classification)
        directory.discover.return_value = [new]
        rebound = await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertIsNone(rebound.endpoint)
        self.assertEqual(rebound.thread_id, "fixture-thread")
        self.assertEqual(self.registry.load(self.identity)["terminal_id"], "fixture-terminal")

    async def test_ready_launch_changed_native_identity_is_unbound_without_rewriting_record(self):
        from wx_clawbot.sessions import SessionUnbound
        directory, native, _ = await self.handshake_fixture()
        await reconcile_launch(self.registry, self.identity, directory, native)
        before = self.registry.load(self.identity)
        native.runtime_identity = (9, 9)
        with self.assertRaises(SessionUnbound):
            await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertEqual(self.registry.load(self.identity), before)

    async def test_ready_launch_keeps_exact_thread_after_desktop_switch(self):
        directory, native, _ = await self.handshake_fixture()
        original = await reconcile_launch(self.registry, self.identity, directory, native)
        directory.current_thread_id.return_value = "another-desktop-thread"
        rebound = await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertEqual(rebound.thread_id, original.thread_id)
        self.assertEqual(rebound.runtime_identity, original.runtime_identity)

    async def test_first_handshake_ignores_desktop_display_and_binds_its_unique_nonce(self):
        directory, native, _ = await self.handshake_fixture()
        directory.current_thread_id.return_value = "another-desktop-thread"
        binding = await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertEqual(binding.thread_id, "fixture-thread")
        directory.current_thread_id.assert_not_called()

    async def test_hidden_first_handshake_traps_all_screen_identity_reads(self):
        directory, native, _ = await self.handshake_fixture()
        directory.current_thread_id.side_effect = AssertionError("No displayed identity allowed")
        await reconcile_launch(self.registry, self.identity, directory, native)
        directory.current_thread_id.assert_not_called()

    async def test_duplicate_nonce_candidates_are_not_selected_by_list_order(self):
        directory, native, _ = await self.handshake_fixture()
        row = native.list_project_threads.return_value["data"][0]
        native.list_project_threads.return_value = {"data": [row, {**row, "id": "another-thread"}]}
        with self.assertRaises(LaunchPending):
            await reconcile_launch(self.registry, self.identity, directory, native)
        native.inspect.assert_not_called()

    async def test_forked_candidate_cannot_prove_the_original_launch(self):
        directory, native, _ = await self.handshake_fixture()
        native.inspect.return_value["forkedFromId"] = "parent-thread"
        with self.assertRaises(LaunchError):
            await reconcile_launch(self.registry, self.identity, directory, native)

    async def test_original_bootstrap_can_be_found_after_the_first_native_page(self):
        directory, native, _ = await self.handshake_fixture()
        row = native.list_project_threads.return_value["data"][0]
        native.list_project_threads.side_effect = [
            {"data": [{**row, "id": "other-thread", "preview": "unrelated"}], "nextCursor": "next"},
            {"data": [row], "nextCursor": None}]
        binding = await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertEqual(binding.thread_id, row["id"])
        self.assertEqual(native.list_project_threads.await_count, 2)

    async def test_merged_bootstrap_input_is_not_a_unique_startup_proof(self):
        directory, native, turn = await self.handshake_fixture()
        turn["items"].append({"type": "userMessage", "content": [{"type": "text", "text": "other input"}]})
        with self.assertRaises(LaunchError):
            await reconcile_launch(self.registry, self.identity, directory, native)

    async def test_runtime_switch_during_initial_handshake_cannot_create_ready_record(self):
        from wx_clawbot.sessions import SessionUnbound
        directory, native, _ = await self.handshake_fixture()
        row = native.inspect.return_value
        async def changed(_):
            native.runtime_identity = (3, 4)
            return row
        native.inspect.side_effect = changed
        with self.assertRaises(SessionUnbound):
            await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertEqual(self.registry.load(self.identity)["phase"], "handshaking")

    async def test_ready_native_identity_does_not_require_a_surviving_sdk_endpoint(self):
        directory, native, _ = await self.handshake_fixture()
        await reconcile_launch(self.registry, self.identity, directory, native)
        directory.discover.side_effect = AssertionError("Ready restore must not require a host")
        directory.current_thread_id.side_effect = AssertionError("No screen identity allowed")
        binding = await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertIsNone(binding.endpoint)

    async def test_changed_process_during_initial_handshake_does_not_create_ready(self):
        from wx_clawbot.sessions import SessionUnbound
        directory, native, _ = await self.handshake_fixture()
        directory.validate.return_value = False
        with self.assertRaises(SessionUnbound):
            await reconcile_launch(self.registry, self.identity, directory, native)

    async def test_in_progress_or_missing_bootstrap_reply_is_not_ready(self):
        directory, native, turn = await self.handshake_fixture()
        turn["status"] = "inProgress"
        with self.assertRaises(LaunchPending):
            await reconcile_launch(self.registry, self.identity, directory, native)
        turn["status"] = "completed"
        turn["items"][-1]["text"] = "unrelated output"
        with self.assertRaises(LaunchError):
            await reconcile_launch(self.registry, self.identity, directory, native)
        self.assertEqual(self.registry.load(self.identity)["phase"], "handshaking")

    async def test_reconcile_invalid_id_does_not_create_a_lock_outside_registry(self):
        with self.assertRaises(LaunchError):
            await reconcile_launch(self.registry, "../outside", object(), object())
        self.assertFalse((self.root / "outside.lock").exists())

    async def test_registered_path_replaced_with_symlink_is_not_retargeted(self):
        record = self.registry.prepare(self.identity, self.project, self.project.root, self.executable, self.home)
        self.project.root.rename(self.root / "original-project")
        outside = self.root / "outside"
        outside.mkdir()
        self.project.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(LaunchError):
            launch_argv(record)
