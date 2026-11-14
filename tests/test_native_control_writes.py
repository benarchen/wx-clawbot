"""Setting writes use exact bound targets, observed confirmations and no replay."""

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from wx_clawbot.agents.rpc import OutcomeUnknown, RpcError
from wx_clawbot.commands import CommandError, parse_command
from wx_clawbot.config import Project
from wx_clawbot.native_controls import NativeControls
from wx_clawbot.routing import Target


def catalog():
    return {'data':[{'model':name,'displayName':name,
        'supportedReasoningEfforts':[{'reasoningEffort':'medium'},{'reasoningEffort':'high'}],
        'serviceTiers':[{'id':'fixture-priority','name':'Fast'}],'defaultServiceTier':None,
        'defaultReasoningEffort':'medium'}
        for name in ('old','new')]}


class WriteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        base=Path(__file__).resolve().parents[1]/'.tmp/native-control-write-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cwd=self.root/'project';self.cwd.mkdir()
        self.target=Target('s-owned','fixture',self.cwd)
        self.settings={'model':'old','modelProvider':'provider','reasoningEffort':'high','serviceTier':'default'}
        self.session=SimpleNamespace(target=self.target,binding=SimpleNamespace(thread_id='owned',native_session_id='native-owned'))
        self.state=SimpleNamespace(path=self.root/'private/runtime.sqlite3',tasks=AsyncMock(return_value=[]),
                                  interaction_rows=AsyncMock(return_value=[]),async_rows=AsyncMock(return_value=[]),
                                  admission_budget=AsyncMock(return_value={'allowed':True}))
        self.native=SimpleNamespace(server_version='0.167.0',runtime_identity=(1,2),
            inspect=AsyncMock(return_value={'status':{'type':'idle'},'canAcceptDirectInput':True}),
            read_settings=AsyncMock(side_effect=lambda *a:self.settings.copy()))
        self.routes=SimpleNamespace(revision=1,target=self.target,projects={'fixture':Project('fixture',self.cwd)})
        self.controller=SimpleNamespace(retired=False,selection_pending=0,routes=self.routes,task_reservations={},
            subscriptions=SimpleNamespace(event_session=Mock(),roles={'s-owned':{'route'}}))
        self.catalog=SimpleNamespace(discover=AsyncMock(),require=AsyncMock(return_value=self.session),sessions={'s-owned':self.session})
        self.queue=SimpleNamespace(list=AsyncMock(return_value=[]))
        def generation(expected=None):
            value=(1,self.native.runtime_identity)
            if self.native.runtime_identity is None or expected is not None and value!=expected:
                raise CommandError('generation changed')
            return value
        self.engine=SimpleNamespace(state=self.state,controller=self.controller,native=self.native,catalog=self.catalog,
                                    verified_native=generation,admission_gate=asyncio.Lock(),queue=Mock(return_value=self.queue))
        self.controller.catalog=self.catalog
        self.controls=NativeControls(self.engine);self.controls.confirm_seconds=.03
        self.mutations=[];self.mode='normal'
        async def request(method,params):
            if method=='model/list':return catalog()
            self.assertEqual(method,'thread/settings/update');self.assertEqual(params['threadId'],'owned')
            self.mutations.append(params.copy())
            if self.mode=='reject':raise RpcError(-1,'PRIVATE ERROR BODY')
            for field,value in params.items():
                if field=='threadId' or self.mode=='partial' and field=='effort':continue
                key='reasoningEffort' if field=='effort' else field
                self.settings[key]=value
            if self.mode=='timeout':raise OutcomeUnknown('PRIVATE NATIVE BODY')
            if self.mode=='provider-change':self.settings['modelProvider']='different'
            if self.mode=='missing-event':return {}
            self.emit('wrong' if self.mode=='wrong-thread' else 'owned')
            if self.mode=='conflict':
                self.settings['model']='conflicting';self.emit()
            if self.mode=='turn-start':self.controls.event('turn/started',{'threadId':'owned','turn':{'id':'desktop'}})
            if self.mode=='generation':self.native.runtime_identity=(3,4)
            if self.mode=='selection':self.routes.revision=2
            return {}
        self.native.rpc=SimpleNamespace(request=AsyncMock(side_effect=request))
        self.key_patch=patch('wx_clawbot.native_controls.repository_key',new=AsyncMock(return_value='repository'))
        self.key_patch.start();self.addCleanup(self.key_patch.stop)

    def emit(self,thread='owned'):
        value=dict(self.settings,cwd=str(self.cwd));value['effort']=value.pop('reasoningEffort')
        self.controls.event('thread/settings/updated',{'threadId':thread,'threadSettings':value})

    async def execute(self,text,message='message'):
        return await self.controls.execute(parse_command(text),self.target,self.routes.revision,message_id=message)

    async def test_model_pair_and_fast_preserve_other_fields(self):
        for i,(text,updates,changes) in enumerate((
                ('/model set new high',{'model':'new','effort':'high'},{'model':'new','reasoningEffort':'high'}),
                ('/model set new medium',{'model':'new','effort':'medium'},{'model':'new','reasoningEffort':'medium'}),
                ('/fast on',{'serviceTier':'fixture-priority'},{'serviceTier':'fixture-priority'}),
                ('/fast off',{'serviceTier':'default'},{'serviceTier':'default'}))):
            before=self.settings.copy();reply=await self.execute(text,str(i))
            self.assertIn('已确认',reply);self.assertIn('桌面并发',reply)
            self.assertEqual(self.mutations[-1],{'threadId':'owned',**updates})
            self.assertEqual(self.settings,dict(before,**changes))
        self.assertIn('仅确认设置，不代表实际提速或计费',reply)

    async def test_omitted_effort_uses_selected_model_default_even_for_current_model(self):
        reply=await self.execute('/model set old')
        self.assertIn('模型默认',reply)
        self.assertEqual(self.mutations,[{'threadId':'owned','model':'old','effort':'medium'}])
        self.assertEqual(self.settings['reasoningEffort'],'medium')
        self.assertEqual(self.controls.journal().read('message')['reasoning_source'],'model_default')

    async def test_0169_pair_update_queries_original_provider_and_keeps_tier(self):
        self.native.server_version='0.169.0'
        reply=await self.execute('/model set new medium')
        self.assertIn('已确认',reply)
        self.assertEqual(self.native.rpc.request.call_args_list[0].args,
            ('model/list',{'limit':100,'includeHidden':False,'modelProvider':'provider'}))
        self.assertEqual(self.mutations,[{'threadId':'owned','model':'new','effort':'medium'}])
        self.assertEqual(self.settings['serviceTier'],'default')
        self.assertEqual(self.settings['modelProvider'],'provider')

    async def test_missing_or_unsupported_default_requires_explicit_effort(self):
        for value in (None,'ultra'):
            rows=catalog()
            if value is None:rows['data'][1].pop('defaultReasoningEffort')
            else:rows['data'][1]['defaultReasoningEffort']=value
            with patch(__name__+'.catalog',return_value=rows):
                with self.assertRaises(CommandError):await self.execute('/model set new',str(value))
                self.assertFalse(self.mutations)
        with patch(__name__+'.catalog',return_value=rows):
            self.assertIn('已确认',await self.execute('/model set new high','explicit'))

    async def test_partial_pair_application_is_unknown_without_rollback_or_replay(self):
        self.mode='partial'
        reply=await self.execute('/model set new medium')
        self.assertIn('待核对',reply)
        self.assertEqual(self.settings['model'],'new')
        self.assertEqual(self.settings['reasoningEffort'],'high')
        self.assertEqual(self.controls.journal().read('message')['phase'],'unknown')
        self.assertEqual(await self.execute('/model set new medium'),reply)
        self.assertEqual(len(self.mutations),1)

    async def test_same_value_is_durable_noop_and_duplicate_message_never_sends(self):
        reply=await self.execute('/model set old high')
        self.assertIn('无变更',reply);self.assertFalse(self.mutations)
        self.settings['model']='new'
        self.assertEqual(await self.execute('/model set old high'),reply)
        self.assertFalse(self.mutations)

    async def test_confirmed_and_unknown_restart_return_frozen_receipt_without_rpc(self):
        for mode in ('normal','timeout'):
            self.mode=mode;key=mode
            reply=await self.execute('/model set old medium',key)
            before=len(self.mutations)
            self.controls=NativeControls(self.engine)
            self.assertEqual(await self.execute('/model set old medium',key),reply)
            self.assertEqual(len(self.mutations),before)
            self.settings['reasoningEffort']='high'

    async def test_missing_or_wrong_event_cannot_confirm_ack(self):
        for mode in ('missing-event','wrong-thread','conflict','turn-start','provider-change'):
            self.mode=mode;self.settings.update(model='old',modelProvider='provider')
            reply=await self.execute('/model set new high',mode)
            self.assertIn('待核对',reply)
            self.assertEqual(self.controls.journal().read(mode)['phase'],'unknown')
            self.assertNotIn('PRIVATE',reply)

    async def test_selection_or_generation_change_after_send_never_replays(self):
        for mode in ('selection','generation'):
            self.routes.revision=1;self.native.runtime_identity=(1,2);self.settings['model']='old';self.mode=mode
            reply=await self.execute('/model set new high',mode)
            self.assertIn('待核对',reply)
        self.assertEqual(len(self.mutations),2)

    async def test_native_rejection_needs_unchanged_readback(self):
        self.mode='reject';reply=await self.execute('/model set new high')
        self.assertIn('原生拒绝',reply);self.assertNotIn('PRIVATE',reply)
        self.assertEqual(self.controls.journal().read('message')['phase'],'rejected')

    async def test_busy_queue_received_occupancy_and_interactions_refuse_before_send(self):
        for mode in ('active','queue','received','task','interaction','async'):
            self.native.inspect.return_value={'status':{'type':'idle'},'canAcceptDirectInput':True}
            self.queue.list.return_value=[];self.controller.task_reservations={}
            self.state.tasks.return_value=[];self.state.interaction_rows.return_value=[];self.state.async_rows.return_value=[]
            record={'project_alias':'fixture','cwd':str(self.cwd),'thread_id':'owned'}
            if mode=='active':self.native.inspect.return_value={'status':{'type':'active'},'canAcceptDirectInput':True}
            if mode=='queue':self.queue.list.return_value=[{'id':'q'}]
            if mode=='received':self.controller.task_reservations[object()]=self.target
            if mode=='task':self.state.tasks.return_value=[{'target':record}]
            if mode=='interaction':self.state.interaction_rows.return_value=[{'target':record,'state':'pending'}]
            if mode=='async':self.state.async_rows.return_value=[{'target':record}]
            with self.subTest(mode=mode),self.assertRaises(CommandError):await self.execute('/model set new high',mode)
        self.assertFalse(self.mutations)

    async def test_unsupported_model_effort_or_tier_never_sends(self):
        for text in ('/model set nonexistent high','/model set old ultra'):
            with self.assertRaises(CommandError):await self.execute(text,text)
        self.settings['serviceTier']='unknown-tier'
        with self.assertRaises(CommandError):await self.execute('/fast off','tier')
        self.assertFalse(self.mutations)

    async def test_source_reuse_with_different_operation_never_sends_again(self):
        await self.execute('/model set new high')
        with self.assertRaises(CommandError):await self.execute('/fast on')
        self.assertEqual(len(self.mutations),1)

    async def test_pre_send_settings_change_is_rejected_without_overwriting_desktop(self):
        reads=0
        def read(*args):
            nonlocal reads
            reads+=1
            if reads==2:self.settings['reasoningEffort']='medium'
            return self.settings.copy()
        self.native.read_settings.side_effect=read
        self.assertIn('未发送',await self.execute('/model set new high'))
        self.assertFalse(self.mutations);self.assertEqual(self.settings['reasoningEffort'],'medium')
        self.assertEqual(self.controls.journal().read('message')['phase'],'rejected')

    async def test_late_receipt_after_timeout_never_reopens_window_or_changes_result(self):
        self.mode='timeout';reply=await self.execute('/model set new high')
        self.emit();self.assertFalse(self.controls.settings_windows)
        self.assertEqual(await self.execute('/model set new high'),reply)
        self.assertEqual(len(self.mutations),1)

    async def test_busy_other_session_in_same_repository_refuses_write(self):
        other=SimpleNamespace(target=Target('s-other','other',self.cwd),binding=SimpleNamespace(thread_id='other'))
        self.catalog.sessions['s-other']=other
        self.routes.projects['other']=Project('other',self.cwd)
        async def inspect(thread):
            return {'status':{'type':'active' if thread=='other' else 'idle'},'canAcceptDirectInput':True}
        self.native.inspect.side_effect=inspect
        with self.assertRaisesRegex(CommandError,'其他会话忙碌'):await self.execute('/model set new high')
        self.assertFalse(self.mutations)

    async def test_intent_failure_refuses_send_and_terminal_failure_keeps_nonreplay_intent(self):
        with patch('wx_clawbot.control_journal.write_json',side_effect=OSError('PRIVATE DISK')):
            with self.assertRaises(CommandError):await self.execute('/model set new high','before')
        self.assertFalse(self.mutations)
        with patch('wx_clawbot.control_journal.ControlJournal.finish',side_effect=OSError('PRIVATE DISK')):
            with self.assertRaisesRegex(CommandError,'待核对'):await self.execute('/model set new high','after')
        self.assertEqual(self.controls.journal().read('after')['phase'],'intent')
        self.assertIn('待核对',await self.execute('/model set new high','after'))
        self.assertEqual(len(self.mutations),1)
