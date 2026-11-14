import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from wx_clawbot.agents.base import Capabilities
from wx_clawbot.agents.rpc import OutcomeUnknown
from wx_clawbot.agents.queue import QueueFull
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.channels.private import write_json
from wx_clawbot.commands import parse_command
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller, RouteCommitFailed
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.lifecycle import HostLifecycle, HostUnavailable, ItermBackend
from wx_clawbot.hosts.visible import LaunchPending, LaunchRegistry
from wx_clawbot.interactions import APPROVAL, QUESTION
from wx_clawbot.routing import RouteError, Target
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.sessions import SessionUnbound
from test_wechat_state import message


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp" / "controller-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        projects = []
        self.sessions = []
        for alias in ("one", "two"):
            cwd = self.root / alias
            cwd.mkdir()
            projects.append(Project(alias, cwd))
            target = Target("session-" + alias, alias, cwd, "managed")
            self.sessions.append(SimpleNamespace(target=target, title=alias,
                                  binding=SimpleNamespace(thread_id="thread-" + alias, runtime_identity=(1, 2),
                                                          native_session_id="native-" + alias)))
        self.agent = SimpleNamespace(runtime_identity=(1, 2), capabilities=Capabilities(observe=True, queue=True, interrupt=True, shared_interactions=True),
                                     observe_loaded=AsyncMock(), unsubscribe=AsyncMock(),
                                     inspect=AsyncMock(return_value={"status": {"type": "idle"}}),
                                     rpc=SimpleNamespace(request=AsyncMock(), respond=AsyncMock()))
        self.catalog = SimpleNamespace(agent=self.agent, sessions={s.target.session_id: s for s in self.sessions},
                                       managed_threads=set(), unverified=[], directory=None, remember_verified=Mock(),
                                       include_directory=Mock(), legacy_targets={}, scope_note="注册根与已知目录。",
                                       discover=AsyncMock(return_value=tuple(self.sessions)))
        async def require(target):
            return self.catalog.sessions[target.session_id]
        self.catalog.require = AsyncMock(side_effect=require)
        account = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")
        self.state = await RuntimeState.open(self.root / "private" / "runtime.sqlite3", account)
        self.addAsyncCleanup(self.state.close)
        starter = SimpleNamespace(registry=LaunchRegistry(self.root / "launches"), start=AsyncMock())
        self.controller = Controller(tuple(projects), self.catalog, self.state, starter, Path("/fixture/codex"), Path("/fixture/home"))
        self.engine = Execution(self.controller)
        key_patch = patch("wx_clawbot.execution.repository_key", new=AsyncMock(side_effect=lambda cwd, root: "directory:" + str(root)))
        key_patch.start()
        self.addCleanup(key_patch.stop)
        conflict_key = patch("wx_clawbot.admission.repository_key", new=AsyncMock(side_effect=lambda cwd, root: "directory:" + str(root)))
        conflict_key.start()
        self.addCleanup(conflict_key.stop)
        self.queue = SimpleNamespace(add=AsyncMock(return_value={"id": "fixture-queue"}),
                                     delete=AsyncMock(return_value=False), request_interrupt=AsyncMock(return_value={}),
                                     list=AsyncMock(return_value=[]))
        self.engine.queue = lambda *_: self.queue
        self.counter = 0

    async def incoming(self, text):
        self.counter += 1
        batch = await self.state.accept_batch({"ret": 0, "msgs": [message(self.counter, text=text)]}, phase="runtime")
        return batch["accepted"][0]

    async def command(self, text):
        await self.controller.prepare(await self.incoming(text))

    async def select(self):
        await self.command("/sessions")
        await self.command("/focus 2")

    async def test_focus_b_observe_a_and_detach_leave_frozen_execution_b(self):
        await self.select()
        await self.command("/attach 1")
        self.assertEqual(self.controller.routes.target, self.sessions[1].target)
        self.assertEqual(self.controller.routes.observer, self.sessions[0].target)
        work = self.controller.prepare(await self.incoming("task to B"))
        await self.command("/detach")
        await self.command("/focus 1")
        await work
        task = (await self.state.tasks())[0]
        self.assertEqual(task["thread_id"], "thread-two")
        self.assertEqual(task["target"]["project_alias"], "two")
        self.assertIsNone(self.controller.routes.observer)
        self.assertTrue(self.controller.subscriptions.has(self.sessions[1].target, "task-" + task["id"]))

    async def test_hung_session_discovery_has_deadline_and_releases_selection(self):
        self.controller.selection_timeout = .02
        async def hung(*_):
            await asyncio.Event().wait()
        self.catalog.discover.side_effect = hung
        await asyncio.wait_for(self.command("/sessions"), .3)
        self.assertEqual(self.controller.selection_pending, 0)
        self.assertFalse(self.controller.changes.locked())
        rows = await self.state._call(lambda: list(self.state.db.execute("SELECT text FROM outbox")))
        self.assertTrue(any("超时" in row[0] for row in rows))
        self.catalog.discover.side_effect = None
        await self.command("/sessions")
        self.assertIsNotNone(self.controller.routes.list)

    async def test_sessions_preserves_focused_and_managed_selection_and_all_leases_without_side_effects(self):
        await self.select()
        await self.command("/attach 1")
        await self.command("original task")
        for mode in ("focused", "managed"):
            self.controller.routes.mode = mode
            before = self.controller._snapshot(self.controller.routes)
            await self.state.save_routes(before)
            leases = {key: roles.copy() for key, roles in self.controller.subscriptions.roles.items()}
            tasks = await self.state.tasks()
            prior_list = self.controller.routes.list
            self.controller.host = SimpleNamespace(ensure=AsyncMock(), verified=Mock())
            self.controller.before_change = AsyncMock(return_value=True)
            self.agent.observe_loaded.reset_mock()
            self.agent.unsubscribe.reset_mock()
            with patch.object(self.state, "save_routes", new=AsyncMock()) as save, \
                    patch.object(self.engine, "reconcile", new=AsyncMock()) as reconcile, \
                    patch.object(self.controller, "_refresh", new=AsyncMock()) as refresh:
                await self.command("/ss two")
            self.assertIsNot(self.controller.routes.list, prior_list)
            self.assertEqual(self.controller._snapshot(self.controller.routes), before)
            self.assertEqual(await self.state.load_routes(), before)
            self.assertEqual(self.controller.subscriptions.roles, leases)
            self.assertEqual(await self.state.tasks(), tasks)
            for operation in (save, reconcile, refresh, self.controller.before_change,
                              self.agent.observe_loaded, self.agent.unsubscribe,
                              self.controller.host.ensure, self.controller.starter.start):
                operation.assert_not_awaited()
            self.controller.host.verified.assert_not_called()
        self.catalog.discover.assert_awaited_with("two")

    async def test_empty_filtered_list_preserves_target_and_explicit_unfocus_only_releases_route(self):
        await self.select()
        await self.command("/attach 2")
        await self.command("task retained")
        target = self.controller.routes.target
        self.catalog.discover.return_value = ()
        await self.command("/sessions no-match")
        self.assertEqual(self.controller.routes.target, target)
        self.assertEqual(self.controller.routes.list.targets, ())
        self.agent.unsubscribe.reset_mock()
        await self.command("/uf")
        self.assertIsNone(self.controller.routes.target)
        self.assertEqual(self.controller.routes.observer, target)
        self.assertFalse(self.controller.subscriptions.has(target, "route"))
        self.assertTrue(self.controller.subscriptions.has(target, "observer"))
        task = (await self.state.tasks())[0]
        self.assertTrue(self.controller.subscriptions.has(target, "task-" + task["id"]))
        self.agent.unsubscribe.assert_not_awaited()

    async def test_query_failure_preserves_original_list_deadline_target_and_durable_state(self):
        from wx_clawbot.catalog import DiscoveryUnavailable
        await self.select()
        before = await self.state.load_routes()
        old = self.controller.routes.list
        for failure in (DiscoveryUnavailable("Incomplete native listing"), TimeoutError()):
            self.catalog.discover.side_effect = failure
            await self.command("/sessions")
            self.assertIs(self.controller.routes.list, old)
            self.assertEqual(self.controller.routes.target, self.sessions[1].target)
            self.assertEqual(await self.state.load_routes(), before)
        self.agent.unsubscribe.assert_not_awaited()

    async def test_native_generation_change_during_query_cannot_publish_list(self):
        await self.select()
        old = self.controller.routes.list
        async def changed(*_):
            self.controller.native_generation += 1
            return tuple(self.sessions)
        self.catalog.discover.side_effect = changed
        await self.command("/sessions")
        self.assertIs(self.controller.routes.list, old)
        self.assertEqual(self.controller.routes.target, self.sessions[1].target)
        self.agent.unsubscribe.assert_not_awaited()

    async def test_query_does_not_block_or_retarget_an_ordinary_message(self):
        await self.select()
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(*_):
            entered.set()
            await release.wait()
            return tuple(reversed(self.sessions))
        self.catalog.discover.side_effect = slow
        work = asyncio.create_task(self.command("/sessions"))
        try:
            await asyncio.wait_for(entered.wait(), .5)
            self.assertEqual(self.controller.selection_pending, 0)
            with patch.object(self.engine, "submit", new=AsyncMock()) as submit:
                await self.command("message while querying")
            self.assertEqual(submit.await_args.args[1].target, self.sessions[1].target)
        finally:
            release.set()
            await work
        self.assertEqual(self.controller.routes.select(1), self.sessions[1].target)

    async def test_retired_query_does_not_publish_list_or_release_selection(self):
        await self.select()
        old = self.controller.routes.list
        entered = asyncio.Event()
        async def slow(*_):
            entered.set()
            await asyncio.Event().wait()
        self.catalog.discover.side_effect = slow
        work = asyncio.create_task(self.command("/sessions"))
        await asyncio.wait_for(entered.wait(), .5)
        await self.controller.retire()
        await work
        self.assertIs(self.controller.routes.list, old)
        self.assertEqual(self.controller.routes.target, self.sessions[1].target)
        self.assertFalse(self.controller.changes.locked())
        self.agent.unsubscribe.assert_not_awaited()

    async def test_failed_rollback_requests_native_recovery_without_blocking_status(self):
        from wx_clawbot.hosts.lifecycle import HostUnavailable
        await self.select()
        self.controller.host = SimpleNamespace(state="ready", phase="ready", generation=1, connection=object())
        self.controller.rollback_timeout = .02
        async def hung(*_):
            await asyncio.Event().wait()
        with patch.object(self.controller, "_change", new=AsyncMock(side_effect=HostUnavailable("rpc"))), \
                patch.object(self.controller, "_restore_roles", new=AsyncMock(side_effect=hung)):
            await asyncio.wait_for(self.command("/focus 1"), .3)
        self.assertTrue(self.controller.recovery_requested.is_set())
        self.assertFalse(self.controller.native_ready)
        self.assertEqual(self.controller.selection_pending, 0)
        self.assertFalse(self.controller.changes.locked())
        await self.command("/status")
        self.queue.add.assert_not_awaited()

    async def test_native_retirement_during_reply_joins_one_final_write(self):
        await self.select()
        before = await self.state.delivery_counts()
        entered, release = asyncio.Event(), asyncio.Event()
        queue_reply = self.state.queue_reply
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await queue_reply(*args, **kwargs)
        with patch.object(self.state, "queue_reply", side_effect=delayed):
            work = asyncio.create_task(self.command("/unfocus"))
            await entered.wait()
            retire = asyncio.create_task(self.controller.retire())
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(work, retire)
        self.assertEqual((await self.state.delivery_counts())["pending"], before["pending"] + 1)

    async def test_native_retirement_joins_pending_route_commit_before_recovery_reads(self):
        await self.select()
        entered, release = asyncio.Event(), asyncio.Event()
        save_routes = self.state.save_routes
        async def delayed(snapshot):
            entered.set()
            await release.wait()
            await save_routes(snapshot)
        with patch.object(self.state, "save_routes", side_effect=delayed):
            work = asyncio.create_task(self.command("/focus 1"))
            await entered.wait()
            retire = asyncio.create_task(self.controller.retire())
            await asyncio.sleep(.01)
            self.assertFalse(retire.done())
            release.set()
            await asyncio.gather(work, retire)
        self.assertEqual((await self.state.load_routes())["target"]["session_id"], self.sessions[0].target.session_id)

    async def test_native_generation_change_before_queue_add_prevents_submission(self):
        await self.select()
        host = SimpleNamespace(state="ready", phase="ready", generation=1, connection=object())
        self.controller.host = host
        update = self.state.task_update
        async def changed(task_id, state, **kwargs):
            result = await update(task_id, state, **kwargs)
            if state == "dispatching":
                self.controller.native_generation += 1
            return result
        with patch.object(self.state, "task_update", side_effect=changed):
            await self.command("never submit on stale proof")
        self.queue.add.assert_not_awaited()
        self.assertEqual((await self.state.tasks())[0]["state"], "failed")

    async def test_rejected_new_subscription_keeps_original_observer_and_focus(self):
        await self.select()
        await self.command("/attach 1")
        # B already has route lease, so fail freshness before a reused subscription.
        self.catalog.require.side_effect = PermissionError("target unavailable")
        await self.command("/attach 2")
        self.assertEqual(self.controller.routes.observer, self.sessions[0].target)
        self.assertEqual(self.controller.routes.target, self.sessions[1].target)

    async def test_failed_old_unsubscribe_does_not_commit_replacement_or_false_detach(self):
        await self.select()
        await self.command("/attach 1")
        self.agent.unsubscribe.side_effect = OutcomeUnknown("lost unsubscribe ACK")
        await self.command("/attach 2")
        self.assertEqual(self.controller.routes.observer, self.sessions[0].target)
        self.assertFalse(self.controller.subscriptions.has(self.sessions[1].target, "observer"))
        await self.command("/detach")
        self.assertEqual(self.controller.routes.observer, self.sessions[0].target)

    async def test_status_bypasses_an_in_progress_submission_and_unknown_never_resubmits(self):
        await self.select()
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(*args):
            entered.set()
            await release.wait()
            raise OutcomeUnknown("receipt lost")
        self.queue.add.side_effect = slow
        message = await self.incoming("one task")
        work = asyncio.create_task(self.controller.prepare(message))
        await asyncio.wait_for(entered.wait(), .5)
        await asyncio.wait_for(self.command("/status"), .5)
        release.set()
        await work
        self.assertEqual((await self.state.tasks())[0]["state"], "unknown")
        # Explicit duplicate uses the same source identity and cannot execute again.
        await self.controller.prepare(message)
        self.assertEqual(self.queue.add.await_count, 1)

    async def test_no_target_unknown_command_and_stale_list_cannot_become_tasks(self):
        for text in ("task with no target", "/unknown task"):
            with self.assertRaises((ValueError, RouteError)):
                self.controller.prepare(await self.incoming(text))
        await self.command("/sessions")
        self.controller.routes.clock = lambda: float("inf")
        with self.assertRaises(RouteError):
            self.controller.prepare(await self.incoming("/send 1 task"))
        self.assertEqual(await self.state.tasks(), [])

    async def test_running_interrupt_waits_for_native_terminal_receipt(self):
        await self.select()
        await self.command("run")
        task = (await self.state.tasks())[0]
        await self.state.task_update(task["id"], "running", turn_id="fixture-turn")
        await self.command("/stop " + task["id"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "stopping")
        await self.engine.complete("thread-two", {"id": "fixture-turn", "status": "interrupted", "items": [
            {"type": "userMessage", "clientId": task["client_id"]}]})
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "interrupted")

    async def test_queue_cancellation_needs_native_deleted_true(self):
        await self.select()
        await self.command("queued")
        task = (await self.state.tasks())[0]
        await self.command("/stop " + task["id"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "queued")
        self.queue.delete.return_value = True
        before = await self.state._call(lambda: self.state.db.execute("SELECT count(*) FROM outbox").fetchone()[0])
        await self.command("/stop " + task["id"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "cancelled")
        self.queue.request_interrupt.assert_not_awaited()
        rows = await self.state._call(lambda: list(self.state.db.execute(
            "SELECT id,priority,kind FROM outbox ORDER BY rowid LIMIT -1 OFFSET ?", (before,))))
        self.assertEqual(rows, [(task["id"] + "-final-1", 0, "final")])

    async def test_merged_native_turn_is_unknown_not_independent_success(self):
        await self.select()
        await self.command("task")
        task = (await self.state.tasks())[0]
        with self.assertRaisesRegex(ValueError, "merged"):
            await self.engine.complete("thread-two", {"id": "mixed", "status": "completed", "items": [
                {"type": "userMessage", "clientId": task["client_id"]},
                {"type": "userMessage", "clientId": "other-input"},
                {"type": "agentMessage", "text": "merged output"}]})
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")

    async def test_observation_does_not_replay_completion_without_a_new_start(self):
        await self.select()
        await self.command("/attach 1")
        before = await self.state.delivery_counts()
        turn = {"id": "historical-turn", "status": "completed", "items": [{"type": "agentMessage", "text": "old private output"}]}
        await self.engine.complete("thread-one", turn)
        self.assertEqual(await self.state.delivery_counts(), before)
        await self.engine.event({"method": "turn/started", "params": {"threadId": "thread-one", "turn": {"id": "new-turn"}}})
        await self.engine.complete("thread-one", {**turn, "id": "new-turn"})
        self.assertEqual((await self.state.delivery_counts())["pending"], before["pending"] + 1)

    async def test_control_with_plain_acceptance_word_is_not_native_approval(self):
        await self.select()
        await self.command("可以")
        self.agent.rpc.respond.assert_not_awaited()
        self.assertEqual(self.queue.add.await_args.args[0], "可以")

    async def test_new_pending_blocks_ordinary_text_and_reuses_source_launch_id(self):
        await self.select()
        self.controller.launch_timeout = 0
        with patch("wx_clawbot.controller.reconcile_launch", side_effect=LaunchPending("not ready")):
            incoming = await self.incoming("/new fixture title")
            work = self.controller.prepare(incoming)
            with self.assertRaises(RouteError):
                self.controller.prepare(await self.incoming("not to old target"))
            await work
            await self.controller.prepare(incoming)
        ids = [call.args[0] for call in self.controller.starter.start.await_args_list]
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(await self.state.tasks(), [])
        self.assertEqual(self.controller.selection_pending, 0)

    async def test_first_cd_waits_for_api_then_creates_once_while_help_remains_available(self):
        backend = ItermBackend()
        backend.identity = AsyncMock(return_value=None)
        async def launch():
            backend.identity.return_value = "same-app"
        backend.launch = AsyncMock(side_effect=launch)
        backend.connect = AsyncMock(return_value=SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock())))
        backend.probe = AsyncMock()
        entered, ready = asyncio.Event(), asyncio.Event()
        probes = 0
        async def transport():
            nonlocal probes
            probes += 1
            if probes == 1:
                raise HostUnavailable("connect")
            entered.set()
            await ready.wait()
        backend._probe_auth_transport = transport
        host = HostLifecycle(backend)
        self.addAsyncCleanup(host.close)
        self.controller.host = host
        self.catalog.discover.side_effect = [(), (self.sessions[0],)]
        with patch("wx_clawbot.controller.reconcile_launch", new=AsyncMock(
                return_value=SimpleNamespace(thread_id="thread-one"))):
            work = asyncio.create_task(self.command("/cd one"))
            try:
                await asyncio.wait_for(entered.wait(), .5)
                backend.connect.assert_not_awaited()
                self.controller.starter.start.assert_not_awaited()
                await asyncio.wait_for(self.command("/help"), .5)
                ready.set()
                await asyncio.wait_for(work, .5)
            finally:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
        backend.launch.assert_awaited_once()
        backend.connect.assert_awaited_once()
        self.controller.starter.start.assert_awaited_once()
        self.assertEqual(self.controller.routes.target, self.sessions[0].target)
        self.assertEqual(host.state, "ready")
        self.queue.add.assert_not_awaited()
        texts = await self.state._call(lambda: [row[0] for row in self.state.db.execute("SELECT text FROM outbox")])
        self.assertEqual(sum("会话已就绪并选中" in text for text in texts), 1)
        self.assertFalse(any("API 连接不可用" in text for text in texts))

    async def approval(self):
        await self.select()
        await self.command("/attach 1")
        await self.engine.event({"id": "native-request", "method": APPROVAL, "params": {
            "threadId": "thread-one", "turnId": "turn-a", "itemId": "item-a",
            "command": "fixture command", "availableDecisions": ["accept", "decline"]}})
        broker = self.engine.brokers["thread-one"]
        return broker, next(iter(broker.records.values()))

    async def test_first_native_answer_only_and_resolved_supersedes_unsent_prompt(self):
        broker, record = await self.approval()
        await self.command("/approve " + record.public_id)
        self.agent.rpc.respond.assert_awaited_once_with("native-request", {"decision": "accept"})
        await self.command("/deny " + record.public_id)
        self.assertEqual(self.agent.rpc.respond.await_count, 1)
        await self.engine.event({"method": "serverRequest/resolved", "params": {
            "threadId": "thread-one", "requestId": "native-request"}})
        self.assertEqual(record.state, "resolved")
        self.assertEqual((await self.state.delivery_counts())["superseded"], 1)
        self.assertEqual(self.controller.routes.target, self.sessions[1].target)

    async def test_invalid_binding_preserves_subscribed_events_but_refuses_new_dispatch(self):
        await self.select()
        await self.command("/attach 1")
        self.catalog.require.reset_mock()
        self.catalog.require.side_effect = SessionUnbound("Original process cannot be verified")
        await self.engine.event({"method": "turn/started", "params": {
            "threadId": "thread-one", "turn": {"id": "modal-turn"}}})
        await self.engine.event({"method": "item/started", "params": {
            "threadId": "thread-one", "turnId": "modal-turn",
            "item": {"type": "userMessage", "clientId": "desktop-client"}}})
        for method, params in ((APPROVAL, {"command": "fixture command"}),
                               (QUESTION, {"questions": [{"id": "q", "options": [{"label": "one"}]}]})):
            await self.engine.event({"id": method, "method": method, "params": {
                "threadId": "thread-one", "turnId": "modal-turn", "itemId": method, **params}})
        self.catalog.require.assert_not_awaited()
        records = list(self.engine.brokers["thread-one"].records.values())
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r.state == "pending" for r in records))
        await self.command("/approve " + records[0].public_id)
        self.agent.rpc.respond.assert_awaited_once_with(APPROVAL, {"decision": "accept"})
        await self.engine.event({"method": "serverRequest/resolved", "params": {
            "threadId": "thread-one", "requestId": APPROVAL}})
        self.assertEqual(records[0].state, "resolved")
        await self.command("new task must not pass an invalid original binding")
        self.queue.add.assert_not_awaited()
        self.assertEqual(len(await self.state.tasks()), 1)  # Only the observed native task.

    async def test_detach_preserves_pending_interaction_until_native_resolution(self):
        broker, record = await self.approval()
        await self.command("/detach")
        self.assertIsNone(self.controller.routes.observer)
        self.agent.unsubscribe.assert_not_awaited()
        await self.command("/deny " + record.public_id)
        self.agent.rpc.respond.assert_awaited_once_with("native-request", {"decision": "decline"})
        await self.engine.event({"method": "serverRequest/resolved", "params": {
            "threadId": "thread-one", "requestId": "native-request"}})
        self.agent.unsubscribe.assert_awaited_once_with("thread-one")

    async def test_expired_or_disconnected_request_does_not_send_an_answer(self):
        broker, record = await self.approval()
        broker.clock = lambda: record.deadline + 1
        await self.command("/approve " + record.public_id)
        broker.disconnect()
        await self.command("/deny " + record.public_id)
        self.agent.rpc.respond.assert_not_awaited()

    async def test_receive_order_survives_slow_first_endpoint_verification(self):
        await self.select()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.catalog.require.side_effect
        first = True
        async def delayed(target):
            nonlocal first
            if first:
                first = False
                entered.set()
                await release.wait()
            return await original(target)
        self.catalog.require.side_effect = delayed
        one = asyncio.create_task(self.controller.prepare(await self.incoming("first")))
        await entered.wait()
        two = asyncio.create_task(self.controller.prepare(await self.incoming("second")))
        await asyncio.sleep(0)
        self.queue.add.assert_not_awaited()
        release.set()
        await asyncio.gather(one, two)
        self.assertEqual([call.args[0] for call in self.queue.add.await_args_list], ["first", "second"])

    async def test_terminal_event_before_add_receipt_is_not_regressed_to_queued(self):
        await self.select()
        async def complete_before_receipt(text, client_id):
            await self.engine.complete("thread-two", {"id": "fast-turn", "status": "completed", "items": [
                {"type": "userMessage", "clientId": client_id}, {"type": "agentMessage", "text": "done"}]})
            return {"id": "late-queue-ack"}
        self.queue.add.side_effect = complete_before_receipt
        await self.command("fast task")
        task = (await self.state.tasks())[0]
        self.assertEqual(task["state"], "completed")
        counts = await self.state.delivery_counts()
        # sessions + focus + terminal reply; no stale acceptance or error reply.
        self.assertEqual(counts, {"pending": 3})

    async def test_session_list_displays_stable_ids_and_current_directory(self):
        await self.command("/sessions")
        reply = await self.state.claim_reply()
        for session in self.sessions:
            self.assertIn(session.target.session_id, reply["text"])
            self.assertIn(str(session.target.cwd), reply["text"])
        self.assertIn("会话列表 · 2 个", reply["text"])

    async def test_projects_reports_disappeared_directory_without_routing_or_native_actions(self):
        self.sessions[0].target.cwd.rename(self.root / "moved-one")
        await self.command("/projects")
        reply = await self.state.claim_reply()
        self.assertIn("**one** · ⚠️ 目录不可访问", reply["text"])
        self.assertIn("**two**", reply["text"])
        self.assertNotIn("可用", reply["text"])
        self.assertIsNone(self.controller.routes.target)
        self.catalog.require.assert_not_awaited()

    async def test_cd_reuses_explicitly_focused_managed_session_among_multiple_candidates(self):
        original = self.sessions[0]
        extra_target = Target("session-one-extra", "one", original.target.cwd, "managed")
        extra = SimpleNamespace(target=extra_target, title="extra", binding=SimpleNamespace(thread_id="thread-extra", runtime_identity=(1, 2), native_session_id="native-extra"))
        self.catalog.sessions[extra_target.session_id] = extra
        self.catalog.discover.return_value = (*self.sessions, extra)
        await self.command("/sessions")
        await self.command("/focus 3")
        await self.command("/cd one")
        self.assertEqual(self.controller.routes.target, extra_target)
        self.assertEqual(self.controller.routes.mode, "managed")
        self.controller.starter.start.assert_not_awaited()

    async def test_refresh_reconciles_unknown_launch_without_restarting_and_skips_other_projects(self):
        registry = self.controller.starter.registry
        record = {"version": 1, "launch_id": "a" * 32, "phase": "unknown", "project_alias": "one",
                  "project_root": str(self.sessions[0].target.cwd), "cwd": str(self.sessions[0].target.cwd)}
        write_json(registry.root / (record["launch_id"] + ".json"), record)
        other = {**record, "launch_id": "b" * 32, "project_alias": "unregistered"}
        write_json(registry.root / (other["launch_id"] + ".json"), other)
        with patch("wx_clawbot.controller.reconcile_launch", new=AsyncMock(return_value=SimpleNamespace(thread_id="thread-recovered"))) as reconcile:
            await self.controller._refresh()
        self.assertEqual(reconcile.await_count, 1)
        self.assertEqual(reconcile.await_args.args[1], record["launch_id"])
        self.assertIn("thread-recovered", self.catalog.managed_threads)
        self.controller.starter.start.assert_not_awaited()

    async def test_native_failure_cause_is_preserved_in_final_reply(self):
        await self.select()
        await self.command("task")
        task = (await self.state.tasks())[0]
        await self.engine.complete("thread-two", {"id": "failed-turn", "status": "failed",
            "error": {"message": "Fixture usage limit reached"},
            "items": [{"type": "userMessage", "clientId": task["client_id"]}]})
        reply = await self.state.claim_reply()
        self.assertIn("Fixture usage limit reached", reply["text"])
        self.assertIn("任务失败", reply["text"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "failed")

    async def test_recovery_keeps_external_merged_turn_unknown_without_stopping_service(self):
        from wx_clawbot.controller import target_record
        await self.select()
        await self.command('a previously submitted bridge task')
        bridge = (await self.state.tasks())[0]
        external = await self.state.external_task(target_record(self.sessions[1]), 'merged-turn')
        await self.state.task_update(external['id'], 'unknown')
        turn = {'id': 'merged-turn', 'status': 'completed', 'items': [
            {'type': 'userMessage', 'clientId': bridge['client_id']},
            {'type': 'userMessage', 'clientId': 'external-client'},
        ]}
        with patch.object(self.engine, 'read_turn', new=AsyncMock(return_value=turn)):
            await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=external['id']))['state'], 'unknown')
        self.assertEqual((await self.state.tasks(task_id=bridge['id']))['state'], 'queued')
        self.queue.add.assert_awaited_once()
        reply = await self.state.claim_reply()
        self.assertIn('保持未知', reply['text'])

    async def test_recovery_keeps_external_turn_unknown_when_client_conflicts(self):
        from wx_clawbot.controller import target_record
        await self.select()
        await self.command('another previously submitted task')
        bridge = (await self.state.tasks())[0]
        external = await self.state.external_task(target_record(self.sessions[1]), 'conflicting-turn',
                                                   native_client_id='external-client')
        await self.state.task_update(external['id'], 'unknown')
        turn = {'id': 'conflicting-turn', 'status': 'completed', 'items': [
            {'type': 'userMessage', 'clientId': bridge['client_id']},
        ]}
        with patch.object(self.engine, 'read_turn', new=AsyncMock(return_value=turn)):
            await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=external['id']))['state'], 'unknown')
        self.assertEqual((await self.state.tasks(task_id=bridge['id']))['state'], 'queued')
        self.queue.add.assert_awaited_once()

    async def test_restart_restores_independent_verified_targets_but_not_numeric_list(self):
        await self.select()
        await self.command("/attach 1")
        original = self.controller
        restored = Controller(tuple(original.routes.projects.values()), self.catalog, self.state,
                              original.starter, original.executable, original.codex_home)
        await restored.restore()
        self.assertEqual(restored.routes.target, self.sessions[1].target)
        self.assertEqual(restored.routes.observer, self.sessions[0].target)
        self.assertIsNone(restored.routes.list)
        with self.assertRaises(RouteError):
            restored.prepare(await self.incoming("/send 1 obsolete index"))
        self.queue.add.assert_not_awaited()

    async def test_changed_endpoint_cannot_restore_old_target_or_submit(self):
        await self.select()
        original = self.controller
        self.catalog.sessions.pop(self.sessions[1].target.session_id)
        restored = Controller(tuple(original.routes.projects.values()), self.catalog, self.state,
                              original.starter, original.executable, original.codex_home)
        await restored.restore()
        self.assertIsNone(restored.routes.target)
        self.assertIsNone((await self.state.load_routes())["target"])
        with self.assertRaises(RouteError):
            restored.prepare(await self.incoming("never replay"))
        self.queue.add.assert_not_awaited()

    async def test_host_recovery_rebinds_only_same_native_identity_and_invalidates_numbers(self):
        await self.select()
        await self.command("/attach 2")
        prior = self.sessions[1]
        prior.binding.runtime_identity = (1, 2)
        prior.binding.native_session_id = "native-two"
        replacement = SimpleNamespace(target=Target("new-terminal", "two", prior.target.cwd, "managed"),
                                      binding=SimpleNamespace(thread_id="thread-two", runtime_identity=(1, 2),
                                                              native_session_id="native-two"), title="two")
        async def refreshed(*_):
            self.catalog.sessions = {replacement.target.session_id: replacement}
            return (replacement,)
        self.catalog.discover.side_effect = refreshed
        await self.controller.recover_host()
        self.assertEqual(self.controller.routes.target, replacement.target)
        self.assertEqual(self.controller.routes.observer, replacement.target)
        self.assertIsNone(self.controller.routes.list)
        self.assertEqual(self.controller.last_managed[("two", prior.target.cwd)], replacement.target)
        self.agent.unsubscribe.assert_not_awaited()
        self.assertEqual(self.agent.observe_loaded.await_count, 1)
        self.queue.add.assert_not_awaited()

    async def test_host_recovery_refuses_reused_thread_with_changed_native_session(self):
        await self.select()
        prior = self.sessions[1]
        prior.binding.runtime_identity = (1, 2)
        prior.binding.native_session_id = "original-native"
        replacement = SimpleNamespace(target=Target("new-terminal", "two", prior.target.cwd, "managed"),
                                      binding=SimpleNamespace(thread_id="thread-two", runtime_identity=(1, 2),
                                                              native_session_id="changed-native"), title="two")
        async def refreshed(*_):
            self.catalog.sessions = {replacement.target.session_id: replacement}
            return (replacement,)
        self.catalog.discover.side_effect = refreshed
        await self.controller.recover_host()
        self.assertIsNone(self.controller.routes.target)
        self.assertIsNone(self.controller.routes.list)
        self.queue.add.assert_not_awaited()

    async def test_host_recovery_missing_binding_keeps_passive_observer_without_route(self):
        await self.select()
        await self.command("/attach 2")
        async def refreshed(*_):
            self.catalog.sessions = {}
            return ()
        self.catalog.discover.side_effect = refreshed
        await self.controller.recover_host()
        self.assertIsNone(self.controller.routes.target)
        self.assertEqual(self.controller.routes.observer, self.sessions[1].target)
        self.assertTrue(self.controller.subscriptions.has(self.sessions[1].target, "observer"))
        self.agent.unsubscribe.assert_not_awaited()

    async def test_failed_route_commit_restores_previous_leases_and_never_acknowledges_change(self):
        await self.select()
        await self.command("/attach 1")
        snapshot = await self.state.load_routes()
        counts = await self.state.delivery_counts()
        with patch.object(self.state, "save_routes", new=AsyncMock(side_effect=OSError("disk full"))):
            with self.assertRaises(RouteCommitFailed):
                await self.command("/focus 1")
        self.assertEqual(self.controller.routes.target, self.sessions[1].target)
        self.assertTrue(self.controller.subscriptions.has(self.sessions[1].target, "route"))
        self.assertFalse(self.controller.subscriptions.has(self.sessions[0].target, "route"))
        self.assertTrue(self.controller.subscriptions.has(self.sessions[0].target, "observer"))
        self.assertEqual(await self.state.load_routes(), snapshot)
        self.assertEqual(await self.state.delivery_counts(), counts)

    async def test_pending_focus_commit_does_not_expose_uncommitted_target(self):
        await self.select()
        entered, release = asyncio.Event(), asyncio.Event()
        save = self.state.save_routes
        async def delayed(snapshot):
            entered.set()
            await release.wait()
            await save(snapshot)
        with patch.object(self.state, "save_routes", side_effect=delayed):
            work = asyncio.create_task(self.controller.prepare(await self.incoming("/focus 1")))
            await entered.wait()
            self.assertEqual(self.controller.routes.target, self.sessions[1].target)
            with self.assertRaises(RouteError):
                self.controller.prepare(await self.incoming("not yet selected"))
            await asyncio.wait_for(self.command("/status"), .5)
            release.set()
            await work
        self.assertEqual(self.controller.routes.target, self.sessions[0].target)
        self.queue.add.assert_not_awaited()

    async def test_frontend_persists_interaction_before_prompt_and_wire_answer(self):
        broker, record = await self.approval()
        row = (await self.state.interaction_rows())[0]
        self.assertEqual((row["state"], row["generation"]), ("pending", self.engine.generation))
        async def check_intent(*args):
            self.assertEqual((await self.state.interaction_rows())[0]["state"], "sending")
        self.agent.rpc.respond.side_effect = check_intent
        await self.command("/approve " + record.public_id)
        self.assertEqual((await self.state.interaction_rows())[0]["state"], "awaiting_native")
        await self.engine.event({"method": "serverRequest/resolved", "params": {
            "threadId": "thread-one", "requestId": "native-request"}})
        self.assertEqual((await self.state.interaction_rows())[0]["state"], "resolved")

    async def test_expiry_stales_durable_request_and_releases_detached_subscription(self):
        broker, record = await self.approval()
        await self.command("/detach")
        broker.clock = lambda: record.deadline
        await self.engine.expire_interactions()
        self.assertEqual((await self.state.interaction_rows())[0]["state"], "stale")
        self.assertFalse(self.controller.subscriptions.has(self.sessions[0].target, "interaction-" + record.public_id))
        await self.command("/approve " + record.public_id)
        self.agent.rpc.respond.assert_not_awaited()

    async def test_failed_request_persistence_cannot_publish_a_false_actionable_prompt(self):
        await self.select()
        await self.command("/attach 1")
        before = await self.state.delivery_counts()
        with patch.object(self.state, "record_interaction", new=AsyncMock(side_effect=OSError("disk full"))):
            with self.assertRaises(OSError):
                await self.engine.event({"id": 9, "method": APPROVAL, "params": {
                    "threadId": "thread-one", "turnId": "turn-a", "itemId": "item-a", "command": "fixture"}})
        self.assertEqual(await self.state.delivery_counts(), before)
        self.agent.rpc.respond.assert_not_awaited()

    async def test_full_queue_is_a_known_unsubmitted_failure_instead_of_unknown(self):
        await self.select()
        self.queue.add.side_effect = QueueFull("ten native entries")
        await self.command("cannot enter full queue")
        task = (await self.state.tasks())[0]
        self.assertEqual(task["state"], "failed")
        self.assertFalse(self.controller.subscriptions.has(self.sessions[1].target, "task-" + task["id"]))

    async def test_recovery_reads_exact_original_completion_without_submitting_again(self):
        await self.select()
        self.queue.add.side_effect = OutcomeUnknown("lost queue receipt")
        await self.command("one native execution")
        task = (await self.state.tasks())[0]
        self.agent.rpc.request.return_value = {"data": [{"id": "recovered-turn", "status": "completed", "items": [
            {"type": "userMessage", "clientId": task["client_id"]}, {"type": "agentMessage", "text": "recovered result"}]}], "nextCursor": None}
        await self.engine.reconcile()
        await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "completed")
        self.assertEqual(self.queue.add.await_count, 1)
        self.assertEqual(self.agent.rpc.request.await_args.args[0], "thread/turns/list")

    async def test_recovery_absence_is_unknown_and_duplicate_native_input_is_not_success(self):
        await self.select()
        self.queue.add.side_effect = OutcomeUnknown("lost receipt")
        await self.command("uncertain task")
        task = (await self.state.tasks())[0]
        self.agent.rpc.request.return_value = {"data": [], "nextCursor": None}
        await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")
        self.agent.rpc.request.return_value = {"data": [{"id": "merged", "status": "completed", "items": [
            {"type": "userMessage", "clientId": task["client_id"]}, {"type": "userMessage", "clientId": "desktop"}]}], "nextCursor": None}
        await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")
        self.assertEqual(self.queue.add.await_count, 1)

    async def test_recovery_queue_identity_restores_state_without_add(self):
        await self.select()
        self.queue.add.side_effect = OutcomeUnknown("lost receipt")
        await self.command("queued on native side")
        task = (await self.state.tasks())[0]
        self.queue.list.return_value = [{"id": "recovered-queue", "clientUserMessageId": task["client_id"]}]
        self.agent.rpc.request.return_value = {"data": [], "nextCursor": None}
        await self.engine.reconcile()
        recovered = await self.state.tasks(task_id=task["id"])
        self.assertEqual((recovered["state"], recovered["queue_id"]), ("queued", "recovered-queue"))
        self.assertEqual(self.queue.add.await_count, 1)

    async def test_query_leaves_unknown_task_for_independent_reconciliation_without_replay(self):
        task = await self.desktop_start(observe=True)
        await self.state.task_update(task["id"], "unknown")
        self.engine.observed_turns.clear()  # No recovered observation history is replayed.
        self.engine.turn_tasks.clear()
        require = self.catalog.require.side_effect
        self.catalog.require.side_effect = SessionUnbound("Original binding cannot be established at startup")
        await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")
        self.catalog.require.side_effect = require
        self.agent.rpc.request.return_value = {"data":[{"id":"desktop-turn", "status":"interrupted", "items":[
            {"type":"userMessage", "clientId":"desktop-native-client"}]}], "nextCursor":None}
        await self.command("/sessions")
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")
        self.agent.rpc.request.assert_not_awaited()
        await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "interrupted")
        self.queue.add.assert_not_awaited()
        self.agent.rpc.respond.assert_not_awaited()
        self.assertTrue(all(call.args[0]=="thread/turns/list" for call in self.agent.rpc.request.await_args_list))
        self.assertEqual(self.controller.routes.target, self.sessions[1].target)
        self.assertEqual(self.controller.routes.observer,self.sessions[1].target)

    async def test_explicit_refresh_preserves_unknown_when_binding_is_still_unverified(self):
        task = await self.desktop_start()
        await self.state.task_update(task["id"], "unknown")
        self.catalog.require.side_effect = SessionUnbound("still no original binding identity")
        self.agent.rpc.request.reset_mock()
        await self.command("/sessions")
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")
        self.agent.rpc.request.assert_not_awaited()
        self.queue.add.assert_not_awaited()

    async def changed_identity_external_task(self):
        task = await self.desktop_start(observe=True)
        await self.state.task_update(task["id"], "unknown")
        self.engine.observed_turns.clear()
        self.engine.turn_tasks.clear()
        original = self.sessions[1]
        target = Target("new-runtime-session", original.target.project_alias, original.target.cwd, "original")
        replacement = SimpleNamespace(target=target, binding=original.binding, title="same original thread")
        self.catalog.sessions = {target.session_id: replacement}
        async def require(current):
            if current.session_id not in self.catalog.sessions:
                raise SessionUnbound("Runtime generation changed the stable session ID")
            return self.catalog.sessions[current.session_id]
        self.catalog.require.side_effect = require
        self.agent.observe_loaded.reset_mock()
        self.agent.inspect.return_value = {"id": task["thread_id"], "cwd": str(target.cwd),
                                           "sessionId": "native-current", "status": {"type": "idle"}}
        return task

    async def test_changed_session_id_reconciles_exact_external_terminal_without_route_or_replay(self):
        task = await self.changed_identity_external_task()
        before_route = self.controller.routes.target
        self.agent.rpc.request.return_value = {"data": [{"id": "desktop-turn", "status": "interrupted", "items": [
            {"type": "userMessage", "clientId": "desktop-native-client"}]}], "nextCursor": None}
        await self.engine.reconcile()
        after = await self.state.tasks(task_id=task["id"])
        self.assertEqual(after["state"], "interrupted")
        self.assertEqual(after["target"], task["target"])
        self.assertEqual(self.controller.routes.target, before_route)
        self.queue.add.assert_not_awaited()
        self.agent.rpc.respond.assert_not_awaited()
        self.agent.observe_loaded.assert_not_awaited()

    async def test_changed_session_reconciliation_requires_unique_client_and_exact_native_history(self):
        task = await self.changed_identity_external_task()
        valid = {"id": "desktop-turn", "status": "interrupted", "items": [
            {"type": "userMessage", "clientId": "desktop-native-client"}]}
        cases = [[], [{**valid, "status": "inProgress"}],
                 [{**valid, "items": [{"type": "userMessage", "clientId": "different-client"}]}],
                 [{**valid, "items": valid["items"] * 2}], [valid, {**valid, "id": "duplicate-turn"}]]
        for turns in cases:
            with self.subTest(turns=turns):
                async def page(_method, params):
                    index = int(params.get("cursor", "0"))
                    return {"data": turns[index:index + 1],
                            "nextCursor": str(index + 1) if index + 1 < len(turns) else None}
                self.agent.rpc.request.side_effect = page
                await self.engine.reconcile()
                self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")
        self.catalog.require.side_effect = SessionUnbound("Original binding cannot be verified")
        self.agent.inspect.return_value["cwd"] = "/unrelated-project"
        self.agent.rpc.request.reset_mock()
        await self.engine.reconcile()
        self.agent.rpc.request.assert_not_awaited()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")
        self.queue.add.assert_not_awaited()

    async def test_changed_session_reconciles_bridge_client_without_resubmission(self):
        await self.select()
        self.queue.add.side_effect = OutcomeUnknown("lost receipt")
        await self.command("one original request")
        task = (await self.state.tasks())[0]
        original = self.sessions[1]
        target = Target("new-runtime-session", "two", original.target.cwd, "original")
        self.catalog.sessions = {target.session_id: SimpleNamespace(target=target, binding=original.binding)}
        async def require(current):
            if current != target:
                raise SessionUnbound("Old runtime identity")
            return self.catalog.sessions[target.session_id]
        self.catalog.require.side_effect = require
        self.agent.inspect.return_value = {"id": task["thread_id"], "cwd": str(target.cwd),
                                           "sessionId": "native-current", "status": {"type": "idle"}}
        self.agent.rpc.request.return_value = {"data": [{"id": "original-turn", "status": "completed", "items": [
            {"type": "userMessage", "clientId": task["client_id"]},
            {"type": "agentMessage", "text": "original result"}]}], "nextCursor": None}
        await self.engine.reconcile()
        result = await self.state.tasks(task_id=task["id"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["target"], task["target"])
        self.assertEqual(self.queue.add.await_count, 1)

    async def test_historical_reconciliation_never_guesses_native_thread_directory_or_client(self):
        task = await self.changed_identity_external_task()
        valid = dict(self.agent.inspect.return_value)
        self.catalog.sessions = {}
        variants = [{**valid, "id": "other-thread"}, {**valid, "cwd": str(self.root / "unrelated")},
                    {**valid, "sessionId": None}]
        self.agent.rpc.request.reset_mock()
        for metadata in variants:
            with self.subTest(metadata=metadata):
                self.agent.inspect.return_value = metadata
                await self.engine.reconcile_results()
        self.agent.rpc.request.assert_not_awaited()
        self.agent.inspect.return_value = valid
        self.agent.rpc.request.return_value = {"data": [{"id": "desktop-turn", "status": "completed",
            "items": [{"type": "userMessage", "clientId": "different-client"}]}], "nextCursor": None}
        await self.engine.reconcile()
        self.queue.add.assert_not_awaited()
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "unknown")

    async def test_unsupported_agent_refuses_before_durable_task_admission(self):
        await self.select()
        self.agent.capabilities = Capabilities(observe=True)
        await self.command("not supported")
        self.assertEqual(await self.state.tasks(), [])
        self.queue.add.assert_not_awaited()

    async def blocked_task(self):
        await self.select()
        original = self.sessions[1]
        other = Target("second-terminal-same-project", "two", original.target.cwd, "managed")
        session = SimpleNamespace(target=other, title="other", binding=SimpleNamespace(thread_id="thread-other", runtime_identity=(1, 2), native_session_id="native-other"))
        self.catalog.sessions[other.session_id] = session
        await self.command("first holds repository")
        # Select a verified second terminal in the same project, while first remains queued.
        self.controller.routes.snapshot((other,))
        await self.command("/focus 1")
        await self.command("wait for repository")
        tasks = await self.state.tasks(active_only=True)
        return next(t for t in tasks if t["state"] == "queued"), next(t for t in tasks if t["state"] == "received")

    async def test_cross_session_project_conflict_waits_then_dispatches_once_after_drain(self):
        first, waiting = await self.blocked_task()
        self.assertEqual(self.queue.add.await_count, 1)
        await self.engine.drain_admission()
        self.assertEqual(self.queue.add.await_count, 1)
        await self.engine.complete("thread-two", {"id": "first-turn", "status": "completed", "items": [
            {"type": "userMessage", "clientId": first["client_id"]}, {"type": "agentMessage", "text": "done"}]})
        await self.engine.drain_admission()
        await self.engine.drain_admission()
        self.assertEqual(self.queue.add.await_count, 2)
        self.assertEqual((await self.state.tasks(task_id=waiting["id"]))["state"], "queued")

    async def test_cancel_received_does_not_claim_native_deletion_or_wait_for_admission_lock(self):
        _, waiting = await self.blocked_task()
        before = await self.state._call(lambda: self.state.db.execute("SELECT count(*) FROM outbox").fetchone()[0])
        async with self.engine.admission_gate:
            await asyncio.wait_for(self.command("/stop " + waiting["id"]), .5)
        self.assertEqual((await self.state.tasks(task_id=waiting["id"]))["state"], "cancelled")
        await self.engine.drain_admission()
        self.assertEqual(self.queue.add.await_count, 1)
        self.queue.delete.assert_not_awaited()
        self.queue.request_interrupt.assert_not_awaited()
        rows = await self.state._call(lambda: list(self.state.db.execute(
            "SELECT id,priority,kind,text FROM outbox ORDER BY rowid LIMIT -1 OFFSET ?", (before,))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:3], (waiting["id"] + "-final-1", 0, "final"))
        self.assertIn("没有发送原生任务", rows[0][3])

    async def test_other_desktop_activity_blocks_admission_until_it_becomes_idle(self):
        await self.select()
        original = self.sessions[1]
        other = Target("desktop-same-project", "two", original.target.cwd, "original")
        self.catalog.sessions[other.session_id] = SimpleNamespace(target=other, binding=SimpleNamespace(thread_id="desktop-thread", runtime_identity=(1, 2), native_session_id="native-desktop"))
        self.agent.inspect.return_value = {"status": {"type": "active"}}
        await self.command("wait for desktop")
        self.assertEqual((await self.state.tasks())[0]["state"], "received")
        self.queue.add.assert_not_awaited()
        self.agent.inspect.return_value = {"status": {"type": "idle"}}
        await self.engine.drain_admission()
        self.queue.add.assert_awaited_once()

    async def test_different_project_aliases_sharing_repository_are_not_independent(self):
        await self.select()
        with patch("wx_clawbot.execution.repository_key", new=AsyncMock(return_value="git:fixture-common")), \
             patch("wx_clawbot.admission.repository_key", new=AsyncMock(return_value="git:fixture-common")):
            await self.command("project two takes lease")
            await self.command("/focus 1")
            await self.command("project one must wait")
        tasks = await self.state.tasks(active_only=True)
        self.assertEqual({t["state"] for t in tasks}, {"queued", "received"})
        self.assertEqual(self.queue.add.await_count, 1)

    async def test_same_native_session_accepts_ten_queued_then_rejects_eleventh(self):
        await self.select()
        for index in range(11):
            await self.command(f"task {index}")
        self.assertEqual(len(await self.state.tasks(active_only=True)), 10)
        self.assertEqual(self.queue.add.await_count, 10)

    async def test_delivery_backlog_refuses_new_execution_but_status_still_works(self):
        await self.select()
        with patch.object(self.state, "admission_budget", new=AsyncMock(return_value={"allowed": False})):
            await self.command("do not admit with full backlog")
            await self.command("/status")
        self.assertEqual(await self.state.tasks(), [])
        self.queue.add.assert_not_awaited()

    async def test_memory_cleanup_keeps_recent_handled_interactions_and_drops_detached_turns(self):
        broker, record = await self.approval()
        for index in range(80):
            event = {"id": index, "method": APPROVAL, "params": {"threadId": "thread-one",
                "turnId": "turn-a", "itemId": f"item-{index}", "command": "fixture"}}
            await self.engine.event(event)
            await self.engine.event({"method": "serverRequest/resolved", "params": {
                "threadId": "thread-one", "requestId": index}})
        # Preserve the first still-pending record, while bounding old handled history.
        self.assertEqual(record.state, "pending")
        self.engine.observed_turns.add(("thread-one", "detached-mid-turn"))
        await self.command("/detach")
        await self.engine.prune_memory()
        self.assertEqual(len(broker.records), 65)
        self.assertEqual(len(self.engine.interaction_targets), 65)
        self.assertEqual(self.engine.observed_turns, set())
        self.assertIn(record.public_id, broker.records)

    async def test_unsupported_native_request_is_reported_without_automatic_reply(self):
        await self.select()
        await self.engine.event({"id": 17, "method": "item/unsupported/requestApproval", "params": {"threadId": "thread-two"}})
        reply = await self.state.claim_reply()
        self.assertIn("尚未支持", reply["text"])
        self.agent.rpc.respond.assert_not_awaited()

    async def desktop_start(self, *, observe=False):
        await self.select()
        if observe:
            await self.command("/attach 2")
        await self.engine.event({"method": "turn/started", "params": {"threadId": "thread-two", "turn": {"id": "desktop-turn"}}})
        await self.engine.event({"method": "item/started", "params": {"threadId": "thread-two", "turnId": "desktop-turn",
            "item": {"type": "userMessage", "clientId": "desktop-native-client"}}})
        return (await self.state.tasks(active_only=True))[0]

    async def test_focused_desktop_turn_is_identifiable_and_stoppable_without_fabricated_inbox(self):
        task = await self.desktop_start()
        self.assertEqual(task["target"]["source"], "external")
        self.assertIsNone(task["source_message_id"])
        self.assertEqual(task["input"], "")
        await self.command("/stop " + task["id"])
        self.queue.request_interrupt.assert_awaited_once_with("desktop-turn")
        await self.engine.complete("thread-two", {"id": "desktop-turn", "status": "interrupted", "items": [
            {"type": "userMessage", "clientId": "desktop-native-client"}]})
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "interrupted")
        self.assertEqual((await self.state.delivery_counts())["pending"], 4)

    async def test_focus_only_does_not_forward_unobserved_desktop_results_or_new_approvals(self):
        task = await self.desktop_start()
        counts = await self.state.delivery_counts()
        await self.engine.event({"id": "desktop-approval", "method": APPROVAL, "params": {
            "threadId": "thread-two", "turnId": "desktop-turn", "itemId": "desktop-item", "command": "fixture"}})
        await self.engine.complete("thread-two", {"id": "desktop-turn", "status": "completed", "items": [
            {"type": "userMessage", "clientId": "desktop-native-client"}, {"type": "agentMessage", "text": "desktop result"}]})
        self.assertEqual(await self.state.delivery_counts(), counts)
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "completed")
        self.assertEqual(await self.state.interaction_rows(), [])
        self.agent.rpc.respond.assert_not_awaited()

    async def test_observed_external_turn_forwards_result_once_and_detach_stops_future_results(self):
        task = await self.desktop_start(observe=True)
        before = await self.state.delivery_counts()
        turn = {"id": "desktop-turn", "status": "completed", "items": [
            {"type": "userMessage", "clientId": "desktop-native-client"}, {"type": "agentMessage", "text": "desktop result"}]}
        await self.engine.complete("thread-two", turn)
        await self.engine.complete("thread-two", turn)
        self.assertEqual((await self.state.delivery_counts())["pending"], before["pending"] + 1)
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "completed")

    async def test_stopped_observed_external_turn_has_one_terminal_reply_with_no_stale_progress(self):
        task = await self.desktop_start(observe=True)
        await self.command("/stop " + task["id"])
        before = await self.state._call(lambda: self.state.db.execute("SELECT count(*) FROM outbox").fetchone()[0])
        turn = {"id": "desktop-turn", "status": "interrupted", "items": [
            {"type": "userMessage", "clientId": "desktop-native-client"},
            {"type": "agentMessage", "phase": "commentary", "text": "still running"}]}
        await self.engine.complete("thread-two", turn)
        await self.engine.complete("thread-two", turn)
        rows = await self.state._call(lambda: list(self.state.db.execute(
            "SELECT id,text FROM outbox ORDER BY rowid LIMIT -1 OFFSET ?", (before,))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], task["id"] + "-final-1")
        self.assertIn("任务中断", rows[0][1])
        self.assertNotIn("still running", rows[0][1])
        self.assertIn("没有最终文本结果", rows[0][1])
        self.assertEqual(self.engine.observed_turns, set())

    async def test_modal_catalog_refresh_cannot_erase_live_observation_or_interaction(self):
        task = await self.desktop_start(observe=True)
        self.catalog.sessions = {}  # Fresh input has no independently verified original binding.
        self.catalog.require.side_effect = SessionUnbound("original process identity is unavailable")
        await self.command("PHONE_ALPHA")
        self.queue.add.assert_not_awaited()
        await self.engine.event({"id":"desktop-question", "method":QUESTION, "params": {
            "threadId":"thread-two", "turnId":"desktop-turn", "itemId":"question-item",
            "questions":[{"id":"choice", "options":[{"label":"PHONE_BETA"}]}]}})
        record = next(iter(self.engine.brokers["thread-two"].records.values()))
        await self.command("/answer " + record.public_id + " PHONE_BETA")
        self.agent.rpc.respond.assert_awaited_once_with("desktop-question", {"answers":{"choice":{"answers":["PHONE_BETA"]}}})
        await self.engine.event({"method":"serverRequest/resolved", "params": {
            "threadId":"thread-two", "requestId":"desktop-question"}})
        turn = {"id":"desktop-turn", "status":"completed", "items":[
            {"type":"userMessage", "clientId":"desktop-native-client"},
            {"type":"agentMessage", "text":"PHONE_BETA"}]}
        counts = await self.state.delivery_counts()
        await self.engine.complete("thread-two", turn)
        self.assertEqual((await self.state.delivery_counts())["pending"], counts["pending"]+1)
        await self.engine.complete("thread-two", turn)
        self.assertEqual((await self.state.delivery_counts())["pending"], counts["pending"]+1)
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "completed")

    async def test_focus_adopts_already_running_native_turn_without_submitting_or_replaying_history(self):
        await self.command("/sessions")
        self.agent.inspect.return_value = {"status": {"type": "active"}}
        self.agent.rpc.request.return_value = {"data": [{"id": "already-running", "status": "inProgress",
            "items": [{"type": "userMessage", "clientId": "desktop-current"}]}], "nextCursor": None}
        await self.command("/focus 2")
        task = (await self.state.tasks())[0]
        self.assertEqual((task["turn_id"], task["target"]["source"]), ("already-running", "external"))
        self.queue.add.assert_not_awaited()

    async def test_oversized_native_approval_cannot_be_approved_from_truncated_text(self):
        await self.select()
        await self.command("/attach 1")
        await self.engine.event({"id": "large-request", "method": APPROVAL, "params": {
            "threadId": "thread-one", "turnId": "large-turn", "itemId": "large-item", "command": "x" * 8000}})
        record = next(iter(self.engine.brokers["thread-one"].records.values()))
        self.assertEqual(record.state, "stale")
        await self.command("/approve " + record.public_id)
        self.agent.rpc.respond.assert_not_awaited()
        reply = await self.state.claim_reply()
        self.assertIn("原终端", reply["text"])

    async def test_display_line_breaks_cannot_change_task_input_or_code_result_bytes(self):
        await self.select()
        raw = '保持这些行：\nvalue = "A B"\nprint(value)'
        await self.command(raw)
        self.assertEqual(self.queue.add.await_args.args[0], raw)
        task = (await self.state.tasks())[0]
        self.assertEqual(task["input"], raw)
        code = 'value = "A B"\nprint(value)\n'
        await self.engine.complete("thread-two", {"id": "code-turn", "status": "completed", "items": [
            {"type": "userMessage", "clientId": task["client_id"]},
            {"type": "agentMessage", "text": "说明。\n\n```python\n" + code + "```"}]})
        reply = await self.state.claim_reply()
        self.assertIn(code, reply["text"])
        self.assertIn("\n\n```python\n", reply["text"])
        self.assertNotIn("\u2028", reply["text"])

    async def test_newly_visible_desktop_session_is_discovered_before_repository_admission(self):
        await self.select()
        other = Target("new-desktop-terminal", "two", self.sessions[1].target.cwd, "original")
        session = SimpleNamespace(target=other, binding=SimpleNamespace(thread_id="new-desktop-thread", runtime_identity=(1, 2), native_session_id="native-new-desktop"))
        async def refresh(*_):
            self.catalog.sessions[other.session_id] = session
            return tuple(self.catalog.sessions.values())
        self.catalog.discover.side_effect = refresh
        self.agent.inspect.side_effect = lambda thread: {"status": {"type": "active" if thread == "new-desktop-thread" else "idle"}}
        await self.command("must wait for newly opened desktop")
        self.assertEqual((await self.state.tasks())[0]["state"], "received")
        self.queue.add.assert_not_awaited()

    async def test_native_interrupt_completion_before_rpc_return_keeps_terminal_truth(self):
        task = await self.desktop_start()
        async def complete_before_return(turn_id):
            self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "stopping")
            await self.engine.complete("thread-two", {"id": turn_id, "status": "interrupted", "items": [
                {"type": "userMessage", "clientId": "desktop-native-client"}]})
            return {}
        self.queue.request_interrupt.side_effect = complete_before_return
        await self.command("/stop " + task["id"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "interrupted")
        command_reply = await self.state.claim_reply()
        self.assertIn("interrupted", command_reply["text"])
        self.assertNotIn("操作未确认", command_reply["text"])

    async def test_queue_cancel_race_uses_fresh_running_turn_instead_of_stale_queued_snapshot(self):
        await self.select()
        await self.command("queued then running")
        task = (await self.state.tasks())[0]
        async def already_running(queue_id):
            await self.state.task_update(task["id"], "running", turn_id="newly-running-turn")
            return False
        self.queue.delete.side_effect = already_running
        await self.command("/stop " + task["id"])
        self.queue.request_interrupt.assert_awaited_once_with("newly-running-turn")
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "stopping")

    async def test_lost_interrupt_ack_cannot_overwrite_already_observed_native_terminal(self):
        task = await self.desktop_start()
        async def complete_then_lose_ack(turn_id):
            await self.engine.complete("thread-two", {"id": turn_id, "status": "interrupted", "items": [
                {"type": "userMessage", "clientId": "desktop-native-client"}]})
            raise OutcomeUnknown("interrupt receipt lost after native completion")
        self.queue.request_interrupt.side_effect = complete_then_lose_ack
        await self.command("/stop " + task["id"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "interrupted")
        reply = await self.state.claim_reply()
        self.assertIn("interrupted", reply["text"])
        self.assertNotIn("操作未确认", reply["text"])

    async def test_native_model_list_does_not_need_focus_or_create_tasks(self):
        self.agent.server_version='0.167.0'
        self.agent.rpc.request.return_value={'data':[{'model':'fixture-model'}]}
        before=await self.state.load_routes()
        await self.command('/model list')
        reply=await self.state.claim_reply()
        self.assertIn('fixture-model',reply['text'])
        self.assertEqual(await self.state.tasks(),[])
        self.assertEqual(await self.state.load_routes(),before)
        self.catalog.require.assert_not_awaited();self.agent.observe_loaded.assert_not_awaited()
        self.agent.rpc.request.assert_awaited_once_with('model/list',{'limit':100,'includeHidden':False})

    async def test_native_queries_freeze_target_and_writes_do_not_enter_task_queue(self):
        await self.select()
        self.agent.server_version='0.167.0'
        self.agent.read_settings=AsyncMock(return_value={'model':'fixture-model','reasoningEffort':'high'})
        self.agent.rpc.request.return_value={'data':[{'model':'fixture-model'}]}
        before=await self.state.load_routes()
        await self.command('/model')
        await self.command('/model set other-model high')
        texts=await self.state._call(lambda:[r[0] for r in self.state.db.execute('SELECT text FROM outbox')])
        self.assertTrue(any('fixture-model' in t for t in texts))
        self.assertTrue(any('当前设置或模型目录缺失' in t for t in texts))
        self.assertEqual(await self.state.tasks(),[])
        self.assertEqual(await self.state.load_routes(),before)
        self.queue.add.assert_not_awaited()

    async def test_received_task_reservation_blocks_setting_before_task_intent(self):
        await self.select()
        self.agent.server_version='0.167.0'
        values={'model':'fixture-model','modelProvider':'fixture-provider','reasoningEffort':'high','serviceTier':'default'}
        self.agent.read_settings=AsyncMock(return_value=values)
        self.agent.inspect.return_value={'status':{'type':'idle'},'canAcceptDirectInput':True}
        self.agent.rpc.request.return_value={'data':[{'model':'fixture-model',
            'supportedReasoningEfforts':[{'reasoningEffort':'medium'},{'reasoningEffort':'high'}]}]}
        self.engine.native_controls.confirm_seconds=.02
        pending=self.controller.prepare(await self.incoming('pending task'))
        self.assertTrue(self.controller.task_reservations)
        await self.command('/model set fixture-model medium')
        self.assertTrue(all(call.args[0]!='thread/settings/update' for call in self.agent.rpc.request.call_args_list))
        self.assertEqual(await self.state.tasks(),[])
        await pending
        self.assertFalse(self.controller.task_reservations)

    async def test_setting_and_normal_dispatch_share_admission_gate(self):
        await self.select()
        self.agent.server_version='0.167.0'
        values={'model':'fixture-model','modelProvider':'fixture-provider','reasoningEffort':'high','serviceTier':'default'}
        self.agent.read_settings=AsyncMock(side_effect=lambda *a:values.copy())
        self.agent.inspect.return_value={'status':{'type':'idle'},'canAcceptDirectInput':True}
        entered,release=asyncio.Event(),asyncio.Event()
        async def rpc(method,params):
            if method=='model/list':return {'data':[{'model':'fixture-model',
                'supportedReasoningEfforts':[{'reasoningEffort':'medium'},{'reasoningEffort':'high'}]}]}
            self.assertEqual(method,'thread/settings/update');entered.set();await release.wait()
            values['reasoningEffort']='medium'
            self.engine.native_controls.event('thread/settings/updated',{'threadId':'thread-two',
                'threadSettings':{'model':'fixture-model','modelProvider':'fixture-provider','effort':'medium',
                                  'serviceTier':'default','cwd':str(self.sessions[1].target.cwd)}})
            return {}
        self.agent.rpc.request.side_effect=rpc
        key=patch('wx_clawbot.native_controls.repository_key',new=AsyncMock(return_value='repository'))
        with key:
            writer=asyncio.create_task(self.command('/model set fixture-model medium'))
            await asyncio.wait_for(entered.wait(),1)
            submit=asyncio.create_task(self.command('after setting'))
            await asyncio.sleep(.01);self.queue.add.assert_not_awaited()
            release.set();await writer;await submit
        self.queue.add.assert_awaited_once()
        texts=await self.state._call(lambda:[r[0] for r in self.state.db.execute('SELECT text FROM outbox')])
        self.assertTrue(any('设置已确认' in text for text in texts))
        self.assertFalse(self.controller.project_reservations)

    async def test_control_active_interactions_cannot_hide_behind_recent_resolved_history(self):
        from wx_clawbot.channels.http import ProtocolError
        target={'thread_id':'thread-two','project_alias':'two','cwd':str(self.sessions[1].target.cwd)}
        for i in range(257):
            record=SimpleNamespace(public_id='fixture-'+str(i),thread_id='thread-two',turn_id='turn',
                                   method=APPROVAL,native_id=i,params={},state='pending' if i==0 else 'resolved')
            await self.state.record_interaction(record,generation='g',target=target,expires_at=1000)
        rows=await self.state.interaction_rows(active_only=True)
        self.assertEqual([v['public_id'] for v in rows],['fixture-0'])
        self.assertEqual(len(await self.state.interaction_rows()),256)
        await self.state._call(lambda:self.state.db.execute("UPDATE interactions SET state='pending'"))
        with self.assertRaises(ProtocolError):await self.state.interaction_rows(active_only=True)

    async def test_native_query_received_before_unfocus_never_uses_new_selection(self):
        await self.select()
        self.agent.server_version='0.167.0'
        self.agent.read_settings=AsyncMock()
        work=self.controller.prepare(await self.incoming('/model'))
        await self.command('/unfocus')
        await work
        self.agent.read_settings.assert_not_awaited()
        self.assertFalse(self.controller.project_reservations)
