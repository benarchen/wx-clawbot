import asyncio
import gc
import unittest
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_runtime_state import RuntimeFixture
from test_wechat_state import message
from wx_clawbot.agents.rpc import ConnectionLost
from wx_clawbot.config import Project
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import LaunchRegistry
from wx_clawbot.routing import RouteError
from wx_clawbot.runtime_lifecycle import BridgeRuntime


class RuntimeLifecycleTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.backend = SimpleNamespace(identity=AsyncMock(return_value=None),
                                       connect=AsyncMock(), launch=AsyncMock(), probe=AsyncMock())
        self.host = HostLifecycle(self.backend)
        self.addAsyncCleanup(self.host.close)
        self.starter = SimpleNamespace(registry=LaunchRegistry(self.root / "launches"), start=AsyncMock())
        self.runtime = BridgeRuntime((Project("fixture", self.root),), self.state, self.starter,
                                      self.host, None, None, self.root)
        await self.runtime.initialize()
        self.index = 100

    async def command(self, text):
        self.index += 1
        batch = await self.state.accept_batch({"ret": 0, "msgs": [message(self.index, text=text)]}, phase="runtime")
        await self.runtime.prepare(batch["accepted"][0])

    async def replies(self):
        return await self.state._call(lambda: [row[0] for row in self.state.db.execute("SELECT text FROM outbox")])

    async def test_static_commands_work_without_host_or_native_and_never_launch(self):
        for text in ("/help", "/projects", "/status"):
            await self.command(text)
        rows = await self.replies()
        self.assertEqual(len(rows), 3)
        self.assertTrue(any("未就绪" in row for row in rows))
        self.backend.identity.assert_not_awaited()
        self.backend.launch.assert_not_awaited()
        self.starter.start.assert_not_awaited()

    async def test_invalid_project_and_new_without_directory_do_not_launch(self):
        for text in ("/cd missing", "/new"):
            with self.assertRaises(RouteError):
                await self.command(text)
        self.backend.launch.assert_not_awaited()
        self.assertEqual(await self.state.tasks(), [])

    async def test_sessions_can_launch_app_and_explain_no_verified_native_sessions(self):
        async def launched():
            self.backend.identity.return_value = "application"
        self.backend.launch.side_effect = launched
        self.backend.connect.return_value = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        with patch("wx_clawbot.hosts.discovery.ItermDirectory.discover", new=AsyncMock(return_value=[])):
            await self.command("/sessions")
        rows = await self.replies()
        self.assertEqual(len(rows), 2)  # Progress and final use distinct durable IDs.
        self.assertTrue(any("暂无已核验" in row for row in rows))
        self.backend.launch.assert_awaited_once()
        self.starter.start.assert_not_awaited()
        self.assertEqual(self.host.state, "ready")

    async def test_host_watch_connects_running_app_without_launch_or_native_dependency(self):
        self.backend.identity.return_value = "application"
        self.backend.connect.return_value = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        job = asyncio.create_task(self.runtime.watch_host())
        await asyncio.sleep(.01)
        self.assertEqual(self.host.state, "ready")
        self.backend.launch.assert_not_awaited()
        job.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await job

    async def test_offline_listing_does_not_erase_observer_waiting_for_revalidation(self):
        observer = {"session_id": "old-session", "thread_id": "old-thread"}
        await self.state.save_routes({"cwd": str(self.root), "revision": 7, "observer": observer,
                                      "last_managed": []})
        await self.runtime.initialize()
        self.backend.identity.return_value = "application"
        self.backend.connect.return_value = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        with patch("wx_clawbot.hosts.discovery.ItermDirectory.discover", new=AsyncMock(return_value=[])):
            await self.command("/sessions")
        snapshot = await self.state.load_routes()
        self.assertEqual(snapshot["observer"], observer)
        self.assertIsNone(snapshot["target"])

    async def test_cd_when_native_missing_connects_host_but_never_creates_codex(self):
        self.backend.identity.return_value = "application"
        self.backend.connect.return_value = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        await self.command("/cd fixture")
        self.assertTrue(any("没有创建" in row for row in await self.replies()))
        self.starter.start.assert_not_awaited()
        self.assertEqual(await self.state.tasks(), [])
        self.assertEqual(self.runtime.controller.selection_pending, 0)

    async def test_new_preserves_saved_directory_without_restoring_unverified_target(self):
        await self.state.save_routes({"cwd": str(self.root)})
        await self.runtime.initialize()
        self.assertEqual(self.runtime.controller.routes.cwd, self.root)
        self.assertIsNone(self.runtime.controller.routes.target)

    async def test_plain_message_while_unavailable_never_becomes_a_deferred_task(self):
        with self.assertRaises(RouteError):
            await self.command("must not run after reconnect")
        self.assertEqual(await self.state.tasks(), [])
        self.backend.launch.assert_not_awaited()

    async def test_received_only_cancel_during_native_outage_is_local_and_atomic(self):
        task = await self.admit(1)
        await self.state.task_update(task["id"], "received")
        await self.command("/stop " + task["id"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "cancelled")
        self.backend.launch.assert_not_awaited()

    async def test_native_disconnect_preserves_received_but_marks_attempts_unknown(self):
        first, second = await self.admit(1), await self.admit(2)
        await self.state.task_update(first["id"], "received")
        await self.state.task_update(second["id"], "running", turn_id="fixture-turn")
        await self.state.native_disconnected()
        self.assertEqual((await self.state.tasks(task_id=first["id"]))["state"], "received")
        self.assertEqual((await self.state.tasks(task_id=second["id"]))["state"], "unknown")
        self.assertEqual(len(await self.state.tasks()), 2)

    async def test_native_discovery_failure_keeps_static_commands_alive(self):
        with patch.object(self.runtime, "connect_native", new=AsyncMock(side_effect=ValueError("private endpoint"))):
            job = asyncio.create_task(self.runtime.run())
            await asyncio.sleep(.01)
            await self.command("/help")
            await self.command("/status")
            self.assertFalse(job.done())
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
        self.assertEqual(len(await self.replies()), 2)
        self.backend.launch.assert_not_awaited()

    async def test_live_native_loss_retires_one_consumer_and_returns_to_offline(self):
        failed = asyncio.Event()
        async def event(**_):
            await failed.wait()
            raise ConnectionLost("disconnected")
        native = SimpleNamespace(rpc=SimpleNamespace(next_event=event), close=AsyncMock())
        with patch.object(self.runtime, "connect_native", new=AsyncMock(return_value=(native, Path("/fixture/codex")))):
            job = asyncio.create_task(self.runtime.run())
            await asyncio.sleep(.01)
            self.assertTrue(self.runtime.controller.native_ready)
            failed.set()
            await asyncio.sleep(.02)
            self.assertFalse(self.runtime.controller.native_ready)
            await self.command("/status")
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
        native.close.assert_awaited_once()
        self.assertEqual(self.runtime.native_generation, 1)

    async def test_native_outage_revokes_dispatch_before_waiting_for_host_restore_lock(self):
        failed = asyncio.Event()
        async def event(**_):
            await failed.wait()
            raise ConnectionLost("disconnected during host restore")
        peer = SimpleNamespace(rpc=SimpleNamespace(next_event=event), close=AsyncMock())
        with patch.object(self.runtime, "connect_native", new=AsyncMock(return_value=(peer, Path("/fixture/codex")))):
            job = asyncio.create_task(self.runtime.run())
            try:
                await asyncio.sleep(.01)
                self.assertTrue(self.runtime.controller.native_ready)
                # A real host refresh owns the same transition lock. Losing
                # native transport must revoke dispatch before cleanup can
                # acquire it; status cannot keep claiming native is usable.
                async with self.runtime.transition:
                    failed.set()
                    async with asyncio.timeout(.5):
                        while self.runtime.native_state != "unavailable":
                            await asyncio.sleep(0)
                    self.assertFalse(self.runtime.controller.native_ready)
                    await self.command("/status")
                    self.assertTrue(any("原生运行时：未就绪" in row for row in await self.replies()))
            finally:
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job

    async def test_twenty_native_recoveries_keep_one_consumer_and_release_old_engines(self):
        from wx_clawbot.execution import Execution

        baseline = set(asyncio.all_tasks())
        engines, peers = [], []
        drained = asyncio.Event()
        live_consumers = maximum_consumers = 0

        def execution(controller):
            engine = Execution(controller)
            engines.append(weakref.ref(engine))
            return engine

        async def connect():
            if len(peers) == 20:
                drained.set()
                await asyncio.Event().wait()
            async def event(**_):
                nonlocal live_consumers, maximum_consumers
                live_consumers += 1
                maximum_consumers = max(maximum_consumers, live_consumers)
                try:
                    raise ConnectionLost("controlled peer disconnect")
                finally:
                    live_consumers -= 1
            peer = SimpleNamespace(rpc=SimpleNamespace(next_event=event), close=AsyncMock())
            peers.append(peer)
            return peer, Path("/fixture/codex")

        with patch.object(self.runtime, "connect_native", side_effect=connect), \
                patch("wx_clawbot.runtime_lifecycle.Execution", side_effect=execution):
            job = asyncio.create_task(self.runtime.run())
            try:
                await asyncio.wait_for(drained.wait(), 30)
            finally:
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job
        await asyncio.sleep(0)
        gc.collect()
        self.assertEqual(len(peers), 20)
        self.assertEqual(maximum_consumers, 1)
        self.assertEqual(live_consumers, 0)
        self.assertTrue(all(peer.close.await_count == 1 for peer in peers))
        self.assertTrue(all(reference() is None for reference in engines))
        self.assertFalse(set(asyncio.all_tasks()) - baseline)
        self.backend.launch.assert_not_awaited()

    async def test_retired_command_prepared_before_swap_cannot_mutate_later(self):
        self.index += 1
        batch = await self.state.accept_batch({"ret": 0, "msgs": [message(self.index, text="/sessions")]}, phase="runtime")
        old = self.runtime.controller
        work = old.prepare(batch["accepted"][0])
        await old.retire()
        await work
        self.backend.launch.assert_not_awaited()
        self.assertEqual(old.selection_pending, 0)
        self.assertTrue(any("连接已变化" in row for row in await self.replies()))


class ForegroundDegradedTests(RuntimeFixture):
    async def test_full_dynamic_work_slots_do_not_block_static_commands_or_controls(self):
        from wx_clawbot.commands import parse_command
        from wx_clawbot.operations import StopRequested
        from wx_clawbot.service import poll

        handled, refused = [], []
        async def work(text):
            name = parse_command(text).name
            if name in {"help", "projects", "status"}:
                handled.append(name)
                return
            if name == "stop":
                handled.append("stop")
            await asyncio.Event().wait()
        controller = SimpleNamespace(state=self.state, prepare=lambda incoming: work(incoming.text),
                                     reply=AsyncMock(side_effect=lambda m, *a, **k: refused.append(m.text)))
        count = 0
        async def updates(*_):
            nonlocal count
            count += 1
            if count == 1:
                texts = ["ordinary" for _ in range(35)] + ["/help", "/projects", "/status", "/stop task-id"]
                return {"ret": 0, "msgs": [message(i+100, text=text) for i, text in enumerate(texts)]}
            while "stop" not in handled:
                await asyncio.sleep(0)
            raise StopRequested()
        with self.assertRaises(StopRequested):
            await asyncio.wait_for(poll(controller, SimpleNamespace(updates=updates)), .5)
        self.assertEqual(handled, ["help", "projects", "status", "stop"])
        self.assertEqual(len(refused), 3)

    async def test_serve_receives_and_handles_owner_commands_before_any_dependency_exists(self):
        from wx_clawbot.operations import StopRequested
        from wx_clawbot.service import serve

        received = False
        async def updates(*_):
            nonlocal received
            if not received:
                received = True
                return {"ret": 0, "msgs": [message(100, text="/help"), message(101, text="/projects")]}
            await asyncio.Event().wait()
        async def stop_when_handled():
            while (await self.state.delivery_counts()).get("pending", 0) != 2:
                await asyncio.sleep(.001)
            raise StopRequested()
        async def sender_wait():
            await asyncio.Event().wait()
        instance = SimpleNamespace(health=lambda _: None, close=lambda: None, watch_stop=stop_when_handled)
        backend = SimpleNamespace(identity=AsyncMock(return_value=None), launch=AsyncMock())
        host = HostLifecycle(backend)
        api = SimpleNamespace(updates=updates)
        http = SimpleNamespace(close=AsyncMock())
        events = []
        with patch("wx_clawbot.service.load_credentials", return_value=self.credentials), \
                patch("wx_clawbot.service.RuntimeState.open", new=AsyncMock(return_value=self.state)), \
                patch("wx_clawbot.service.ForegroundInstance", return_value=instance), \
                patch("wx_clawbot.service.HostLifecycle", return_value=host), \
                patch("wx_clawbot.service.WeixinHttp", return_value=http), \
                patch("wx_clawbot.service.WechatApi", return_value=api), \
                patch("wx_clawbot.service.Sender.run", new=AsyncMock(side_effect=sender_wait)), \
                patch.object(BridgeRuntime, "connect_native", new=AsyncMock(side_effect=ValueError("daemon absent"))):
            await asyncio.wait_for(serve((Project("fixture", self.root),), self.root, None, None,
                                         self.root, emit=events.append), .5)
        self.assertTrue(any(e["status"] == "foreground_ready" for e in events))
        backend.launch.assert_not_awaited()
        http.close.assert_awaited_once()
