import asyncio
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from test_runtime_state import RuntimeFixture
from wx_clawbot.admission_recovery import AdmissionRecovery, EvidenceUnavailable
from wx_clawbot.channels.http import ProtocolError


class RecoverySchedulingTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.task=await self.admit()
        await self.state.task_update(self.task['id'],'unknown',turn_id='fixture-turn')
        self.engine=SimpleNamespace(state=self.state,inflight=set(),native=object(),generation='fixture-generation',
            admission_gate=asyncio.Lock(),controller=SimpleNamespace(native_ready=True),reconcile_results=AsyncMock())
        self.now=0
        self.recovery=AdmissionRecovery(self.engine,clock=lambda:self.now)

    def evidence(self):
        return {'kind':'native_terminal','thread_id':'fixture-thread','turns':{'fixture-turn':'completed'},
                'queue_empty':True,'generation':'fixture-generation'}

    async def test_failure_backoff_is_bounded_and_successful_history_does_not_poll(self):
        with patch('wx_clawbot.admission_recovery.terminal_evidence',side_effect=EvidenceUnavailable('native_still_active')) as read:
            for now,expected in ((0,1),(.5,1),(1,2),(2,2),(3,3),(8,4),(23,5),(52,5),(53,6)):
                self.now=now
                await self.recovery.reconcile()
                self.assertEqual(read.await_count,expected)
        with patch('wx_clawbot.admission_recovery.terminal_evidence',return_value=self.evidence()) as read:
            await self.recovery.reconcile(force=True)
            await self.recovery.reconcile(force=True)
            read.assert_awaited_once()
        self.assertEqual(self.recovery.schedule,{})

    async def test_slow_native_check_never_holds_admission_gate(self):
        entered,release=asyncio.Event(),asyncio.Event()
        async def slow(*_):
            entered.set();await release.wait();return self.evidence()
        with patch('wx_clawbot.admission_recovery.terminal_evidence',side_effect=slow):
            work=asyncio.create_task(self.recovery.reconcile())
            try:
                await entered.wait()
                await asyncio.wait_for(self.engine.admission_gate.acquire(),.1)
                self.engine.admission_gate.release()
                release.set();await work
            finally:
                work.cancel();await asyncio.gather(work,return_exceptions=True)

    async def test_revision_change_between_read_and_release_is_rejected(self):
        async def changed(*_):
            await self.state.task_update(self.task['id'],'unknown')
            return self.evidence()
        with patch('wx_clawbot.admission_recovery.terminal_evidence',side_effect=changed):
            await self.recovery.reconcile()
        self.assertEqual((await self.state.occupancy_snapshot(task_id=self.task['id']))[0]['occupancy']['state'],'holding')

    async def test_generation_retirement_and_inflight_submission_block_release(self):
        self.engine.controller.native_ready=False
        with patch('wx_clawbot.admission_recovery.terminal_evidence',return_value=self.evidence()):
            await self.recovery.reconcile()
        self.assertEqual((await self.state.occupancy_snapshot(task_id=self.task['id']))[0]['occupancy']['state'],'holding')
        self.engine.inflight.add('fixture-thread')
        with patch('wx_clawbot.admission_recovery.terminal_evidence') as read:
            await self.recovery.reconcile(force=True)
            read.assert_not_awaited()

    async def test_timeout_is_observable_and_does_not_release(self):
        self.recovery.query_timeout=.01
        async def hung(*_):await asyncio.Event().wait()
        with patch('wx_clawbot.admission_recovery.terminal_evidence',side_effect=hung):
            await self.recovery.reconcile()
        hold=(await self.state.occupancy_snapshot(task_id=self.task['id']))[0]['occupancy']
        self.assertEqual((hold['state'],hold['reason']),('holding','native_query_unavailable'))
        self.assertIsNotNone(hold['checked_at'])
        status=await self.state.describe_admission(await self.state.tasks(task_id=self.task['id']))
        self.assertIn('原生查询暂不可用',status)
        self.assertIn('最后占用核验',status)

    async def test_native_terminal_signal_expedites_recheck_without_retaining_history_cache(self):
        with patch('wx_clawbot.admission_recovery.terminal_evidence',side_effect=EvidenceUnavailable('native_still_active')) as read:
            await self.recovery.reconcile()
            await self.recovery.reconcile()
            read.assert_awaited_once()
            self.recovery.trigger('fixture-thread')
            await self.recovery.reconcile()
            self.assertEqual(read.await_count,2)

    async def test_storage_failure_is_not_disguised_as_native_unavailability(self):
        with patch('wx_clawbot.admission_recovery.terminal_evidence',return_value=self.evidence()), \
                patch.object(self.state,'release_occupancies',side_effect=ProtocolError('fixture storage failure')):
            with self.assertRaisesRegex(ProtocolError,'storage failure'):
                await self.recovery.reconcile()

    async def test_unbound_exact_started_event_reacquires_historical_ownership_only(self):
        from wx_clawbot.execution import Execution
        # An event with a known original turn is allowed to restore a hold even
        # when that thread is no longer a route/subscription. Unknown turns are ignored.
        snapshots=await self.state.occupancy_snapshot(holding_only=True)
        await self.state.release_occupancies(snapshots,self.evidence())
        controller=SimpleNamespace(state=self.state,catalog=SimpleNamespace(agent=object()),
                                   subscriptions=SimpleNamespace(bound={}))
        engine=Execution(controller)
        try:
            await engine.event({'method':'turn/started','params':{'threadId':'unrelated','turn':{'id':'fixture-turn'}}})
            self.assertEqual((await self.state.occupancy_snapshot(task_id=self.task['id']))[0]['occupancy']['state'],'released')
            await engine.event({'method':'turn/started','params':{'threadId':'fixture-thread','turn':{'id':'fixture-turn'}}})
            self.assertEqual((await self.state.occupancy_snapshot(task_id=self.task['id']))[0]['occupancy']['state'],'holding')
        finally:await engine.close()
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'],'unknown')
