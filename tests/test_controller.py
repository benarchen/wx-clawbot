import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.agents.base import Capabilities
from wx_clawbot.agents.rpc import OutcomeUnknown
from wx_clawbot.agents.queue import QueueFull
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.channels.private import write_json
from wx_clawbot.commands import parse_command
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller, RouteCommitFailed
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.visible import LaunchPending, LaunchRegistry
from wx_clawbot.interactions import APPROVAL, QUESTION
from wx_clawbot.routing import RouteError, Target
from wx_clawbot.runtime_state import RuntimeState
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
                                  binding=SimpleNamespace(thread_id="thread-" + alias)))
        self.agent = SimpleNamespace(capabilities=Capabilities(observe=True, queue=True, interrupt=True, shared_interactions=True),
                                     observe_loaded=AsyncMock(), unsubscribe=AsyncMock(),
                                     inspect=AsyncMock(return_value={"status": {"type": "idle"}}),
                                     rpc=SimpleNamespace(request=AsyncMock(), respond=AsyncMock()))
        self.catalog = SimpleNamespace(agent=self.agent, sessions={s.target.session_id: s for s in self.sessions},
                                       managed_threads=set(), unverified=[], directory=None,
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
        await self.command("/stop " + task["id"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "cancelled")
        self.queue.request_interrupt.assert_not_awaited()

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
        self.assertIn("受管会话", reply["text"])

    async def test_projects_reports_disappeared_directory_without_routing_or_native_actions(self):
        self.sessions[0].target.cwd.rename(self.root / "moved-one")
        await self.command("/projects")
        reply = await self.state.claim_reply()
        self.assertIn("one：不可访问", reply["text"])
        self.assertIn("two：可用", reply["text"])
        self.assertIsNone(self.controller.routes.target)
        self.catalog.require.assert_not_awaited()

    async def test_cd_reuses_explicitly_focused_managed_session_among_multiple_candidates(self):
        original = self.sessions[0]
        extra_target = Target("session-one-extra", "one", original.target.cwd, "managed")
        extra = SimpleNamespace(target=extra_target, title="extra", binding=SimpleNamespace(thread_id="thread-extra"))
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
        self.assertIn("failed", reply["text"])
        self.assertEqual((await self.state.tasks(task_id=task["id"]))["state"], "failed")

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
        session = SimpleNamespace(target=other, title="other", binding=SimpleNamespace(thread_id="thread-other"))
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
        async with self.engine.admission_gate:
            await asyncio.wait_for(self.command("/stop " + waiting["id"]), .5)
        self.assertEqual((await self.state.tasks(task_id=waiting["id"]))["state"], "cancelled")
        await self.engine.drain_admission()
        self.assertEqual(self.queue.add.await_count, 1)
        self.queue.delete.assert_not_awaited()
        self.queue.request_interrupt.assert_not_awaited()

    async def test_other_desktop_activity_blocks_admission_until_it_becomes_idle(self):
        await self.select()
        original = self.sessions[1]
        other = Target("desktop-same-project", "two", original.target.cwd, "original")
        self.catalog.sessions[other.session_id] = SimpleNamespace(target=other, binding=SimpleNamespace(thread_id="desktop-thread"))
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

    async def test_focus_adopts_already_running_native_turn_without_submitting_or_replaying_history(self):
        await self.command("/sessions")
        self.agent.inspect.return_value = {"status": {"type": "active"}}
        self.agent.rpc.request.return_value = {"data": [{"id": "already-running", "status": "inProgress",
            "items": [{"type": "userMessage", "clientId": "desktop-current"}]}], "nextCursor": None}
        await self.command("/focus 2")
        task = (await self.state.tasks())[0]
        self.assertEqual((task["turn_id"], task["target"]["source"]), ("already-running", "external"))
        self.queue.add.assert_not_awaited()
