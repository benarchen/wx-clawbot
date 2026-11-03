import unittest
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import test_controller
from test_runtime_state import RuntimeFixture
from wx_clawbot.controller import target_record
from wx_clawbot.sessions import SessionUnbound
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.admission_recovery import terminal_evidence, EvidenceUnavailable
from wx_clawbot.occupancy import ACTIVE_FROM, ACTIVE_WHERE


class AdmissionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_controller.ControllerTests.asyncSetUp
    incoming = test_controller.ControllerTests.incoming
    command = test_controller.ControllerTests.command
    select = test_controller.ControllerTests.select

    async def unique_result_case(self, released=False):
        await self.select()
        destination=self.sessions[1]
        incoming=await self.incoming('known completed input')
        task=await self.state.task_intent(incoming.message_id,target_record(destination),'known completed input')
        await self.state.task_update(task['id'],'unknown',queue_id='known-queue',turn_id='known-turn')
        turn={'id':'known-turn','status':'completed','items':[
            {'type':'userMessage','clientId':task['client_id']},{'type':'agentMessage','text':'EXACT-RECOVERED-RESULT'}]}
        async def request(method,params):
            if method=='thread/queue/list':return {'data':[],'nextCursor':None}
            if method=='thread/turns/list':return {'data':[turn],'nextCursor':None}
            raise AssertionError(method)
        self.agent.rpc.request.side_effect=request
        self.agent.inspect.return_value={'id':'thread-two','cwd':str(destination.target.cwd),'status':{'type':'idle'}}
        if released:
            rows=await self.state.occupancy_snapshot(task_id=task['id'])
            await self.state.release_occupancies(rows,{'kind':'native_terminal','thread_id':'thread-two',
                'turns':{'known-turn':'completed'},'queue_empty':True,'generation':'fixture'})
            self.assertEqual(await self.state.tasks(active_only=True),[])
        await self.engine.reconcile()
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'],'completed')
        finals=await self.state._call(lambda:list(self.state.db.execute("SELECT text FROM outbox WHERE task_id=? AND kind='final'",(task['id'],))))
        self.assertEqual(len(finals),1)
        self.assertIn('EXACT-RECOVERED-RESULT',finals[0][0])

    async def test_unique_completed_result_is_recovered_before_unknown_hold_is_archived(self):
        await self.unique_result_case()

    async def test_released_unknown_can_still_recover_exact_result_on_later_refresh(self):
        await self.unique_result_case(released=True)

    async def test_released_unknown_task_subscription_is_pruned_without_removing_focus(self):
        await self.select()
        target=self.sessions[0].target
        incoming=await self.incoming('old subscribed task')
        task=await self.state.task_intent(incoming.message_id,target_record(self.sessions[0]),'old subscribed task')
        await self.state.task_update(task['id'],'unknown',turn_id='old-turn')
        await self.controller.subscriptions.acquire(target,'task-'+task['id'])
        rows=await self.state.occupancy_snapshot(task_id=task['id'])
        evidence={'kind':'native_terminal','thread_id':'thread-one','turns':{'old-turn':'completed'},'queue_empty':True,'generation':'fixture'}
        await self.state.release_occupancies(rows,evidence)
        await self.engine.prune_memory()
        self.assertNotIn(target.session_id,self.controller.subscriptions.bound)
        self.assertEqual(self.controller.routes.target,self.sessions[1].target)
        self.assertIn(self.sessions[1].target.session_id,self.controller.subscriptions.bound)

    async def test_merged_terminal_history_releases_occupancy_without_inventing_results(self):
        await self.select()
        destination = self.sessions[1]
        old = target_record(destination)
        old['session_id'] = 'old-session'
        old['repository'] = 'directory:' + str(destination.target.cwd)
        incoming = await self.incoming('old task')
        task = await self.state.task_intent(incoming.message_id, old, 'old task')
        await self.state.task_update(task['id'], 'unknown', queue_id='old-queue', turn_id='old-turn')
        external = await self.state.external_task(old, 'old-turn', native_client_id='desktop-client')
        await self.state.task_update(external['id'], 'unknown')
        users = [{'type': 'userMessage', 'clientId': c} for c in (task['client_id'], 'desktop-client')]
        async def request(method, params):
            if method == 'thread/queue/list':
                return {'data': [], 'nextCursor': None}
            if method == 'thread/turns/list':
                return {'data': [{'id': 'old-turn', 'status': 'completed', 'items': users}], 'nextCursor': None}
            raise AssertionError(method)
        self.agent.rpc.request.side_effect = request
        self.agent.inspect.return_value = {'id': 'thread-two', 'cwd': str(destination.target.cwd), 'status': {'type': 'idle'}}
        original_require = self.catalog.require.side_effect
        async def require(target):
            if target.session_id == 'old-session':
                raise SessionUnbound('Original terminal no longer present')
            return await original_require(target)
        self.catalog.require.side_effect = require
        await self.command('new task')
        waiting = (await self.state.tasks())[0]
        self.assertEqual(waiting['state'], 'received')
        await self.engine.reconcile()
        await self.engine.drain_admission()
        self.assertEqual((await self.state.tasks(task_id=waiting['id']))['state'], 'queued')
        for identity in (task['id'], external['id']):
            self.assertEqual((await self.state.tasks(task_id=identity))['state'], 'unknown')
        self.queue.add.assert_awaited_once()


class OccupancyCapacityTests(RuntimeFixture):
    async def unknown(self, identity=1):
        task = await self.admit(identity)
        await self.state.task_update(task['id'],'unknown',turn_id='fixture-turn',queue_id='fixture-queue')
        return (await self.state.occupancy_snapshot(task_id=task['id']))[0]

    def evidence(self):
        return {'kind':'native_terminal','thread_id':'fixture-thread','turns':{'fixture-turn':'completed'},
                'queue_empty':True,'generation':'fixture-generation'}

    async def test_released_unknown_does_not_consume_active_capacity(self):
        task = await self.unknown()
        await self.state.release_occupancies([task],self.evidence())
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'],'unknown')
        self.assertEqual(await self.state.tasks(active_only=True),[])
        self.assertEqual((await self.state.occupancy_counts())['released_unknown'],1)
        await self.restart()
        self.assertEqual(await self.state.tasks(active_only=True),[])
        self.assertEqual((await self.state.occupancy_snapshot(task_id=task['id']))[0]['occupancy']['state'],'released')

    async def test_state_change_invalidates_release_evidence(self):
        task = await self.unknown()
        await self.state.task_update(task['id'],'running')
        with self.assertRaisesRegex(ProtocolError,'stale'):
            await self.state.release_occupancies([task],self.evidence())
        self.assertEqual((await self.state.occupancy_snapshot(task_id=task['id']))[0]['occupancy']['state'],'holding')

    async def test_group_release_and_audit_roll_back_together(self):
        first,second = await self.unknown(1),await self.unknown(2)
        await self.state._call(lambda:self.state.db.execute("CREATE TRIGGER deny_release BEFORE INSERT ON occupancy_audit WHEN NEW.state='released' BEGIN SELECT RAISE(ABORT,'fixture failure'); END"))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.release_occupancies([first,second],self.evidence())
        self.assertEqual({t['occupancy']['state'] for t in await self.state.occupancy_snapshot()}, {'holding'})

    async def test_late_native_activity_reacquires_without_rewriting_unknown(self):
        task = await self.unknown()
        await self.state.release_occupancies([task],self.evidence())
        self.assertTrue(await self.state.reactivate_occupancy('fixture-thread','fixture-turn'))
        self.assertFalse(await self.state.reactivate_occupancy('unrelated','fixture-turn'))
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'],'unknown')
        row=(await self.state.occupancy_snapshot(task_id=task['id']))[0]
        self.assertEqual((row['occupancy']['state'],row['occupancy']['reason']),('holding','late_native_activity'))

    async def test_released_unknown_survives_retention(self):
        from wx_clawbot.retention import maintain
        task = await self.unknown()
        await self.state.release_occupancies([task],self.evidence())
        before=(await self.state.tasks(task_id=task['id']))
        await self.state.close()
        report=maintain(self.root,self.credentials,now=9999999999,apply=True)
        await self.restart()
        self.assertEqual(await self.state.tasks(task_id=task['id']),before)
        self.assertEqual(report['changed_rows']['terminal_task_summaries'],0)

    async def test_wait_notifications_are_once_and_persist_across_restart(self):
        intent=await self.admit()
        await self.state.task_update(intent['id'],'received')
        task=await self.state.tasks(task_id=intent['id'])
        for now in (100,90,159,160,161,10000):
            await self.state.admission_wait(task,'fixture blocker',['old-task'],now=now)
        rows=await self.state._call(lambda:list(self.state.db.execute('SELECT id FROM outbox ORDER BY rowid')))
        self.assertEqual([r[0] for r in rows],[task['id']+'-waiting',task['id']+'-waiting-60'])
        await self.restart()
        await self.state.admission_wait(task,'fixture blocker',['old-task'],now=20000)
        self.assertEqual((await self.state.admission_wait_status(task['id']))['escalated'],1)
        self.assertEqual(len(await self.state._call(lambda:list(self.state.db.execute('SELECT id FROM outbox')))),2)
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'],'received')

    async def test_capacity_bound_uses_active_occupancies_and_history_is_paged(self):
        released=[]
        for i in range(1,4):
            task=await self.unknown(i)
            await self.state.release_occupancies([task],self.evidence())
            released.append(task['id'])
        for i in range(4,132):
            await self.admit(i)
        self.assertEqual(len(await self.state.tasks(active_only=True)),128)
        with self.assertRaisesRegex(ProtocolError,'bound'):
            await self.admit(132)
        page=await self.state.occupancy_history(limit=2)
        rest=await self.state.occupancy_history(after=page[-1]['task_id'],limit=2)
        self.assertEqual([t['task_id'] for t in page+rest],sorted(released))
        plan=await self.state._call(lambda:list(self.state.db.execute(f'EXPLAIN QUERY PLAN SELECT count(*) FROM {ACTIVE_FROM} WHERE {ACTIVE_WHERE}')))
        self.assertTrue(any('occupancy_active' in str(r) for r in plan))
        def corrupt_overflow():
            self.state.db.execute('BEGIN IMMEDIATE')
            self.state.db.execute("""INSERT INTO tasks(id,client_id,target,thread_id,input,state,created_at,updated_at)
                VALUES('overflow','overflow-client','{}','overflow-thread','fixture','received',1,1)""")
            self.state._occupancy_transition('overflow','waiting','fixture_overflow')
            self.state.db.execute('COMMIT')
        await self.state._call(corrupt_overflow)
        with self.assertRaisesRegex(ProtocolError,'partial'):
            await self.state.tasks(active_only=True)
        with self.assertRaisesRegex(ProtocolError,'incomplete'):
            await self.state.occupancy_snapshot()


class NativeEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        task={'id':'old','state':'unknown','thread_id':'thread','turn_id':'turn','client_id':'client',
              'target':{'cwd':'/fixture/project'},'occupancy':{'revision':1}}
        turn={'id':'turn','status':'completed','items':[{'type':'userMessage','clientId':'client'}]}
        async def request(method,params):
            if method=='thread/queue/list':return {'data':[],'nextCursor':None}
            if method=='thread/turns/list':return {'data':[turn],'nextCursor':None}
            raise AssertionError('Mutating native call: '+method)
        native=SimpleNamespace(inspect=AsyncMock(return_value={'id':'thread','cwd':'/fixture/project','status':{'type':'idle'}}),rpc=SimpleNamespace(request=AsyncMock(side_effect=request)))
        return native,task,turn

    async def test_terminal_and_empty_queue_prove_historical_ownership_without_resume(self):
        native,task,turn=self.fixture()
        result=await terminal_evidence(native,[task],'generation')
        self.assertEqual(result['turns'],{'turn':'completed'})
        self.assertEqual([c.args[0] for c in native.rpc.request.await_args_list],['thread/queue/list','thread/turns/list','thread/queue/list'])

    async def test_busy_idle_alone_missing_client_and_running_tool_fail_closed(self):
        for scenario in ('busy','missing_client','running_tool','not_terminal'):
            native,task,turn=self.fixture()
            if scenario=='busy':native.inspect.return_value['status']['type']='active'
            if scenario=='missing_client':turn['items']=[]
            if scenario=='running_tool':turn['items'].append({'type':'commandExecution','status':'inProgress'})
            if scenario=='not_terminal':turn['status']='inProgress'
            with self.subTest(scenario=scenario),self.assertRaises(EvidenceUnavailable):
                await terminal_evidence(native,[task],'generation')

    async def test_queue_insertion_during_read_and_repeated_history_cursor_fail_closed(self):
        native,task,turn=self.fixture()
        native.rpc.request.side_effect=[{'data':[],'nextCursor':None},{'data':[turn],'nextCursor':None},{'data':[{'id':'queued'}],'nextCursor':None}]
        with self.assertRaisesRegex(EvidenceUnavailable,'queue_changed'):
            await terminal_evidence(native,[task],'generation')
        native,task,turn=self.fixture()
        native.rpc.request.side_effect=[{'data':[],'nextCursor':None},{'data':[],'nextCursor':'cursor'},{'data':[],'nextCursor':'cursor'}]
        with self.assertRaisesRegex(EvidenceUnavailable,'cursor'):
            await terminal_evidence(native,[task],'generation')

    async def test_duplicate_client_history_cannot_release(self):
        native,task,turn=self.fixture()
        native.rpc.request.side_effect=[{'data':[],'nextCursor':None},{'data':[dict(turn,id='other')],'nextCursor':'next'},{'data':[turn],'nextCursor':None}]
        with self.assertRaisesRegex(EvidenceUnavailable,'duplicate_client'):
            await terminal_evidence(native,[task],'generation')

    async def test_found_exact_original_turn_does_not_scan_unrelated_older_history(self):
        native,task,turn=self.fixture()
        native.rpc.request.side_effect=[{'data':[],'nextCursor':None},{'data':[turn],'nextCursor':'unrelated-old-history'},{'data':[],'nextCursor':None}]
        self.assertEqual((await terminal_evidence(native,[task],'generation'))['turns'],{'turn':'completed'})
        self.assertEqual(native.rpc.request.await_count,3)

    async def test_malformed_task_status_and_client_fail_as_evidence_unavailable(self):
        for scenario in ('missing_cwd','malformed_status','malformed_client','malformed_item'):
            native,task,turn=self.fixture()
            if scenario=='missing_cwd':task['target']={}
            if scenario=='malformed_status':native.inspect.return_value['status']=None
            if scenario=='malformed_client':turn['items'][0]['clientId']={}
            if scenario=='malformed_item':turn['items'].append(None)
            with self.subTest(scenario=scenario),self.assertRaises(EvidenceUnavailable):
                await terminal_evidence(native,[task],'generation')
