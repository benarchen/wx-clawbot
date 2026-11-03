import asyncio
import json
import os
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from test_runtime_state import RuntimeFixture
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.private import write_json
from wx_clawbot.hosts.process import ProcessIdentity
from wx_clawbot.operations import ForegroundInstance, StopRequested, request_stop, retry_delivery, status
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.service import ComponentError, component_task, failure_report


class OperatorTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        write_json(self.root / "credentials.json", {"version": 1, "owner_confirmed": True,
                   "credentials": asdict(self.credentials)})
        self.identity = ProcessIdentity(os.getpid(), (123, 456), "/fixture/python", 0)

    async def test_status_is_read_only_and_redacts_messages_binding_and_routes(self):
        await self.admit()
        await self.state.queue_reply("operator-event", "secret message")
        await self.state.claim_reply()
        before = await self.state._call(lambda: list(self.state.db.iterdump()))
        report = status(self.root)
        self.assertEqual(report["status"], "consumer_unverified")
        self.assertEqual(report["tasks"], {"prepared": 1})
        self.assertEqual(report["replies"], {"sending": 1})
        self.assertEqual(before, await self.state._call(lambda: list(self.state.db.iterdump())))
        for secret in (self.credentials.token, self.credentials.owner_id, "secret message", "fixture-thread"):
            self.assertNotIn(secret, json.dumps(report))

    async def test_stop_request_is_generation_bound_and_never_signals_a_process(self):
        with patch("wx_clawbot.operations.read_process", return_value=self.identity), patch("os.kill") as kill:
            instance = ForegroundInstance(self.root)
            self.addCleanup(instance.close)
            self.assertEqual(status(self.root)["status"], "running")
            self.assertEqual(request_stop(self.root)["status"], "stop_requested")
            with self.assertRaises(StopRequested):
                await instance.watch_stop()
            kill.assert_not_called()
            instance.close()
            self.assertFalse((self.root / "foreground.json").exists())

    async def test_managed_status_requires_same_foreground_and_stays_read_only(self):
        with patch("wx_clawbot.operations.read_process", return_value=self.identity):
            instance = ForegroundInstance(self.root)
            self.addCleanup(instance.close)
            path = self.root / "managed.json"
            write_json(path, {"version": 1, "state": "running", "pid": os.getpid(),
                              "process": asdict(self.identity),
                              "previous_exit_unobserved": True, "token": "SECRET"})
            before = path.read_bytes()
            before_db = await self.state._call(lambda: list(self.state.db.iterdump()))
            report = status(self.root)
            self.assertEqual(report["supervision"]["state"], "running")
            self.assertTrue(report["supervision"]["previous_exit_unobserved"])
            self.assertNotIn("SECRET", json.dumps(report))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(before_db, await self.state._call(lambda: list(self.state.db.iterdump())))
            write_json(path, {"version": 1, "state": "running", "pid": os.getpid(),
                              "process": asdict(ProcessIdentity(os.getpid(), (124, 456), "/fixture/python", 0))}, replace=True)
            self.assertEqual(status(self.root)["supervision"]["state"], "previous_exit_unobserved")

    async def test_malformed_managed_record_cannot_hide_bridge_status(self):
        path = self.root / "managed.json"
        write_json(path, {"version": 1, "state": []})
        report = status(self.root)
        self.assertEqual(report["status"], "consumer_unverified")
        self.assertEqual(report["supervision"], {"state": "unavailable"})

    async def test_reused_pid_and_released_consumer_lock_refuse_stop(self):
        with patch("wx_clawbot.operations.read_process", return_value=self.identity):
            instance = ForegroundInstance(self.root)
            self.addCleanup(instance.close)
            with patch("wx_clawbot.operations.read_process", return_value=ProcessIdentity(os.getpid(), (124, 456), "/fixture/python", 0)):
                self.assertEqual(request_stop(self.root)["status"], "no_verified_foreground")
            await self.state.close()
            self.assertEqual(request_stop(self.root)["status"], "no_verified_foreground")
            self.assertFalse((self.root / "foreground-stop.json").exists())

    async def test_old_stop_request_cannot_stop_new_generation_and_cleanup_preserves_replacement(self):
        write_json(self.root / "foreground-stop.json", {"generation": "0" * 32})
        with patch("wx_clawbot.operations.read_process", return_value=self.identity):
            instance = ForegroundInstance(self.root)
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(instance.watch_stop(), 0.01)
            write_json(self.root / "foreground.json", dict(instance.record, generation="1" * 32), replace=True)
            instance.close()
            self.assertTrue((self.root / "foreground.json").exists())
            self.assertTrue((self.root / "foreground-stop.json").exists())

    async def test_retry_inspection_and_write_do_not_recover_or_mutate_other_task_states(self):
        task = await self.admit()
        await self.state.queue_reply("operator-event", "result")
        await self.state.claim_reply()
        await self.state.finish_reply("operator-event", "unknown")
        before = await self.state.tasks()
        self.assertFalse(retry_delivery(self.root, "operator-event")["applied"])
        with self.assertRaises(ProtocolError):
            retry_delivery(self.root, "operator-event", apply=True, confirm_unknown=True)
        await self.state.close()
        with self.assertRaises(ProtocolError):
            retry_delivery(self.root, "operator-event", apply=True)
        report = retry_delivery(self.root, "operator-event", apply=True, confirm_unknown=True)
        self.assertEqual(report["next_attempt"], 1)
        import sqlite3
        with closing(sqlite3.connect(self.root / "runtime.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT state FROM tasks WHERE id=?", (task["id"],)).fetchone()[0], before[0]["state"])
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT phase FROM inbox").fetchone()[0], "runtime")
        with self.assertRaises(ProtocolError):
            retry_delivery(self.root, "operator-event", apply=True, confirm_unknown=True)

    async def test_missing_and_public_directory_are_not_created_or_repaired(self):
        missing = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            status(missing)
        self.assertFalse(missing.exists())
        os.chmod(self.root, 0o755)
        with self.assertRaises(ProtocolError):
            request_stop(self.root)
        os.chmod(self.root, 0o700)


class DiscoveryAndFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_launchd_template_manages_only_bridge_with_bounded_failure_restart(self):
        import plistlib
        template = Path(__file__).resolve().parents[1] / "config" / "launchd.example.plist"
        value = plistlib.loads(template.read_bytes())
        self.assertTrue(value["RunAtLoad"])
        self.assertEqual(value["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(value["ThrottleInterval"], 30)
        self.assertEqual(value["ExitTimeOut"], 120)
        self.assertEqual(value["Umask"], 0o077)
        self.assertEqual(value["ProgramArguments"][1:3], ["-m", "wx_clawbot.managed"])
        self.assertEqual(value["StandardOutPath"], "/dev/null")
        self.assertEqual(value["StandardErrorPath"], "/dev/null")
        self.assertEqual(set(value["EnvironmentVariables"]), {"PATH"})

    async def test_component_group_reports_only_safe_labels_and_types(self):
        async def bad():
            raise ValueError("token=private message body")
        with self.assertRaises(ComponentError) as caught:
            await component_task("channel_receive", bad())
        report = failure_report(ExceptionGroup("private", [caught.exception]))
        self.assertEqual(report[0]["component"], "channel_receive")
        self.assertEqual(report[0]["error_type"], "ValueError")
        self.assertIn("本人绑定", report[0]["message"])
        self.assertNotIn("private", json.dumps(report))

    async def test_daemon_discovery_uses_only_version_with_explicit_home(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as home, patch("wx_clawbot.runtime_discovery.shutil.which", return_value="/fixture/codex"), patch("wx_clawbot.runtime_discovery.subprocess.run") as run:
            run.return_value = CompletedProcess([], 0, json.dumps({"status": "running", "socketPath": "/fixture/control.sock", "managedCodexPath": "/fixture/native/codex"}))
            self.assertEqual(discover_runtime(Path(home))[0], Path("/fixture/control.sock"))
            self.assertEqual(run.call_args.args[0], ["/fixture/codex", "app-server", "daemon", "version"])
            self.assertEqual(run.call_args.kwargs["env"]["CODEX_HOME"], str(Path(home).resolve()))
            for response in ({"status": "stopped"}, {"status": "running", "socketPath": "relative", "managedCodexPath": "/fixture/native"}, []):
                run.return_value = CompletedProcess([], 0, json.dumps(response))
                with self.assertRaises(ValueError):
                    discover_runtime(Path(home))
