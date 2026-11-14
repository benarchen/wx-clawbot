"""Real child crashes and a synthetic Unix peer prove setting RPC is not replayed."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from websockets.asyncio.server import unix_serve


CHILD = r'''
import asyncio,json,os,sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.commands import parse_command
from wx_clawbot.config import Project
from wx_clawbot.control_journal import ControlJournal
from wx_clawbot.native_controls import NativeControls
from wx_clawbot.routing import Target
async def main():
 root=Path(sys.argv[1]);native=await CodexConnection.connect(Path(sys.argv[2]));mode=sys.argv[3]
 target=Target('s-owned','fixture',root/'project')
 session=NS(target=target,binding=NS(thread_id='owned',native_session_id='native-owned'))
 state=NS(path=root/'private/runtime.sqlite3',tasks=AsyncMock(return_value=[]),interaction_rows=AsyncMock(return_value=[]),async_rows=AsyncMock(return_value=[]),admission_budget=AsyncMock(return_value={'allowed':True}))
 controller=NS(retired=False,selection_pending=0,task_reservations={},routes=NS(revision=1,target=target,projects={'fixture':Project('fixture',target.cwd)}),
  subscriptions=NS(event_session=Mock(),roles={'s-owned':{'route'}}))
 catalog=NS(discover=AsyncMock(),require=AsyncMock(return_value=session),sessions={'s-owned':session});controller.catalog=catalog
 identity=native.runtime_identity
 def verified(expected=None):
  value=(1,native.runtime_identity)
  if value[1]!=identity or expected is not None and value!=expected:raise ValueError('generation')
  return value
 engine=NS(native=native,state=state,controller=controller,catalog=catalog,verified_native=verified,admission_gate=asyncio.Lock(),queue=lambda thread,cwd:NativeQueue(native,thread,cwd))
 controls=NativeControls(engine)
 async def consume():
  while True:
   event=await native.rpc.next_event();controls.event(event.get('method'),event.get('params'))
 pump=asyncio.create_task(consume())
 finish=ControlJournal.finish
 def crash(self,*a,**k):
  if mode=='after-confirmed':finish(self,*a,**k)
  os._exit(74)
 if mode!='normal':ControlJournal.finish=crash
 try:
  reply=await controls.execute(parse_command('/model set new high'),target,1,message_id='stable-owned-message')
  print(json.dumps({'reply':reply}),flush=True)
 finally:
  pump.cancel();await asyncio.gather(pump,return_exceptions=True);await native.close()
asyncio.run(main())
'''


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        base=Path(__file__).resolve().parents[1]/'.tmp/native-control-process';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'project').mkdir()
        sockets=tempfile.TemporaryDirectory(prefix='wx-ctrl-',dir='/tmp');self.addCleanup(sockets.cleanup)
        self.socket=Path(sockets.name)/'rpc.sock';self.writes=[];self.methods=[]
        self.settings={'model':'old','modelProvider':'provider','reasoningEffort':'high','serviceTier':'default'}
        self.thread={'id':'owned','sessionId':'native-owned','cwd':str(self.root/'project'),
                     'status':{'type':'idle'},'canAcceptDirectInput':True}
        async def peer(ws):
            async for raw in ws:
                value=json.loads(raw);method=value['method'];self.methods.append(method)
                if method=='initialized':continue
                if method=='initialize':result={'userAgent':'fixture/0.167.0','platformFamily':'unix','platformOs':'macos','codexHome':'/fixture'}
                elif method=='model/list':result={'data':[{'model':name,'supportedReasoningEfforts':[{'reasoningEffort':'high'}]} for name in ('old','new')]}
                elif method=='thread/read':result={'thread':dict(self.thread,**{k:v for k,v in self.settings.items() if k!='serviceTier'})}
                elif method=='thread/loaded/list':result={'data':['owned'],'nextCursor':None}
                elif method=='thread/resume':
                    self.assertEqual(set(value['params']),{'threadId','excludeTurns'})
                    result=dict(self.settings,cwd=self.thread['cwd'],thread=dict(self.thread,**{k:v for k,v in self.settings.items() if k!='serviceTier'}))
                elif method=='thread/queue/list':result={'data':[],'nextCursor':None}
                elif method=='thread/settings/update':
                    self.writes.append(value['params']);self.settings.update(model=value['params']['model'],reasoningEffort=value['params']['effort'])
                    sample=dict(self.settings,cwd=self.thread['cwd']);sample['effort']=sample.pop('reasoningEffort')
                    await ws.send(json.dumps({'method':'thread/settings/updated','params':{'threadId':'owned','threadSettings':sample}}))
                    result={}
                else:raise AssertionError(method)
                await ws.send(json.dumps({'id':value['id'],'result':result}))
        self.server=await unix_serve(peer,self.socket);os.chmod(self.socket,0o600)
        self.addAsyncCleanup(self.close_server)

    async def close_server(self):
        self.server.close();await self.server.wait_closed()

    async def child(self,mode):
        process=await asyncio.create_subprocess_exec(sys.executable,'-I','-c',CHILD,str(self.root),str(self.socket),mode,
                                                    stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            stdout,stderr=await asyncio.wait_for(process.communicate(),15)
        except BaseException:
            if process.returncode is None:process.kill()
            await process.wait();raise
        return process.returncode,stdout,stderr

    async def test_crash_after_wire_ack_restart_does_not_repeat_rpc(self):
        code,_,error=await self.child('after-ack');self.assertEqual(code,74,error)
        self.assertEqual(self.writes,[{'threadId':'owned','model':'new','effort':'high'}])
        code,stdout,error=await self.child('normal');self.assertEqual(code,0,error)
        self.assertIn('待核对',json.loads(stdout)['reply']);self.assertEqual(len(self.writes),1)

    async def test_crash_after_durable_confirmation_recovers_frozen_reply_without_rpc(self):
        code,_,error=await self.child('after-confirmed');self.assertEqual(code,74,error)
        path=next((self.root/'private/native-controls').glob('*.json'));frozen=json.loads(path.read_text())
        self.assertEqual(frozen['phase'],'confirmed')
        code,stdout,error=await self.child('normal');self.assertEqual(code,0,error)
        self.assertEqual(json.loads(stdout)['reply'],frozen['reply']);self.assertEqual(len(self.writes),1)
