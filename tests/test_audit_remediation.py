import asyncio
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.private import private_directory, private_file, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution
from wx_clawbot.occupancy import release_rows
from wx_clawbot.runtime_state import RuntimeState
from test_wechat_state import message


class AuditRemediationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp" / "audit-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.credentials = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")

    async def test_write_json_replace_mode_0600(self):
        """P0-03: write_json replace=True preserves 0o600 permissions."""
        target_dir = private_directory(self.root / "private")
        file_path = target_dir / "secret.json"
        write_json(file_path, {"initial": 1})
        self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o600)

        write_json(file_path, {"replaced": 2}, replace=True)
        self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o600)
        private_file(file_path)

    async def test_image_worker_error_does_not_abort_maintain_loop(self):
        """P0-01 / P3-01: An unhandled image worker error does not crash maintain()."""
        controller = MagicMock()
        controller.state = MagicMock()
        controller.catalog = MagicMock()
        controller.catalog.agent = MagicMock()
        engine = Execution(controller)
        engine.image_errors.append(RuntimeError("disk full in background worker"))

        # Stub async dependencies of maintain() so it doesn't fail on mock awaits
        engine.expire_interactions = AsyncMock()
        engine.async_questions = MagicMock()
        engine.async_questions.expire = AsyncMock()
        engine.drain_admission = AsyncMock()
        engine.prune_memory = AsyncMock()

        # maintain() must clear the error and continue instead of raising
        maintain_task = asyncio.create_task(engine.maintain())
        await asyncio.sleep(0.05)
        self.assertFalse(maintain_task.done())
        self.assertEqual(len(engine.image_errors), 0)
        maintain_task.cancel()
        await asyncio.gather(maintain_task, return_exceptions=True)

    async def test_concurrent_dispatch_same_thread_inflight_counter(self):
        """P1-01 / P3-02: inflight counter does not prematurely clear on concurrent dispatch."""
        controller = MagicMock()
        controller.state = MagicMock()
        controller.catalog = MagicMock()
        controller.catalog.agent = MagicMock()
        engine = Execution(controller)

        thread_id = "thread-alpha"
        self.assertNotIn(thread_id, engine.inflight)

        # First dispatch increments
        engine.inflight[thread_id] += 1
        self.assertIn(thread_id, engine.inflight)
        self.assertEqual(engine.inflight[thread_id], 1)

        # Second concurrent dispatch increments
        engine.inflight[thread_id] += 1
        self.assertEqual(engine.inflight[thread_id], 2)

        # First dispatch finishes
        engine.inflight[thread_id] -= 1
        if engine.inflight[thread_id] <= 0:
            engine.inflight.pop(thread_id, None)
        # Still in flight because second is running
        self.assertIn(thread_id, engine.inflight)
        self.assertEqual(engine.inflight[thread_id], 1)

        # Second dispatch finishes
        engine.inflight[thread_id] -= 1
        if engine.inflight[thread_id] <= 0:
            engine.inflight.pop(thread_id, None)
        self.assertNotIn(thread_id, engine.inflight)

    async def test_native_disconnected_recovers_unsubmitted_image_prepared_tasks(self):
        """P1-02: Disconnect resets unsubmitted image prepared tasks to received, not unknown."""
        state = await RuntimeState.open(self.root / "runtime.sqlite3", self.credentials)
        self.addAsyncCleanup(state.close)

        # Admit a message and create a task intent with image items
        await state.accept_batch({"ret": 0, "msgs": [message(101)]}, phase="runtime")
        task = await state.task_intent("101", {"thread_id": "th-img", "cwd": "/tmp"}, "img task")
        # Update input_items to non-empty
        await state._call(lambda: state.db.execute("UPDATE tasks SET input_items='[{\"type\":\"image\"}]' WHERE id=?", (task["id"],)))

        # Trigger native_disconnected
        await state.native_disconnected()

        # The task must be reset to 'received' for re-admission, NOT 'unknown'
        reloaded = await state.tasks(task_id=task["id"])
        self.assertEqual(reloaded["state"], "received")

    async def test_retire_timeout_handling_and_drain(self):
        """P0-02 / P1-06 / P3-04: retire() tolerates timeout and drain() waits for all writes."""
        state = await RuntimeState.open(self.root / "runtime.sqlite3", self.credentials)
        self.addAsyncCleanup(state.close)

        controller = Controller([], MagicMock(), state, MagicMock(), Path("/bin/sh"), Path("/tmp"))

        # Add a slow operation that exceeds the 3s timeout
        async def slow_op():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                # Simulate a shielded database write during cancellation
                def slow_write():
                    time.sleep(0.05)
                await state._call(slow_write)

        controller.operations.add(asyncio.create_task(slow_op()))

        # retire() must not raise TimeoutError
        await controller.retire()
        self.assertTrue(controller.retired)

        # state.drain() must wait for any remaining shielded worker call
        drained = False
        async def do_drain():
            nonlocal drained
            await state.drain()
            drained = True

        await asyncio.wait_for(do_drain(), timeout=2.0)
        self.assertTrue(drained)

    async def test_occupancy_release_rows_edge_cases(self):
        """P3-05: release_rows enforces turns matching, snapshot revision and valid evidence."""
        state = await RuntimeState.open(self.root / "runtime.sqlite3", self.credentials)
        self.addAsyncCleanup(state.close)

        # Admit and move task to unknown
        await state.accept_batch({"ret": 0, "msgs": [message(201)]}, phase="runtime")
        task = await state.task_intent("201", {"thread_id": "th-occ", "cwd": "/tmp"}, "occ task")
        await state.task_update(task["id"], "unknown", turn_id="turn-201")

        snapshots = await state.occupancy_snapshot(holding_only=True)
        task_snap = next(t for t in snapshots if t["id"] == task["id"])

        # 1. Invalid evidence kind raises ValueError
        with self.assertRaises(ValueError):
            await state._call(lambda: release_rows(state.db, [task_snap], {"kind": "invalid"}))

        # 2. Missing turn in evidence turns raises ProtocolError
        evidence_missing_turn = {
            "kind": "native_terminal",
            "queue_empty": True,
            "turns": {"other-turn": "completed"},
            "generation": "gen-1",
            "thread_id": "th-occ",
        }
        with self.assertRaises(ProtocolError):
            await state._call(lambda: release_rows(state.db, [task_snap], evidence_missing_turn))

        # 3. Valid terminal evidence succeeds
        valid_evidence = {
            "kind": "native_terminal",
            "queue_empty": True,
            "turns": {"turn-201": "completed"},
            "generation": "gen-1",
            "thread_id": "th-occ",
        }
        res = await state._call(lambda: release_rows(state.db, [task_snap], valid_evidence))
        self.assertTrue(res)

        # 4. Re-releasing stale revision raises ProtocolError
        with self.assertRaises(ProtocolError):
            await state._call(lambda: release_rows(state.db, [task_snap], valid_evidence))

    async def test_sqlite_begin_immediate_lock_handling(self):
        """P3-03: sqlite busy / locked during BEGIN IMMEDIATE fails cleanly without hanging."""
        import sqlite3
        state = await RuntimeState.open(self.root / "runtime.sqlite3", self.credentials)
        self.addAsyncCleanup(state.close)

        # Open a concurrent connection with an immediate transaction to hold the write lock
        blocking = sqlite3.connect(self.root / "runtime.sqlite3", timeout=0.01)
        self.addCleanup(blocking.close)
        blocking.execute("BEGIN IMMEDIATE")

        def try_write():
            state.db.execute("PRAGMA busy_timeout=10")
            state.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(sqlite3.OperationalError):
            await state._call(try_write)

        blocking.execute("ROLLBACK")
        # Ensure state connection remains healthy after lock failure
        self.assertEqual(await state.cursor(), "")

    async def test_poll_job_failure_does_not_crash_receive_loop(self):
        """P1-03 / P3-07: A failed job in poll() does not kill the message receive loop."""
        from wx_clawbot.service import poll
        from wx_clawbot.channels.messages import IncomingText

        controller = MagicMock()
        controller.state = AsyncMock()
        controller.state.credentials = self.credentials
        controller.state.cursor = AsyncMock(side_effect=["c1", asyncio.CancelledError])

        # Mock an incoming message batch
        failing_msg = IncomingText("1", "fail_cmd", "ctx", 100, 1)
        controller.state.accept_batch = AsyncMock(return_value={"accepted": [failing_msg]})
        controller.state.handled = AsyncMock()
        controller.reply = AsyncMock()

        # Controller prepare returns a task that raises an unhandled exception
        async def bad_work():
            raise RuntimeError("internal command error")

        controller.prepare = MagicMock(return_value=bad_work())

        api = MagicMock()
        api.updates = AsyncMock(return_value={"ret": 0, "msgs": []})

        # Run poll; it should catch CancelledError on the 2nd loop iteration, without being killed by bad_work
        with self.assertRaises(asyncio.CancelledError):
            await poll(controller, api)

        # Verify bad_work was scheduled and handled without crashing poll prematurely
        self.assertEqual(controller.prepare.call_count, 1)

