import hashlib
import importlib.util
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_runtime_state import RuntimeFixture
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.hosts.discovery import TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity


spec = importlib.util.spec_from_file_location("w08_interactions", Path(__file__).parent / "integration" / "w08_interactions.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class InteractionAcceptanceTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        write_json(self.root / "credentials.json", {"version": 1, "owner_confirmed": True, "credentials": asdict(self.credentials)})
        self.home = private_directory(self.root / "fake-home")
        (self.home / "config.toml").write_text("# synthetic config, not a real user setting\n")
        self.fixture_record = self.root / "fixture.json"
        write_json(self.fixture_record, {"socket": "/fixture/control.sock", "cases": [{"root": str(self.root),
            "terminal_id": "fixture-terminal", "thread_id": "fixture-thread", "native_session_id": "fixture-native-session", "runtime_identity": [1, 2]}]})
        self.args = SimpleNamespace(fixture_record=self.fixture_record, fixture_root=self.root,
            codex_home=self.home, expected_config_sha256=hashlib.sha256((self.home / "config.toml").read_bytes()).hexdigest(),
            report_dir=self.root / "report", state_dir=self.root, case="approval-phone-first")

    async def test_prepare_attests_dedicated_identity_without_starting_a_native_turn(self):
        native = SimpleNamespace(close=AsyncMock(), rpc=SimpleNamespace(request=AsyncMock()))
        process = ProcessIdentity(123, (456, 789), "/fixture/python", 0)
        original = {"approvalPolicy": "on-request", "approvalsReviewer": "auto_review", "sandbox": {"type": "workspaceWrite"},
                    "collaborationMode": {"mode": "default", "settings": {"model": "fixture-model"}}}
        native.rpc.request.return_value = original
        binding = SimpleNamespace(endpoint=SimpleNamespace(process=process), thread_id="fixture-thread")
        with patch.object(acceptance, "connect", AsyncMock(return_value=(native, object(), object(), binding))), patch.object(acceptance, "close_connection", AsyncMock()):
            result = await acceptance.prepare(self.args)
        self.assertEqual(result["status"], "prepared_no_native_submission")
        native.rpc.request.assert_awaited_once_with("thread/resume", {"threadId": "fixture-thread", "excludeTurns": True})
        record = read_json(self.args.report_dir / "case.json")
        self.assertEqual(record["attested_process"]["started"], [456, 789])
        self.assertEqual(record["original_settings"]["approvalsReviewer"], "auto_review")
        with self.assertRaises(FileExistsError):
            with patch.object(acceptance, "connect", AsyncMock(return_value=(native, object(), object(), binding))), patch.object(acceptance, "close_connection", AsyncMock()):
                await acceptance.prepare(self.args)

    async def test_prepare_refuses_business_project_and_changed_config_before_connecting(self):
        self.args.fixture_root = self.home
        with patch.object(acceptance, "connect", AsyncMock()) as connect:
            with self.assertRaises(ValueError):
                await acceptance.prepare(self.args)
            connect.assert_not_awaited()
        self.args.fixture_root = self.root
        self.args.expected_config_sha256 = "0" * 64
        with patch.object(acceptance, "connect", AsyncMock()) as connect:
            with self.assertRaises(ValueError):
                await acceptance.prepare(self.args)
            connect.assert_not_awaited()

    async def test_focus_alone_does_not_replace_real_observer_subscription(self):
        with self.assertRaises(ValueError):
            await self.state._call(acceptance.require_observer, self.state.db, "fixture-thread")
        await self.state.save_routes({"target": {"thread_id": "fixture-thread"}, "observer": None})
        with self.assertRaises(ValueError):
            await self.state._call(acceptance.require_observer, self.state.db, "fixture-thread")
        await self.state.save_routes({"observer": {"thread_id": "another-thread"}})
        with self.assertRaises(ValueError):
            await self.state._call(acceptance.require_observer, self.state.db, "fixture-thread")
        await self.state.save_routes({"observer": {"thread_id": "fixture-thread"}})
        await self.state._call(acceptance.require_observer, self.state.db, "fixture-thread")

    async def test_extra_native_command_is_not_accepted_as_the_authorized_effect(self):
        import shlex
        command = "printf %s 'fixture-effect' > '/fixture/project two/approval.txt'"
        acceptance.validate_command(command, command)
        acceptance.validate_command(shlex.join(["/bin/zsh", "-lc", command]), command)
        for actual in (command + "; touch unrelated", command.replace("approval.txt", "different.txt"), "echo fixture-effect"):
            with self.assertRaises(ValueError):
                acceptance.validate_command(actual, command)

    async def test_reused_pid_generation_is_refused_before_any_native_turn_or_ui_input(self):
        case = {"socket": "/fixture/control.sock", "fixture": {"terminal_id": "fixture-terminal"},
                "attested_process": {"pid": 123, "started": [456, 789], "executable": "/fixture/codex", "tty_device": 0}}
        changed = TerminalEndpoint("fixture-terminal", ProcessIdentity(123, (457, 789), "/fixture/codex", 0), "codex_candidate")
        native = SimpleNamespace(close=AsyncMock(), rpc=SimpleNamespace(request=AsyncMock()))
        terminal = SimpleNamespace(async_send_text=AsyncMock())
        app = SimpleNamespace(get_session_by_id=lambda _: terminal)
        with patch.object(acceptance.CodexConnection, "connect", AsyncMock(return_value=native)), patch("iterm2.Connection.async_create", AsyncMock(return_value=object())), patch("iterm2.async_get_app", AsyncMock(return_value=app)), patch.object(acceptance, "inspect_terminal", AsyncMock(return_value=changed)), patch.object(acceptance, "close_connection", AsyncMock()):
            with self.assertRaises(ValueError):
                await acceptance.connect(case)
        terminal.async_send_text.assert_not_awaited()
        native.rpc.request.assert_not_awaited()

    async def restoration_case(self):
        original = {"approvalPolicy": "on-request", "approvalsReviewer": "auto_review", "sandboxPolicy": {"type": "workspaceWrite"},
                    "collaborationMode": {"mode": "default", "settings": {"model": "fixture-model"}}}
        report_dir = private_directory(self.root / "restore")
        case = {"phase": "awaiting_real_owner_or_desktop", "case": "approval-phone-first", "model": "fixture-model",
                "turn_id": "fixture-turn", "public_id": "fixture-request", "original_settings": original,
                "binding": [self.credentials.bot_id, self.credentials.owner_id], "config_sha256": self.args.expected_config_sha256}
        write_json(report_dir / "case.json", case)
        args = SimpleNamespace(action="restore", report_dir=report_dir, codex_home=self.home, state_dir=self.root)
        return original, args

    async def test_restore_only_changes_test_thread_defaults_and_verifies_original_model(self):
        original, args = await self.restoration_case()
        reply = {"approvalPolicy": original["approvalPolicy"], "approvalsReviewer": original["approvalsReviewer"],
                 "sandbox": original["sandboxPolicy"], "collaborationMode": original["collaborationMode"], "model": "fixture-model"}
        native = SimpleNamespace(close=AsyncMock(), inspect=AsyncMock(return_value={"status": {"type": "idle"}}),
            rpc=SimpleNamespace(request=AsyncMock(side_effect=[{"data": [{"id": "fixture-turn", "status": "completed"}]}, {}, reply])))
        binding = SimpleNamespace(thread_id="fixture-thread")
        with patch.object(acceptance, "connect", AsyncMock(return_value=(native, object(), object(), binding))), patch.object(acceptance, "close_connection", AsyncMock()):
            await acceptance.act(args)
        methods = [call.args[0] for call in native.rpc.request.await_args_list]
        self.assertEqual(methods, ["thread/turns/list", "thread/settings/update", "thread/resume"])
        restored = native.rpc.request.await_args_list[1].args[1]
        self.assertEqual(restored, {"threadId": "fixture-thread", **{k:original[k] for k in ("approvalPolicy", "approvalsReviewer", "collaborationMode")}})
        self.assertNotIn("sandboxPolicy", restored)
        self.assertTrue(read_json(args.report_dir / "case.json")["original_settings_restored"])

    async def test_restore_refuses_running_or_different_turn_without_mutating_native_settings(self):
        _, args = await self.restoration_case()
        native = SimpleNamespace(close=AsyncMock(), inspect=AsyncMock(return_value={"status": {"type": "active"}}),
                                 rpc=SimpleNamespace(request=AsyncMock()))
        binding = SimpleNamespace(thread_id="fixture-thread")
        with patch.object(acceptance, "connect", AsyncMock(return_value=(native, object(), object(), binding))), patch.object(acceptance, "close_connection", AsyncMock()):
            with self.assertRaises(ValueError):
                await acceptance.act(args)
            native.rpc.request.assert_not_awaited()
            native.inspect.return_value = {"status": {"type": "idle"}}
            native.rpc.request.return_value = {"data": [{"id": "another-turn", "status": "completed"}]}
            with self.assertRaises(ValueError):
                await acceptance.act(args)
        self.assertEqual([c.args[0] for c in native.rpc.request.await_args_list], ["thread/turns/list"])
        self.assertNotIn("restoration_intent", read_json(args.report_dir / "case.json"))

    async def test_uncertain_desktop_input_cannot_be_repeated(self):
        _, args = await self.restoration_case()
        args.action = "desktop-accept"
        path = args.report_dir / "case.json"
        case = read_json(path)
        case["desktop_action_intent"] = "desktop-accept"
        write_json(path, case, replace=True)
        native = SimpleNamespace(close=AsyncMock(), rpc=SimpleNamespace(request=AsyncMock()))
        terminal = SimpleNamespace(async_send_text=AsyncMock())
        with patch.object(acceptance, "connect", AsyncMock(return_value=(native, object(), terminal, object()))), patch.object(acceptance, "close_connection", AsyncMock()):
            with self.assertRaises(ValueError):
                await acceptance.act(args)
        terminal.async_send_text.assert_not_awaited()
        native.rpc.request.assert_not_awaited()
