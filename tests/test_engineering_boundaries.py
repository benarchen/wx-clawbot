"""Scale boundaries use synthetic ledgers and native pages, never live services."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import test_catalog
import test_controller
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.commands import CommandError, parse_command


class StopCandidateTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_controller.ControllerTests.asyncSetUp
    incoming = test_controller.ControllerTests.incoming
    command = test_controller.ControllerTests.command
    select = test_controller.ControllerTests.select

    async def release_unknown(self, task):
        await self.state.task_update(task['id'], 'unknown')
        def release():
            self.state.db.execute('BEGIN IMMEDIATE')
            try:
                self.state._occupancy_transition(task['id'], 'released', 'synthetic_terminal_proof')
                self.state.db.execute('COMMIT')
            except BaseException:
                self.state.db.execute('ROLLBACK')
                raise
        await self.state._call(release)

    async def running(self):
        await self.select()
        await self.command('synthetic long-running task')
        task = (await self.state.tasks())[0]
        await self.state.task_update(task['id'], 'running', turn_id='synthetic-turn')
        return await self.state.tasks(task_id=task['id'])

    async def history(self, task, count=100):
        def insert():
            self.state.db.executemany('''INSERT INTO tasks
                (id,client_id,target,thread_id,input,state,created_at,updated_at)
                VALUES(?,?,?,?,'','completed',?,?)''',
                [(f'history-{i}', f'history-client-{i}', json.dumps(task['target']), task['thread_id'],
                  10**12 + i, 10**12 + i) for i in range(count)])
        await self.state._call(insert)

    async def waiting(self, task):
        message = await self.incoming('synthetic waiting task')
        created = await self.state.task_intent(message.message_id, task['target'], message.text)
        await self.state.task_update(created['id'], 'received')
        await self.state._call(lambda: self.state.db.execute(
            'UPDATE tasks SET created_at=? WHERE id=?', (10**13, created['id'])))
        return created

    async def test_old_running_beyond_recent_history_remains_unique_stop_candidate(self):
        task = await self.running()
        await self.history(task)
        await self.engine.control(parse_command('/stop'))
        self.queue.request_interrupt.assert_awaited_once_with('synthetic-turn')

    async def test_truncated_history_cannot_turn_two_candidates_into_one(self):
        task = await self.running()
        await self.history(task)
        waiting = await self.waiting(task)
        with self.assertRaises(CommandError):
            await self.engine.control(parse_command('/stop'))
        self.assertEqual((await self.state.tasks(task_id=waiting['id']))['state'], 'received')
        self.queue.request_interrupt.assert_not_awaited()
        self.queue.delete.assert_not_awaited()

    async def test_ten_thousand_settled_tasks_cannot_hide_running_task(self):
        task = await self.running()
        await self.history(task, 10000)
        await self.engine.control(parse_command('/stop'))
        self.queue.request_interrupt.assert_awaited_once_with('synthetic-turn')

    async def test_released_unknown_does_not_make_current_waiting_task_ambiguous(self):
        task = await self.running()
        await self.release_unknown(task)
        waiting = await self.waiting(task)
        await self.engine.control(parse_command('/stop'))
        self.assertEqual((await self.state.tasks(task_id=waiting['id']))['state'], 'cancelled')
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'], 'unknown')
        self.queue.request_interrupt.assert_not_awaited()

    async def test_exact_stop_of_released_unknown_cannot_reacquire_occupancy(self):
        task = await self.running()
        await self.release_unknown(task)
        await self.engine.control(parse_command('/stop ' + task['id']))
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'], 'unknown')
        self.assertEqual((await self.state.occupancy_snapshot(task_id=task['id']))[0]['occupancy']['state'], 'released')
        self.queue.delete.assert_not_awaited()
        self.queue.request_interrupt.assert_not_awaited()

    async def test_holding_unknown_keeps_stop_ambiguous(self):
        task = await self.running()
        await self.state.task_update(task['id'], 'unknown')
        await self.waiting(task)
        with self.assertRaises(CommandError):
            await self.engine.control(parse_command('/stop'))
        self.queue.request_interrupt.assert_not_awaited()

    async def test_exact_id_still_selects_old_task_among_multiple_candidates(self):
        task = await self.running()
        await self.history(task)
        await self.waiting(task)
        await self.engine.control(parse_command('/stop ' + task['id']))
        self.queue.request_interrupt.assert_awaited_once_with('synthetic-turn')

    async def test_discovery_failure_keeps_waiting_intent_and_allows_later_maintenance(self):
        from wx_clawbot.catalog import DiscoveryUnavailable
        task = await self.running()
        waiting = await self.waiting(task)
        self.catalog.discover.side_effect = DiscoveryUnavailable('Synthetic incomplete discovery')
        await self.engine.drain_admission()
        self.assertEqual((await self.state.tasks(task_id=waiting['id']))['state'], 'received')
        self.assertEqual(self.queue.add.await_count, 1)
        self.catalog.discover.side_effect = None
        await self.engine.drain_admission()
        self.assertEqual(self.queue.add.await_count, 2)

    async def test_new_submission_discovery_failure_has_no_native_intent(self):
        from wx_clawbot.catalog import DiscoveryUnavailable
        await self.select()
        self.catalog.discover.side_effect = DiscoveryUnavailable('Synthetic incomplete discovery')
        await self.command('synthetic task')
        self.assertEqual(await self.state.tasks(), [])
        self.queue.add.assert_not_awaited()


class CatalogPaginationTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_catalog.CatalogTests.setUp

    def pages(self, count, *, target_last=False):
        threads = [{**self.thread, 'id': f'other-{i}', 'sessionId': f'native-{i}'}
                   for i in range(count - 1)]
        threads.insert(len(threads) if target_last else 0, self.thread)
        async def page(cwd, *, cursor=None):
            offset = int(cursor) if cursor else 0
            end = offset + 100
            return {'data': threads[offset:end], 'nextCursor': str(end) if end < len(threads) else None}
        self.agent.list_project_threads.side_effect = page

    async def test_visible_target_in_first_page_survives_next_cursor(self):
        self.pages(101)
        sessions = await self.catalog.discover()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(self.agent.list_project_threads.await_count, 2)

    async def test_visible_target_in_last_page_is_found(self):
        self.pages(1000, target_last=True)
        sessions = await self.catalog.discover()
        self.assertEqual(sessions[0].binding.thread_id, self.thread['id'])
        self.assertEqual(self.agent.list_project_threads.await_count, 10)

    async def test_page_limit_refuses_incomplete_view(self):
        self.pages(1001)
        with self.assertRaises(ValueError):
            await self.catalog.discover()
        self.assertLessEqual(self.agent.list_project_threads.await_count, 10)
        self.assertEqual(self.catalog.sessions, {})

    async def test_repeated_cursor_and_duplicate_threads_are_refused(self):
        self.agent.list_project_threads.return_value = {'data': [self.thread], 'nextCursor': 'loop'}
        with self.assertRaises(ValueError):
            await self.catalog.discover()
        self.assertEqual(self.catalog.sessions, {})

    async def test_duplicate_identity_inside_one_page_is_refused(self):
        self.agent.list_project_threads.return_value = {'data': [self.thread, self.thread]}
        with self.assertRaises(ValueError):
            await self.catalog.discover()
        self.agent.inspect.assert_not_awaited()

    async def test_oversized_page_is_refused(self):
        self.agent.list_project_threads.return_value = {'data': [self.thread] * 101}
        with self.assertRaises(ValueError):
            await self.catalog.discover()

    async def test_failed_refresh_preserves_previous_snapshot(self):
        original = (await self.catalog.discover())[0]
        self.agent.list_project_threads.return_value = {'data': [self.thread], 'nextCursor': ''}
        with self.assertRaises(ValueError):
            await self.catalog.discover()
        self.assertEqual(self.catalog.sessions[original.target.session_id].binding.thread_id, self.thread['id'])

    async def test_hung_discovery_has_total_deadline(self):
        async def hung(*args, **kwargs):
            await asyncio.Event().wait()
        self.agent.list_project_threads.side_effect = hung
        with patch.object(SessionCatalog, 'DISCOVERY_SECONDS', .02, create=True):
            with self.assertRaises(ValueError):
                await asyncio.wait_for(self.catalog.discover(), .2)
        self.assertEqual(self.catalog.sessions, {})

    async def test_global_page_budget_is_enforced_before_next_rpc(self):
        self.pages(101)
        with patch.object(SessionCatalog, 'TOTAL_PAGES', 1):
            with self.assertRaises(ValueError):
                await self.catalog.discover()
        self.assertEqual(self.agent.list_project_threads.await_count, 1)

    async def test_global_thread_budget_is_enforced(self):
        self.pages(2)
        with patch.object(SessionCatalog, 'TOTAL_THREADS', 1):
            with self.assertRaises(ValueError):
                await self.catalog.discover()
        self.agent.inspect.assert_not_awaited()

    async def test_global_byte_budget_is_enforced(self):
        with patch.object(SessionCatalog, 'TOTAL_BYTES', 16):
            with self.assertRaises(ValueError):
                await self.catalog.discover()
        self.agent.inspect.assert_not_awaited()

    async def test_unregistered_page_directory_is_refused(self):
        self.agent.list_project_threads.return_value = {'data': [{**self.thread, 'cwd': str(self.root.parent)}]}
        with self.assertRaises(ValueError):
            await self.catalog.discover()
        self.agent.inspect.assert_not_awaited()

    async def test_endpoint_budget_is_checked_before_native_reads(self):
        self.directory.discover.return_value = [self.endpoint] * 257
        with self.assertRaises(ValueError):
            await self.catalog.discover()
        self.agent.list_project_threads.assert_not_awaited()

    async def test_same_thread_cannot_appear_in_two_project_scopes(self):
        from dataclasses import replace
        from wx_clawbot.config import Project
        second = replace(self.endpoint, terminal_id='second-terminal')
        nested = self.root / 'nested'
        nested.mkdir()
        self.directory.discover.return_value = [self.endpoint, second]
        self.directory.cwd.side_effect = lambda e: nested if e == second else self.root
        self.agent.list_project_threads.side_effect = lambda cwd: {'data': [{**self.thread, 'cwd': str(cwd)}]}
        catalog = SessionCatalog((self.project, Project('nested', nested)), self.directory, self.agent)
        with self.assertRaises(ValueError):
            await catalog.discover()
        self.assertEqual(catalog.sessions, {})
