"""Whole native selection, snapshot compatibility and result-only recovery."""

from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import test_independent_target as fixtures
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.controller import Controller, RouteCommitFailed
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.lifecycle import HostUnavailable
from wx_clawbot.sessions import legacy_binding_key


class NativeTargetLifecycleTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.IndependentTargetTests.asyncSetUp
    command = fixtures.IndependentTargetTests.command
    desktop_switch = fixtures.IndependentTargetTests.desktop_switch

    def fresh_controller(self):
        catalog = SessionCatalog((self.project,), self.directory, self.agent)
        # This shared fixture models an already attested managed A. Independent
        # startup tests cover how that marker is established from its receipt.
        catalog.managed_threads.update(self.catalog.managed_threads)
        controller = Controller((self.project,), catalog, self.state, self.starter,
                                Path('/fixture/codex'), Path('/fixture/home'))
        engine = Execution(controller)
        engine.queue = lambda key, _: self.queues[key]
        self.addAsyncCleanup(engine.close)
        return controller

    async def test_all_native_operations_trap_screen_identity_reads(self):
        self.directory.current_thread_id.side_effect = AssertionError('No screen identity allowed')
        self.directory.validate.side_effect = AssertionError('No host pairing allowed')
        await self.command('Continue the explicitly selected A')
        self.assertEqual((await self.state.tasks())[0]['thread_id'], 'thread-a')
        self.queues['thread-a'].add.assert_awaited_once()

    async def test_v2_restore_survives_missing_sdk_and_keeps_native_stable_id(self):
        snapshot = await self.state.load_routes()
        self.assertEqual(snapshot['version'], 2)
        self.assertEqual(snapshot['target']['runtime_identity'], [1, 2])
        self.directory.discover.side_effect = HostUnavailable('not_running')
        controller = self.fresh_controller()
        await controller.restore()
        self.assertEqual(controller.routes.target, self.a)
        self.assertIsNone(controller.catalog.sessions[self.a.session_id].binding.endpoint)
        self.queues['thread-a'].add.assert_not_called()

    async def test_runtime_or_native_session_change_never_restores_same_named_dialogue(self):
        snapshot = await self.state.load_routes()
        for change in ('runtime', 'native-session'):
            self.agent.runtime_identity = (1, 2)
            self.threads['thread-a']['sessionId'] = 'session-thread-a'
            await self.state.save_routes(snapshot)
            if change == 'runtime':
                self.agent.runtime_identity = (3, 4)
            else:
                self.threads['thread-a']['sessionId'] = 'different-root'
            controller = self.fresh_controller()
            await controller.restore()
            with self.subTest(change=change):
                self.assertIsNone(controller.routes.target)
                self.queues['thread-a'].add.assert_not_called()
                persisted = await self.state.load_routes()
                self.assertEqual(persisted['unrestored_selection']['target'], snapshot['target'])
                again = self.fresh_controller()
                await again.restore()
                self.assertIsNone(again.routes.target)
                self.assertEqual((await self.state.load_routes())['unrestored_selection'],
                                 persisted['unrestored_selection'])

    async def legacy_snapshot(self):
        session = self.catalog.sessions[self.a.session_id]
        target = replace(self.a, session_id=legacy_binding_key(self.endpoint, session.binding))
        record = asdict(target)
        record.update(cwd=str(target.cwd), thread_id=session.binding.thread_id)
        snapshot = {'version': 1, 'revision': 4, 'mode': 'focused', 'project': self.project.alias,
                    'cwd': str(self.root), 'target': record, 'observer': None, 'last_managed': []}
        await self.state.save_routes(snapshot)
        return target, record

    async def test_legacy_fingerprint_migrates_only_with_exact_real_host_and_native_proof(self):
        old, _ = await self.legacy_snapshot()
        controller = self.fresh_controller()
        await controller.restore()
        self.assertEqual(controller.routes.target, self.a)
        self.assertNotEqual(controller.routes.target.session_id, old.session_id)
        self.assertEqual((await self.state.load_routes())['version'], 2)
        self.queues['thread-a'].add.assert_not_called()

    async def test_legacy_fingerprint_with_changed_process_source_not_guessed_from_loaded_id(self):
        await self.legacy_snapshot()
        self.directory.discover.return_value = [replace(self.endpoint, terminal_id='different-endpoint')]
        controller = self.fresh_controller()
        await controller.restore()
        self.assertIsNone(controller.routes.target)
        texts = await self.state._call(lambda: [r[0] for r in self.state.db.execute('SELECT text FROM outbox')])
        self.assertTrue(any('未恢复对应选择' in text for text in texts))

    async def test_corrupted_boolean_snapshot_version_is_not_a_legacy_version(self):
        snapshot = await self.state.load_routes()
        snapshot['version'] = True
        await self.state.save_routes(snapshot)
        with self.assertRaises(RouteCommitFailed):
            await self.fresh_controller().restore()

    async def test_bad_runtime_field_types_do_not_restore_v2(self):
        snapshot = await self.state.load_routes()
        snapshot['target']['runtime_identity'] = [True, 2]
        snapshot['last_managed'] = []
        await self.state.save_routes(snapshot)
        controller = self.fresh_controller()
        await controller.restore()
        self.assertIsNone(controller.routes.target)

    async def test_unknown_legacy_result_can_reconcile_unloaded_native_without_route_or_replay(self):
        await self.command('One already submitted task')
        task = (await self.state.tasks())[0]
        frozen = dict(task['target'])
        frozen['session_id'] = 'old-terminal-fingerprint'
        frozen.pop('runtime_identity')
        frozen.pop('native_session_id')
        encoded = json.dumps(frozen, ensure_ascii=False, sort_keys=True)
        await self.state._call(lambda: self.state.db.execute('UPDATE tasks SET target=? WHERE id=?', (encoded, task['id'])))
        await self.state.task_update(task['id'], 'unknown')
        self.threads['thread-a']['status'] = {'type': 'notLoaded'}
        controller = self.fresh_controller()
        await controller.catalog.discover()
        self.agent.rpc = SimpleNamespace(request=AsyncMock(return_value={'data': [{
            'id': 'original-turn', 'status': 'completed', 'items': [
                {'type': 'userMessage', 'clientId': task['client_id']},
                {'type': 'agentMessage', 'text': 'the exact retained result'}]}], 'nextCursor': None}))
        self.agent.observe_loaded.reset_mock()
        await controller.engine.reconcile_results()
        recovered = await self.state.tasks(task_id=task['id'])
        self.assertEqual(recovered['state'], 'completed')
        self.assertEqual(recovered['target'], frozen)
        self.assertIsNone(controller.routes.target)
        self.agent.observe_loaded.assert_not_called()
        self.queues['thread-a'].add.assert_awaited_once()  # Only the original input.

    async def test_declared_directory_scope_cannot_be_expanded_outside_registration(self):
        with self.assertRaises(ValueError):
            self.catalog.include_directory(self.root.parent)
        await self.catalog.discover()
        self.assertTrue(all(call.args[0] == self.root for call in self.agent.list_project_threads.await_args_list))

    async def test_exact_child_cwd_is_found_only_after_explicit_scope_registration(self):
        child = self.root / 'child'
        child.mkdir()
        self.threads['thread-b']['cwd'] = str(child)
        async def page(cwd, **_):
            return {'data': [v for v in self.threads.values() if v['cwd'] == str(cwd)]}
        self.agent.list_project_threads.side_effect = page
        initial = await self.catalog.discover()
        self.assertEqual([s.binding.thread_id for s in initial], ['thread-a'])
        self.catalog.include_directory(child)
        found = await self.catalog.discover()
        self.assertEqual({s.binding.thread_id for s in found}, {'thread-a', 'thread-b'})
        self.assertEqual({call.args[0] for call in self.agent.list_project_threads.await_args_list},
                         {self.root, child})
        self.assertIn('不作递归扫描', self.catalog.scope_note)

    async def test_known_directory_cap_cannot_silently_drop_the_last_directory(self):
        from wx_clawbot.catalog import DiscoveryUnavailable
        child = self.root / 'candidate'
        child.mkdir()
        self.catalog.directories = {self.root / str(i) for i in range(256)}
        with self.assertRaises(DiscoveryUnavailable):
            self.catalog.include_directory(child)
        self.assertNotIn(child, self.catalog.directories)

    async def test_same_thread_in_multiple_hosts_deduplicates_without_using_their_ids(self):
        self.directory.discover.return_value = [self.endpoint, replace(self.endpoint, terminal_id='second-host')]
        self.directory.current_thread_id.side_effect = AssertionError('Cannot infer by host')
        sessions = await self.catalog.discover()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].target, self.a)
