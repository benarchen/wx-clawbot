"""Session notices exercise real route restoration, persistence and rendering."""

import asyncio
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
from types import SimpleNamespace

import test_independent_target as fixtures
import test_native_target_lifecycle as lifecycle
from test_runtime_state import RuntimeFixture
from test_wechat_state import message
from wx_clawbot.agents.rpc import ConnectionLost, RpcError
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.hosts.lifecycle import HostLifecycle, HostUnavailable
from wx_clawbot.runtime_lifecycle import BridgeRuntime


class SelectionNoticeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.IndependentTargetTests.asyncSetUp
    command = fixtures.IndependentTargetTests.command
    desktop_switch = fixtures.IndependentTargetTests.desktop_switch
    fresh_controller = lifecycle.NativeTargetLifecycleTests.fresh_controller

    async def notices(self):
        return await self.state._call(lambda: [row[0] for row in self.state.db.execute(
            "SELECT text FROM outbox WHERE id LIKE 'session-%' OR id LIKE 'route-recovery-%' ORDER BY rowid")])

    async def test_stale_history_does_not_notify_or_drop_current_selection(self):
        snapshot = await self.state.load_routes()
        snapshot['last_managed'].append(dict(snapshot['target'], session_id='old-history', thread_id='gone'))
        await self.state.save_routes(snapshot)
        controller = self.fresh_controller()
        await controller.restore()
        self.assertEqual(controller.routes.target, self.a)
        self.assertEqual(await self.notices(), [])
        self.assertTrue(controller.subscriptions.has(self.a, 'route'))

    async def test_history_only_and_invalid_old_directory_are_silent(self):
        snapshot = await self.state.load_routes()
        snapshot.update(target=None, observer=None, mode='unbound', cwd='/missing-fixture-directory')
        self.agent.loaded_threads.return_value = frozenset()
        await self.state.save_routes(snapshot)
        await self.fresh_controller().restore()
        self.assertEqual(await self.notices(), [])

    async def test_runtime_change_names_input_and_does_not_invent_restart_cause(self):
        self.agent.runtime_identity = (3, 4)
        await self.fresh_controller().restore()
        texts = await self.notices()
        self.assertEqual(len(texts), 1)
        self.assertIn('原生运行时已变化', texts[0])
        self.assertIn('输入目标', texts[0])
        self.assertIn('/focus <序号>', texts[0])
        self.assertNotIn('/attach', texts[0])
        self.assertNotIn('重启了', texts[0])
        self.assertIn(self.a.session_id, texts[0])
        self.queues['thread-a'].add.assert_not_awaited()

    async def test_native_session_change_has_distinct_reason(self):
        self.threads['thread-a']['sessionId'] = 'new-native-root'
        await self.fresh_controller().restore()
        self.assertIn('原生会话身份已变化', (await self.notices())[0])

    async def test_exact_unloaded_target_is_not_reported_as_runtime_change(self):
        self.threads['thread-a']['status'] = {'type': 'notLoaded'}
        self.agent.loaded_threads.return_value = frozenset()
        await self.fresh_controller().restore()
        text = (await self.notices())[0]
        self.assertIn('已不在原生运行时中加载', text)
        self.assertNotIn('运行时已变化', text)
        self.agent.observe_loaded.assert_awaited_once()  # Only initial focus.

    async def test_missing_candidate_but_exact_loaded_thread_is_evidence_gap(self):
        self.agent.list_project_threads.return_value = {'data': []}
        await self.fresh_controller().restore()
        text = (await self.notices())[0]
        self.assertIn('核验证据不足', text)
        self.assertNotIn('已不在原生运行时中加载', text)

    async def test_exact_read_error_never_leaks_or_claims_unloaded(self):
        self.agent.list_project_threads.return_value = {'data': []}
        self.agent.inspect.side_effect = RpcError(-32000, 'SECRET /private/path')
        await self.fresh_controller().restore()
        text = (await self.notices())[0]
        self.assertIn('核验证据不足', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('/private/path', text)
        self.assertNotIn('已不在原生运行时中加载', text)

    async def test_cwd_change_is_classified_from_exact_read(self):
        self.agent.list_project_threads.return_value = {'data': []}
        self.threads['thread-a']['cwd'] = str(self.root.parent)
        await self.fresh_controller().restore()
        self.assertIn('项目目录已变化', (await self.notices())[0])

    async def test_observer_only_failure_preserves_input_and_uses_attach(self):
        self.desktop_switch()
        await self.command('/sessions')
        number = next(i for i, t in enumerate(self.controller.routes.list.targets, 1)
                      if t != self.a)
        await self.command('/attach ' + str(number))
        self.threads['thread-b']['status'] = {'type': 'notLoaded'}
        self.agent.loaded_threads.return_value = frozenset({'thread-a'})
        controller = self.fresh_controller()
        await controller.restore()
        text = (await self.notices())[0]
        self.assertIn('观察订阅', text)
        self.assertIn('/attach <序号>', text)
        self.assertIn('输入目标保留', text)
        self.assertNotIn('/focus', text)
        self.assertEqual(controller.routes.target, self.a)
        self.assertIsNone(controller.routes.observer)

    async def test_two_roles_fail_in_one_notice_with_both_actions(self):
        await self.command('/attach 1')
        self.agent.runtime_identity = (3, 4)
        await self.fresh_controller().restore()
        texts = await self.notices()
        self.assertEqual(len(texts), 1)
        self.assertIn('/focus <序号>', texts[0])
        self.assertIn('/attach <序号>', texts[0])

    async def test_subscription_failure_is_unconfirmed_not_unloaded(self):
        self.agent.observe_loaded.side_effect = RpcError(-32000, 'SECRET')
        controller = self.fresh_controller()
        await controller.restore()
        self.assertIsNone(controller.routes.target)
        text = (await self.notices())[0]
        self.assertIn('原生订阅尚未确认', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('已不在原生运行时中加载', text)

    async def test_subscription_timeout_remains_unconfirmed(self):
        self.agent.observe_loaded.side_effect = TimeoutError('SECRET')
        await self.fresh_controller().restore()
        self.assertIn('原生订阅尚未确认', (await self.notices())[0])

    async def test_repeated_restore_does_not_repeat_selection_notice(self):
        self.agent.runtime_identity = (3, 4)
        await self.fresh_controller().restore()
        await self.fresh_controller().restore()
        self.assertEqual(len(await self.notices()), 1)

    async def test_iterm_absence_with_valid_native_is_silent(self):
        self.directory.discover.side_effect = HostUnavailable('not_running')
        controller = self.fresh_controller()
        await controller.restore()
        self.assertEqual(controller.routes.target, self.a)
        self.assertEqual(await self.notices(), [])

    async def test_host_recovery_reports_actual_lost_target(self):
        self.threads['thread-a']['status'] = {'type': 'notLoaded'}
        self.agent.loaded_threads.return_value = frozenset()
        await self.controller.recover_host()
        self.assertIsNone(self.controller.routes.target)
        self.assertIn('已不在原生运行时中加载', (await self.notices())[0])

    async def test_failed_notice_transaction_retains_original_route_and_retries_once(self):
        original = await self.state.load_routes()
        await self.state._call(lambda: self.state.db.execute("""CREATE TEMP TRIGGER fail_notice
            BEFORE INSERT ON outbox WHEN NEW.id LIKE 'session-%'
            BEGIN SELECT RAISE(ABORT,'injected'); END"""))
        self.agent.runtime_identity = (3, 4)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.fresh_controller().restore()
        self.assertEqual(await self.state.load_routes(), original)
        self.assertEqual(await self.notices(), [])
        await self.state._call(lambda: self.state.db.execute('DROP TRIGGER fail_notice'))
        await self.fresh_controller().restore()
        self.assertEqual(len(await self.notices()), 1)

    async def exercise_runtime_reconnect(self, *, changed=False):
        snapshot = await self.state.load_routes()
        snapshot['target']['origin'] = 'original'
        snapshot['last_managed'] = []
        await self.state.save_routes(snapshot)
        backend = SimpleNamespace(identity=AsyncMock(return_value=None), launch=AsyncMock())
        host = HostLifecycle(backend)
        self.addAsyncCleanup(host.close)
        runtime = BridgeRuntime((self.project,), self.state, self.starter, host, None, None, self.root)
        notifier = self.state.session_notifications
        now = [1000., 100.]
        notifier.wall, notifier.clock = lambda: now[0], lambda: now[1]
        await runtime.initialize()
        lost = asyncio.Event()
        calls = 0
        async def event(**_):
            nonlocal calls
            calls += 1
            if calls == 1:
                await lost.wait()
                raise ConnectionLost('SECRET transport failure')
            await asyncio.Event().wait()
        self.agent.rpc = SimpleNamespace(next_event=event)
        self.agent.close = AsyncMock()
        with patch.object(runtime, 'connect_native', new=AsyncMock(return_value=(self.agent, Path('/fixture/codex')))):
            job = asyncio.create_task(runtime.run())
            try:
                async with asyncio.timeout(2):
                    while not runtime.notices_ready:
                        await asyncio.sleep(.001)
                self.assertEqual(await self.notices(), [])
                lost.set()
                async with asyncio.timeout(2):
                    while not (await self.state.load_routes())['session_notifications']['outage']:
                        await asyncio.sleep(.001)
                now[0] += 31
                now[1] += 31
                await notifier.tick()
                await self.state.accept_batch({'ret': 0, 'msgs': [message(999, text='/status')]}, phase='runtime')
                reply = await self.state.claim_reply()
                self.assertIn('连接暂时不可用', reply['text'])
                await self.state.finish_reply(reply['id'], 'accepted', 'synthetic-server-id')
                if changed:
                    self.agent.runtime_identity = (3, 4)
                async with asyncio.timeout(3):
                    while not runtime.notices_ready:
                        await asyncio.sleep(.001)
                texts = await self.notices()
                self.assertEqual(len(texts), 2)
                if changed:
                    self.assertIn('原生运行时已变化', texts[1])
                    self.assertIsNone(runtime.controller.routes.target)
                    self.assertNotIn('已重新核验并恢复', texts[1])
                else:
                    self.assertIn('已重新核验并恢复', texts[1])
                    self.assertEqual(runtime.controller.routes.target.session_id, self.a.session_id)
                self.assertNotIn('SECRET', '\n'.join(texts))
                self.assertEqual(await self.state.tasks(), [])
                backend.launch.assert_not_awaited()
            finally:
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job

    async def test_runtime_disconnect_reconnect_preserves_exact_selection_and_notifies_recovery(self):
        await self.exercise_runtime_reconnect()

    async def test_runtime_replacement_during_reconnect_notifies_selection_loss_without_false_recovery(self):
        await self.exercise_runtime_reconnect(changed=True)


class OutageNoticeTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.now = [1000., 100.]
        self.configure_clock()
        self.record = {'session_id': 's-exact-fixture', 'project_alias': 'fixture'}
        self.snapshot = {'version': 2, 'revision': 3, 'mode': 'focused', 'project': 'fixture',
                         'cwd': str(self.root), 'target': self.record, 'observer': None, 'last_managed': []}
        await self.state.save_routes(self.snapshot)

    def configure_clock(self):
        self.notifier = self.state.session_notifications
        self.notifier.wall = lambda: self.now[0]
        self.notifier.clock = lambda: self.now[1]

    def advance(self, seconds):
        self.now[0] += seconds
        self.now[1] += seconds

    async def notices(self):
        return await self.state._call(lambda: [row[0] for row in self.state.db.execute(
            "SELECT text FROM outbox WHERE id LIKE 'session-%' ORDER BY rowid")])

    async def deliver(self, outcome='accepted'):
        await self.state.accept_batch({'ret': 0, 'msgs': [message(999, text='/status')]}, phase='runtime')
        while (reply := await self.state.claim_reply()) is not None:
            await self.state.finish_reply(reply['id'], outcome, 'synthetic-server-id' if outcome == 'accepted' else None)

    async def test_29999_seconds_silent_30_seconds_notifies_once(self):
        await self.notifier.begin()
        await self.notifier.tick()
        self.advance(29.999)
        await self.notifier.tick()
        self.assertEqual(await self.notices(), [])
        self.advance(.001)
        await self.notifier.tick()
        await self.notifier.tick()
        self.assertEqual(len(await self.notices()), 1)
        self.assertIn('正在自动重连', (await self.notices())[0])

    async def test_short_outage_and_recovery_are_both_silent(self):
        await self.notifier.begin()
        self.advance(29)
        await self.notifier.recovered()
        await self.notifier.tick()
        self.assertEqual(await self.notices(), [])

    async def test_notified_outage_has_one_role_accurate_recovery_notice(self):
        await self.notifier.begin()
        self.advance(31)
        await self.notifier.tick()
        await self.deliver()
        await self.notifier.recovered()
        await self.notifier.recovered()
        texts = await self.notices()
        self.assertEqual(len(texts), 2)
        self.assertIn('已重新核验并恢复', texts[1])
        self.assertNotIn('观察订阅', texts[1])

    async def test_old_inactive_observer_issue_does_not_hide_current_input_recovery(self):
        await self.notifier.restore(self.snapshot, [('observer', self.record, 'not_loaded')])
        await self.notifier.begin()
        self.advance(31)
        await self.notifier.tick()
        await self.deliver()
        await self.notifier.recovered()
        self.assertIn('已重新核验并恢复', (await self.notices())[-1])

    async def test_restart_keeps_deadline_and_does_not_repeat_sent_stage(self):
        await self.notifier.begin()
        self.advance(20)
        await self.restart()
        self.configure_clock()
        await self.notifier.begin()
        self.advance(10)
        await self.notifier.tick()
        self.assertEqual(len(await self.notices()), 1)
        await self.restart()
        self.configure_clock()
        await self.notifier.begin()
        await self.notifier.tick()
        self.assertEqual(len(await self.notices()), 1)

    async def test_wall_clock_jump_does_not_advance_live_deadline(self):
        await self.notifier.begin()
        await self.notifier.tick()
        self.now[0] += 86400
        self.now[1] += 29
        await self.notifier.tick()
        self.assertEqual(await self.notices(), [])
        self.now[1] += 1
        await self.notifier.tick()
        self.assertEqual(len(await self.notices()), 1)

    async def test_restart_after_clock_rollback_does_not_notify_early(self):
        await self.notifier.begin()
        self.now[0] -= 3600
        await self.restart()
        self.configure_clock()
        await self.notifier.tick()
        self.assertEqual(await self.notices(), [])
        self.now[1] += 30
        await self.notifier.tick()
        self.assertEqual(len(await self.notices()), 1)

    async def test_verification_pending_has_distinct_once_only_message(self):
        await self.notifier.begin()
        self.advance(31)
        await self.notifier.tick()
        await self.notifier.begin('verification_pending')
        await self.notifier.tick()
        await self.notifier.begin()
        await self.notifier.tick()
        texts = await self.notices()
        self.assertEqual(len(texts), 2)
        self.assertIn('恢复核验尚未完成', texts[1])
        self.assertNotIn('正在自动重连', texts[1])

    async def test_no_selection_and_no_tasks_stays_silent(self):
        self.snapshot.update(target=None, mode='unbound')
        await self.state.save_routes(self.snapshot)
        await self.notifier.begin()
        self.advance(300)
        await self.notifier.tick()
        self.assertEqual(await self.notices(), [])

    async def test_task_only_outage_does_not_claim_task_stopped_or_selection_restored(self):
        self.snapshot.update(target=None, mode='unbound')
        await self.state.save_routes(self.snapshot)
        await self.admit()
        await self.notifier.begin()
        self.advance(31)
        await self.notifier.tick()
        await self.deliver()
        await self.notifier.recovered()
        texts = await self.notices()
        self.assertEqual(len(texts), 2)
        self.assertIn('执行状态待核验', texts[0])
        self.assertIn('不代表任务已完成', texts[1])
        self.assertNotIn('输入目标', texts[1])

    async def test_released_unknown_alone_does_not_trigger_outage_notice(self):
        self.snapshot.update(target=None, mode='unbound')
        await self.state.save_routes(self.snapshot)
        task = await self.admit()
        await self.state.task_update(task['id'], 'unknown')
        # Isolated fixture models an audited release; production release gates are unchanged.
        await self.state._call(lambda: self.state.db.execute("UPDATE task_occupancy SET state='released'"))
        await self.notifier.begin()
        self.advance(300)
        await self.notifier.tick()
        self.assertEqual(await self.notices(), [])

    async def test_failed_selection_cannot_emit_recovery_success(self):
        await self.notifier.begin()
        self.advance(31)
        await self.notifier.tick()
        lost = dict(self.snapshot, target=None, mode='unbound')
        await self.notifier.restore(lost, [('target', self.record, 'runtime_changed')])
        await self.notifier.recovered()
        texts = await self.notices()
        self.assertEqual(len(texts), 2)
        self.assertFalse(any('已重新核验并恢复' in t for t in texts))

    async def test_selection_write_preserves_outage_and_new_selection_ends_old_issue(self):
        await self.notifier.begin()
        lost = dict(self.snapshot, target=None, mode='unbound')
        failure = [('target', self.record, 'not_loaded')]
        await self.notifier.restore(lost, failure)
        await self.notifier.restore(lost, failure)
        self.assertEqual(len(await self.notices()), 1)
        before = (await self.state.load_routes())['session_notifications']['outage']
        await self.notifier.select(self.snapshot, ('target',))
        current = (await self.state.load_routes())['session_notifications']
        self.assertEqual(current['outage'], before)
        self.assertEqual(current['issues'], {})
        await self.notifier.restore(lost, failure)
        self.assertEqual(len(await self.notices()), 2)

    async def test_changed_role_reason_is_reported_without_repeating_same_reason(self):
        lost = dict(self.snapshot, target=None, mode='unbound')
        await self.notifier.restore(lost, [('target', self.record, 'evidence_missing')])
        await self.notifier.restore(lost, [('target', self.record, 'evidence_missing')])
        await self.notifier.restore(lost, [('target', self.record, 'not_loaded')])
        await self.notifier.restore(lost, [('target', self.record, 'evidence_missing')])
        self.assertEqual(len(await self.notices()), 2)

    async def test_recovery_supersedes_unsent_fault_without_sending_stale_fault_or_recovery(self):
        await self.notifier.begin()
        self.advance(31)
        await self.notifier.tick()
        await self.notifier.recovered()
        rows = await self.state._call(lambda: list(self.state.db.execute('SELECT state FROM outbox')))
        self.assertEqual(rows, [('superseded',)])
        await self.deliver()
        self.assertIsNone(await self.state.claim_reply())

    async def test_unknown_fault_delivery_is_not_retried_but_allows_recovery_followup(self):
        await self.notifier.begin()
        self.advance(31)
        await self.notifier.tick()
        await self.deliver('unknown')
        await self.notifier.recovered()
        states = await self.state._call(lambda: [r[0] for r in self.state.db.execute('SELECT state FROM outbox ORDER BY rowid')])
        self.assertEqual(states, ['unknown', 'pending'])
        self.assertIn('已重新核验并恢复', (await self.notices())[1])

    async def test_registry_sanitized_selection_does_not_start_old_project_outage(self):
        await self.notifier.begin(snapshot=dict(self.snapshot, target=None, mode='unbound'))
        self.advance(31)
        await self.notifier.tick()
        self.assertEqual(await self.notices(), [])

    async def test_atomic_outage_commit_rolls_back_and_retry_is_single(self):
        await self.notifier.begin()
        original = await self.state.load_routes()
        await self.state._call(lambda: self.state.db.execute("""CREATE TEMP TRIGGER fail_notice
            BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'injected'); END"""))
        self.advance(31)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.notifier.tick()
        self.assertEqual(await self.state.load_routes(), original)
        await self.state._call(lambda: self.state.db.execute('DROP TRIGGER fail_notice'))
        await self.notifier.tick()
        await self.notifier.tick()
        self.assertEqual(len(await self.notices()), 1)

    async def test_oversized_route_rolls_back_notification_and_snapshot(self):
        original = await self.state.load_routes()
        large = dict(self.snapshot, unexpected='x' * 65536)
        with self.assertRaises(ValueError):
            await self.notifier.restore(large, [('target', self.record, 'evidence_missing')])
        self.assertEqual(await self.state.load_routes(), original)
        self.assertEqual(await self.notices(), [])

    async def test_concurrent_ticks_only_create_one_frozen_notice(self):
        await self.notifier.begin()
        self.advance(31)
        await asyncio.gather(*(self.notifier.tick() for _ in range(8)))
        self.assertEqual(len(await self.notices()), 1)

    async def test_invalid_notification_state_fails_closed(self):
        await self.state.save_routes(dict(self.snapshot, session_notifications={'version': True}))
        with self.assertRaises(ProtocolError):
            await self.notifier.begin()
