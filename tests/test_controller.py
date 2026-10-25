import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.agents.base import Capabilities
from wx_clawbot.agents.rpc import OutcomeUnknown
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.commands import parse_command
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
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
        self.agent = SimpleNamespace(capabilities=Capabilities(observe=True),
                                     observe_loaded=AsyncMock(), unsubscribe=AsyncMock(),
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
        self.queue = SimpleNamespace(add=AsyncMock(return_value={"id": "fixture-queue"}),
                                     delete=AsyncMock(return_value=False), request_interrupt=AsyncMock(return_value={}))
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
        self.assertEqual((await self.state.delivery_counts())["pending"], before["pending"] + 2)

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
