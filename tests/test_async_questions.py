import asyncio
import json
import time
import unittest
import sqlite3
from contextlib import closing
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import test_controller as fixtures
from wx_clawbot.agents.rpc import OutcomeUnknown, RpcError
from wx_clawbot.async_questions import answer_text, questions_from
from wx_clawbot.commands import CommandError, parse_command
from wx_clawbot.hosts.discovery import TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity
from wx_clawbot.sessions import SessionBinding
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.execution import Execution
from wx_clawbot import schema


class AsyncFixture(unittest.IsolatedAsyncioTestCase):
    incoming = fixtures.ControllerTests.incoming
    command = fixtures.ControllerTests.command
    select = fixtures.ControllerTests.select

    async def asyncSetUp(self):
        await fixtures.ControllerTests.asyncSetUp(self)
        self.agent.server_version = '0.166.0'
        self.agent.runtime_identity = (1, 2)
        for session in self.sessions:
            session.binding = SessionBinding(TerminalEndpoint('tty-' + session.target.session_id,
                ProcessIdentity(123, (1, 2), '/fixture/codex', 12), 'codex_candidate'),
                session.target.cwd, (1, 2), session.binding.thread_id, 'native-' + session.target.session_id)

    async def question(self, *, questions=None, item_id='fixture-question'):
        await self.select()
        await self.command('fixture business task')
        task = (await self.state.tasks())[0]
        self.task, self.thread, self.turn = task, task['thread_id'], 'fixture-turn'
        original = {'type': 'userMessage', 'clientId': task['client_id']}
        await self.engine.event({'method':'item/started','params':{'threadId':self.thread,
            'turnId':self.turn,'item':original}})
        self.native_turn = {'id':self.turn,'status':'inProgress','items':[original]}
        self.engine.read_turn = AsyncMock(side_effect=lambda *_: self.native_turn)
        self.item = {'id':item_id,'type':'agentMessage','delivery':'async','phase':'final_answer',
            'text':'Fixture question', 'questions':questions or [{'title':'中文 choice?','options':['ALPHA','BETA']}]}
        await self.emit(self.item)
        rows = await self.state.async_rows(thread_turn=(self.thread,self.turn))
        return rows[0] if rows else None

    async def emit(self, item):
        await self.engine.event({'method':'item/completed','params':{'threadId':self.thread,
            'turnId':self.turn,'item':item}})

    async def row(self, public_id):
        return (await self.state.async_rows(public_id=public_id))[0]

    async def answer(self, row, text='BETA'):
        self.agent.rpc.request.return_value = {'turnId':self.turn}
        return await self.engine.control(parse_command('/answer ' + row['public_id'] + ' ' + text))

    async def user(self, row, *, text=None, client=None):
        return {'type':'userMessage','clientId':client or row['answer_client'],
                'content':[{'type':'text','text':text if text is not None else row['answer_text']}]}


class AsyncQuestionTests(AsyncFixture):
    async def test_incomplete_started_waits_for_completed(self):
        row = await self.question()
        partial = {**self.item,'id':'second-item','questions':None}
        await self.engine.event({'method':'item/started','params':{'threadId':self.thread,'turnId':self.turn,'item':partial}})
        self.assertEqual(len(await self.state.async_rows(active=True)),1)
        await self.emit({**self.item,'id':'second-item'})
        self.assertEqual(len(await self.state.async_rows(active=True)),2)

    async def test_immediate_card_duplicate_event_and_task_running(self):
        row = await self.question()
        self.assertEqual(row['state'],'pending')
        await self.emit(self.item)
        rows = await self.state._call(lambda:list(self.state.db.execute("SELECT text FROM outbox WHERE kind='async_question'")))
        self.assertEqual(len(rows),1)
        self.assertIn('/answer '+row['public_id'],rows[0][0])
        self.assertIn('任务可能继续',rows[0][0])
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'],'running')

    async def test_answer_accepted_observed_and_original_completed_once(self):
        row = await self.question()
        response = await self.answer(row)
        self.assertIn('尚未证明模型采用',response)
        row = await self.row(row['public_id'])
        self.assertEqual(row['state'],'accepted')
        method, params = self.agent.rpc.request.await_args.args
        self.assertEqual(method,'turn/steer')
        self.assertEqual(params['expectedTurnId'],self.turn)
        user = await self.user(row)
        await self.engine.event({'method':'item/started','params':{'threadId':self.thread,'turnId':self.turn,'item':user}})
        self.assertEqual(len(await self.state.tasks()),1)
        self.assertEqual((await self.row(row['public_id']))['state'],'observed')
        turn = {**self.native_turn,'status':'completed','items':[*self.native_turn['items'],user,
            {'type':'agentMessage','phase':'final_answer','text':'fixture final'}]}
        await self.engine.complete(self.thread,turn)
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'],'completed')
        self.queue.add.assert_awaited_once()
        self.agent.rpc.respond.assert_not_awaited()

    async def test_two_concurrent_opposite_bridge_answers_submit_once(self):
        row = await self.question()
        results = await asyncio.gather(self.answer(row,'ALPHA'),self.answer(row,'BETA'),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,CommandError) for r in results),1)
        self.agent.rpc.request.assert_awaited_once()

    async def test_optional_host_provenance_and_host_loss_do_not_change_native_answer_target(self):
        from types import SimpleNamespace
        row = await self.question()
        self.sessions[1].binding = replace(self.sessions[1].binding, endpoint=None)
        self.controller.host = SimpleNamespace(state='unavailable', phase='not_running')
        await self.answer(row)
        saved = await self.row(row['public_id'])
        self.assertEqual(saved['state'], 'accepted')
        self.agent.rpc.request.assert_awaited_once()

    async def test_losing_concurrent_preflight_cannot_close_winning_answer_intent(self):
        row=await self.question()
        original=self.catalog.require
        gate=asyncio.Event()
        arrived=0
        async def require(target):
            nonlocal arrived
            result=await original(target)
            arrived+=1
            if arrived==2:gate.set()
            await gate.wait()
            return result
        async def native(*_):
            await asyncio.sleep(.03)
            return {'turnId':self.turn}
        self.agent.rpc.request.side_effect=native
        with patch.object(self.catalog,'require',side_effect=require):
            results=await asyncio.gather(self.answer(row,'ALPHA'),self.answer(row,'BETA'),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,CommandError) for r in results),1)
        self.agent.rpc.request.assert_awaited_once()
        saved=await self.row(row['public_id'])
        self.assertEqual(saved['state'],'accepted')
        self.assertIsNone(saved['closed_at'])

    async def test_foreign_before_answer_refuses_and_after_answer_reports_conflict(self):
        row = await self.question()
        foreign = await self.user(row,text='desktop ALPHA',client='desktop-fixture')
        await self.state.async_user(self.thread,self.turn,foreign)
        with self.assertRaises(CommandError):
            await self.answer(row)
        self.agent.rpc.request.assert_not_awaited()
        self.assertEqual((await self.row(row['public_id']))['state'],'stale')

    async def test_foreign_after_accepted_preserves_unknown_business_result(self):
        row = await self.question()
        await self.answer(row)
        row = await self.row(row['public_id'])
        own, foreign = await self.user(row), await self.user(row,text='desktop opposite',client='desktop-fixture')
        await self.state.async_user(self.thread,self.turn,foreign)
        self.assertEqual((await self.row(row['public_id']))['state'],'conflict')
        with self.assertRaisesRegex(ValueError,'merged'):
            await self.engine.complete(self.thread,{**self.native_turn,'status':'completed',
                'items':[*self.native_turn['items'],own,foreign]})
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'],'unknown')

    async def test_changed_question_stales_old_card_and_keeps_original(self):
        row = await self.question()
        await self.emit({**self.item,'questions':[{'title':'changed','options':None}]})
        changed = await self.row(row['public_id'])
        self.assertEqual((changed['state'],changed['revision']),('stale',2))
        self.assertEqual(changed['questions'],row['questions'])
        with self.assertRaises(CommandError):
            await self.answer(changed)
        await self.emit(self.item)
        self.assertEqual((await self.row(row['public_id']))['state'],'stale')

    async def test_multi_answer_exact_keys_and_free_text(self):
        row = await self.question(questions=[{'title':'first','options':['A','B']},{'title':'自由文本','options':None}])
        for text in ['one','{}','{"q1":"A"}','{"q1":"A","q2":"x","q3":"y"}',
                     '{"q1":"A","q2":[]}','{"q1":"A","q2":""}','{"q1":"A","q1":"B","q2":"x"}']:
            with self.subTest(text=text),self.assertRaises(CommandError):
                await self.answer(row,text)
        self.agent.rpc.request.assert_not_awaited()
        await self.answer(row,'{"q1":"B","q2":"中文 自由答案"}')
        self.assertIn('中文 自由答案',(await self.row(row['public_id']))['answer_text'])

    async def test_wrong_target_binding_refuses_without_rpc(self):
        row = await self.question()
        self.sessions[1].binding = replace(self.sessions[1].binding,native_session_id='changed')
        with self.assertRaises(CommandError):
            await self.answer(row)
        self.agent.rpc.request.assert_not_awaited()

    async def test_rpc_ack_unknown_refusal_and_duplicate_never_retries(self):
        row = await self.question()
        self.agent.rpc.request.side_effect = OutcomeUnknown('fixture ACK lost')
        self.assertIn('未知',await self.answer(row))
        with self.assertRaises(CommandError):
            await self.answer(row)
        self.agent.rpc.request.assert_awaited_once()
        saved = await self.row(row['public_id'])
        self.assertEqual(saved['state'],'unknown')
        await self.state.async_user(self.thread,self.turn,await self.user(saved))
        self.assertEqual((await self.row(row['public_id']))['state'],'observed')

    async def test_expiry_monotonic_cannot_be_extended_by_wall_clock(self):
        row = await self.question()
        self.engine.async_questions.clock = lambda:self.engine.async_questions.deadlines[row['public_id']]
        with patch('wx_clawbot.async_questions.time.time',return_value=row['created_at']-10000):
            await self.engine.async_questions.expire()
        self.assertEqual((await self.row(row['public_id']))['state'],'stale')
        self.agent.rpc.request.assert_not_awaited()

    async def test_turn_end_before_rpc_ack_cannot_revive_entry(self):
        row = await self.question()
        async def accepted(*_):
            await self.state.async_close(thread_turn=(self.thread,self.turn),reason='turn_ended')
            return {'turnId':self.turn}
        self.agent.rpc.request.side_effect = accepted
        await self.answer(row)
        saved = await self.row(row['public_id'])
        self.assertEqual(saved['state'],'unknown')
        self.assertIsNotNone(saved['closed_at'])

    async def test_wrong_body_duplicate_client_wrong_turn_not_auxiliary(self):
        row = await self.question()
        await self.answer(row)
        row = await self.row(row['public_id'])
        good = await self.user(row)
        bad = await self.user(row,text='wrong-body')
        original = self.native_turn['items'][0]
        for users,turn in [([original,bad],self.turn),([original,good,good],self.turn),([original,good],'other-turn')]:
            self.assertEqual(await self.state.async_business_users(self.thread,turn,users,self.task),users)
        self.assertEqual(await self.state.async_business_users(self.thread,self.turn,[original,good],self.task),[original])
        other_original = {**original,'clientId':'unrelated-business-client'}
        self.assertEqual(await self.state.async_business_users(self.thread,self.turn,[other_original,good]),[other_original,good])

    async def test_focus_change_keeps_original_answer_target(self):
        row = await self.question()
        await self.command('/focus 1')
        await self.answer(row)
        self.assertEqual(self.agent.rpc.request.await_args.args[1]['threadId'],self.thread)
        self.assertEqual(self.controller.routes.target,self.sessions[0].target)

    async def test_native_refusal_is_final_and_does_not_reopen(self):
        row = await self.question()
        self.agent.rpc.request.side_effect = RpcError(-1,'fixture ended')
        self.assertIn('已拒绝',await self.answer(row))
        self.assertEqual((await self.row(row['public_id']))['state'],'refused')
        with self.assertRaises(CommandError):
            await self.answer(row)
        self.agent.rpc.request.assert_awaited_once()

    async def test_cancel_after_committed_intent_never_calls_native_or_reopens(self):
        row = await self.question()
        committed = asyncio.Event()
        original = self.state.async_intent
        async def hold(*args):
            result = await original(*args)
            committed.set()
            await asyncio.Event().wait()
            return result
        with patch.object(self.state,'async_intent',side_effect=hold):
            job = asyncio.create_task(self.answer(row))
            await committed.wait()
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
        self.agent.rpc.request.assert_not_awaited()
        self.assertEqual((await self.row(row['public_id']))['state'],'unknown')

    async def test_expiry_599_valid_and_600_invalid(self):
        row = await self.question()
        deadline = self.engine.async_questions.deadlines[row['public_id']]
        self.engine.async_questions.clock = lambda:deadline-1
        with patch('wx_clawbot.async_questions.time.time',return_value=row['expires_at']-1):
            await self.engine.async_questions.expire()
        self.assertEqual((await self.row(row['public_id']))['state'],'pending')
        with patch('wx_clawbot.async_questions.time.time',return_value=row['expires_at']):
            await self.engine.async_questions.expire()
        self.assertEqual((await self.row(row['public_id']))['state'],'stale')

    async def test_shared_sync_capacity_refuses_new_async_without_discarding(self):
        def fill():
            self.state.db.executemany('''INSERT INTO interactions VALUES(?,?,'generation','thread','turn',
                'item/tool/requestUserInput','{}','{}',600,'pending',1,1)''',
                [(f'r-fixture-{i}',str(i)) for i in range(256)])
        await self.state._call(fill)
        self.assertIsNone(await self.question())
        self.assertEqual(await self.state.async_budget(),(256,512))

    async def test_restart_pending_is_stale_and_accepted_evidence_survives(self):
        row = await self.question()
        await self.emit({**self.item,'id':'second'})
        second = [r for r in await self.state.async_rows(active=True) if r['public_id']!=row['public_id']][0]
        await self.answer(row)
        saved = await self.row(row['public_id'])
        credentials = self.state.credentials
        await self.state.close()
        self.state = await RuntimeState.open(self.root/'private/runtime.sqlite3',credentials)
        self.addAsyncCleanup(self.state.close)
        self.controller.state = self.state
        self.engine = Execution(self.controller)
        self.assertEqual((await self.row(second['public_id']))['state'],'stale')
        kept = await self.row(row['public_id'])
        self.assertEqual((kept['state'],kept['answer_client']),('accepted',saved['answer_client']))
        with self.assertRaises(CommandError):
            await self.answer(kept)
        self.agent.rpc.request.assert_awaited_once()
        self.queue.add.assert_awaited_once()

    async def test_restart_sending_is_unknown_preserving_exact_intent(self):
        row = await self.question()
        intent = await self.state.async_intent(row['public_id'],self.engine.generation,1,answer_text(row,'BETA'))
        await self.state.native_disconnected()
        saved = await self.row(row['public_id'])
        self.assertEqual(saved['state'],'unknown')
        self.assertEqual(saved['answer_text'],intent['answer_text'])
        self.assertEqual(saved['answer_client'],intent['answer_client'])
        self.agent.rpc.request.assert_not_awaited()

    async def test_cancel_during_native_send_marks_unknown(self):
        row = await self.question()
        sending = asyncio.Event()
        async def hold(*args):
            sending.set()
            await asyncio.Event().wait()
        self.agent.rpc.request.side_effect = hold
        job = asyncio.create_task(self.answer(row))
        await sending.wait()
        job.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await job
        self.assertEqual((await self.row(row['public_id']))['state'],'unknown')
        with self.assertRaises(CommandError):
            await self.answer(row)
        self.agent.rpc.request.assert_awaited_once()

    async def test_desktop_focus_is_not_observation_but_attach_notifies(self):
        await self.select()
        target = self.sessions[1].target
        thread,turn = self.sessions[1].binding.thread_id,'desktop-turn'
        await self.engine.event({'method':'item/started','params':{'threadId':thread,'turnId':turn,
            'item':{'type':'userMessage','clientId':'desktop-client'}}})
        item = {'type':'agentMessage','delivery':'async','id':'desktop-question',
                'questions':[{'title':'desktop question','options':None}]}
        await self.engine.async_questions.register(thread,turn,item)
        self.assertEqual(await self.state.async_rows(active=True),[])
        await self.command('/attach 2')
        await self.engine.async_questions.register(thread,turn,item)
        self.assertEqual(len(await self.state.async_rows(active=True)),1)

    async def test_unrelated_thread_events_never_read_or_register(self):
        row = await self.question()
        await self.engine.event({'method':'item/completed','params':{'threadId':'unsubscribed-project',
            'turnId':'unrelated-turn','item':self.item}})
        self.engine.read_turn.assert_not_awaited()
        self.assertEqual(len(await self.state.async_rows(active=True)),1)

    async def test_foreign_history_after_turn_closed_still_reports_conflict(self):
        row = await self.question()
        await self.answer(row)
        saved = await self.row(row['public_id'])
        await self.state.async_close(thread_turn=(self.thread,self.turn),reason='turn_ended')
        await self.state.async_user(self.thread,self.turn,await self.user(saved,text='late foreign',client='desktop-late'))
        self.assertEqual((await self.row(row['public_id']))['state'],'conflict')

    async def test_same_item_in_two_projects_has_distinct_identity(self):
        from wx_clawbot.controller import target_record
        row = await self.question()
        await self.command('/attach 1')
        session = self.sessions[0]
        desktop = await self.state.external_task(target_record(session),self.turn,native_client_id='desktop-other-project')
        self.engine.turn_tasks[(session.binding.thread_id,self.turn)] = desktop['id']
        await self.engine.async_questions.register(session.binding.thread_id,self.turn,self.item)
        other = (await self.state.async_rows(thread_turn=(session.binding.thread_id,self.turn)))[0]
        self.assertNotEqual(other['public_id'],row['public_id'])
        self.assertNotEqual(other['target']['project_alias'],row['target']['project_alias'])

    async def test_controller_generation_change_rejects_new_input(self):
        row = await self.question()
        self.controller.native_generation += 1
        with self.assertRaises(CommandError):
            await self.answer(row)
        self.agent.rpc.request.assert_not_awaited()

    async def test_raw_event_budget_and_prompt_literal_content(self):
        row = await self.question(questions=[{'title':'中文 `a_b` /focus 1 <x> \\ path','options':None}])
        texts = await self.state._call(lambda:[r[0] for r in self.state.db.execute("SELECT text FROM outbox WHERE kind='async_question'")])
        self.assertIn('/focus 1',''.join(texts))
        self.assertIn('a_b',''.join(texts))
        await self.emit({**self.item,'id':'oversize','text':'x'*(1024*1024+1)})
        self.assertEqual(len(await self.state.async_rows(active=True)),1)

    async def test_native_generation_change_after_intent_is_unknown_not_sent(self):
        row = await self.question()
        original=self.state.async_intent
        async def change(*args):
            result=await original(*args)
            self.controller.native_generation+=1
            return result
        with patch.object(self.state,'async_intent',side_effect=change):
            self.assertIn('未知',await self.answer(row))
        self.agent.rpc.request.assert_not_awaited()
        self.assertEqual((await self.row(row['public_id']))['state'],'unknown')

    async def test_retention_preserves_unknown_and_active_task_answer_evidence(self):
        from wx_clawbot.retention import maintain
        row = await self.question()
        await self.answer(row)
        saved = await self.row(row['public_id'])
        await self.state.async_user(self.thread,self.turn,await self.user(saved))
        await self.state.async_close(thread_turn=(self.thread,self.turn),reason='turn_ended')
        path,credentials = self.state.path,self.state.credentials
        await self.state.close()
        report = maintain(path.parent,credentials,now=time.time()+40*86400)
        self.assertEqual(report['eligible_rows']['closed_async_questions'],0)
        maintain(path.parent,credentials,apply=True,now=time.time()+40*86400)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM async_questions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)

    async def test_explicit_retention_only_removes_closed_observed_terminal_record(self):
        from wx_clawbot.retention import maintain
        row = await self.question()
        await self.answer(row)
        saved = await self.row(row['public_id'])
        own = await self.user(saved)
        await self.engine.complete(self.thread,{**self.native_turn,'status':'completed',
            'items':[*self.native_turn['items'],own,{'type':'agentMessage','text':'final fixture'}]})
        await self.state._call(lambda:self.state.db.execute("UPDATE outbox SET state='accepted'"))
        path,credentials = self.state.path,self.state.credentials
        await self.state.close()
        report = maintain(path.parent,credentials,now=time.time()+40*86400)
        self.assertEqual(report['eligible_rows']['closed_async_questions'],1)
        maintain(path.parent,credentials,apply=True,now=time.time()+40*86400)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM async_questions').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    async def test_shared_bytes_cap_does_not_evict_pending_sync_requests(self):
        params=json.dumps({'x':'x'*(1024*1024-8)},separators=(',',':'))
        self.assertEqual(len(params.encode()),1024*1024)
        def fill():
            self.state.db.executemany('''INSERT INTO interactions VALUES(?,?,'generation','thread','turn',
                'item/tool/requestUserInput',?,'{}',600,'pending',1,1)''',
                [(f'r-large-{i}',str(i),params) for i in range(16)])
        await self.state._call(fill)
        self.assertIsNone(await self.question())
        self.assertEqual((await self.state.async_budget())[0],16)

    async def test_recovery_recognizes_only_own_answer_and_recovers_original_result(self):
        row=await self.question()
        await self.answer(row)
        saved=await self.row(row['public_id'])
        turn={**self.native_turn,'status':'completed','items':[*self.native_turn['items'],await self.user(saved),
            {'type':'agentMessage','text':'recovered fixture result'}]}
        await self.state.task_update(self.task['id'],'unknown',turn_id=self.turn)
        async def turns(*_):
            yield turn
        self.engine.turns=turns
        self.engine.read_turn=AsyncMock(return_value=turn)
        await self.engine.reconcile_results(thread_id=self.thread)
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'],'completed')
        self.queue.add.assert_awaited_once()

    async def test_external_recovery_does_not_adopt_auxiliary_answer_as_business(self):
        await self.select()
        await self.command('/attach 2')
        self.thread,self.turn=self.sessions[1].binding.thread_id,'external-question-turn'
        original={'type':'userMessage','clientId':'external-original'}
        await self.engine.event({'method':'item/started','params':{'threadId':self.thread,'turnId':self.turn,'item':original}})
        external=(await self.state.tasks())[0]
        self.item={'type':'agentMessage','id':'external-item','delivery':'async',
                   'questions':[{'title':'external question','options':None}]}
        self.native_turn={'id':self.turn,'status':'inProgress','items':[original]}
        self.engine.read_turn=AsyncMock(side_effect=lambda *_:self.native_turn)
        await self.emit(self.item)
        row=(await self.state.async_rows(task_id=external['id']))[0]
        await self.answer(row,'actual free note')
        saved=await self.row(row['public_id'])
        self.native_turn={**self.native_turn,'status':'completed','items':[original,await self.user(saved)]}
        await self.state.task_update(external['id'],'unknown')
        await self.engine.reconcile_results(thread_id=self.thread)
        self.assertEqual((await self.state.tasks(task_id=external['id']))['state'],'completed')
        self.assertEqual(len(await self.state.tasks()),1)
        self.queue.add.assert_not_awaited()

    async def test_commit_failure_before_intent_has_no_rpc(self):
        row = await self.question()
        await self.state._call(lambda:self.state.db.execute("""CREATE TRIGGER reject_answer BEFORE UPDATE ON async_questions
            WHEN NEW.state='sending' BEGIN SELECT RAISE(ABORT,'fixture commit refused'); END"""))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.answer(row)
        self.agent.rpc.request.assert_not_awaited()
        self.assertEqual((await self.row(row['public_id']))['state'],'pending')

    async def test_prompt_and_question_atomic_failure(self):
        await self.state._call(lambda:self.state.db.execute("""CREATE TRIGGER reject_card BEFORE INSERT ON outbox
            WHEN NEW.kind='async_question' BEGIN SELECT RAISE(ABORT,'fixture card commit refused'); END"""))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.question()
        self.assertEqual(await self.state.async_rows(active=True),[])

    async def test_status_does_not_claim_task_paused_or_native_resolved(self):
        row = await self.question()
        text = await self.engine.control(parse_command('/status '+self.task['id']))
        self.assertIn('异步待答：1',text)
        self.assertIn(row['public_id'],text)
        self.assertIn('执行中',text)
        for command in ['approve','deny']:
            with self.assertRaises(CommandError):
                await self.engine.control(parse_command('/'+command+' '+row['public_id']))

    async def test_unsupported_version_and_bad_question_only_fixed_notice(self):
        self.agent.server_version = '0.165.0'
        self.assertIsNone(await self.question())
        self.agent.server_version = '0.166.0'
        for qs in [[],[{'title':'','options':None}],[{'title':'x','options':['A','A']}],
                   [{'title':'x','options':[{'label':'A'}]}],[{'title':'x'*7000,'options':None}]]:
            await self.emit({**self.item,'id':'bad-'+str(len(str(qs))),'questions':qs})
        self.assertEqual(await self.state.async_rows(active=True),[])


class AsyncFormatTests(unittest.TestCase):
    def test_twenty_questions_and_combined_native_limit(self):
        item={'type':'agentMessage','delivery':'async','id':'bounded',
              'questions':[{'title':str(i),'options':None} for i in range(20)]}
        questions=questions_from(item)
        self.assertEqual(len(questions),20)
        with self.assertRaises(ValueError):
            questions_from({**item,'questions':item['questions']+[{'title':'extra','options':None}]})
        row={'questions':questions,'public_id':'q-fixture','item_id':'item','question_sha256':'hash'}
        self.assertLess(len(answer_text(row,json.dumps({q['id']:'x'*1500 for q in questions}))),32000)
        with self.assertRaises(ValueError):
            answer_text(row,json.dumps({q['id']:'x'*1600 for q in questions}))
    def test_normal_text_is_not_question_and_input_limits(self):
        with self.assertRaises(ValueError):
            questions_from({'id':'fixture','type':'agentMessage','text':'Question?'})
        row={'questions':[{'id':'q1'}],'public_id':'q-fixture','item_id':'item','question_sha256':'hash'}
        self.assertIn('x'*4000,answer_text(row,'x'*4000))
        with self.assertRaises(ValueError):
            answer_text(row,'x'*4001)


class AsyncMigrationTests(AsyncFixture):
    async def v5(self):
        await self.select()
        await self.command('legacy business task')
        await self.state.queue_reply('legacy-frozen','original frozen reply')
        self.credentials = self.state.credentials
        self.path = self.state.path
        await self.state.close()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE async_questions')
            db.execute('PRAGMA user_version=5')
            db.commit()
        return self.snapshot()

    def snapshot(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as db:
            return {name:db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()
                    for name in schema.V1_COLUMNS|schema.V2_COLUMNS|schema.V3_COLUMNS|schema.V5_COLUMNS}

    async def test_v5_explicit_upgrade_preserves_all_12_tables_and_backup(self):
        before = await self.v5()
        plan = schema.inspect(self.path.parent,self.credentials)
        self.assertEqual(plan['add_tables'],['async_questions'])
        self.assertEqual(self.snapshot(),before)
        report = schema.upgrade(self.path.parent,self.credentials)
        self.assertEqual(report['to_version'],6)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.snapshot(self.path.parent/report['backup']),before)
        self.assertEqual(schema.upgrade(self.path.parent,self.credentials)['status'],'current')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute('SELECT count(*) FROM async_questions').fetchone()[0],0)

    async def test_v5_serve_never_auto_migrates(self):
        before = await self.v5()
        with self.assertRaises(schema.UpgradeRequired):
            await RuntimeState.open(self.path,self.credentials)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse((self.path.parent/'backups').exists())

    async def test_v5_failed_upgrade_rolls_back_new_table_and_preserves_backup(self):
        before = await self.v5()
        original = schema.apply_steps
        def fail(db,credentials):
            original(db,credentials)
            raise sqlite3.OperationalError('fixture failure after DDL')
        with patch.object(schema,'apply_steps',side_effect=fail),self.assertRaises(sqlite3.OperationalError):
            schema.upgrade(self.path.parent,self.credentials)
        self.assertEqual(self.snapshot(),before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(schema.validate(db,self.credentials),5)
