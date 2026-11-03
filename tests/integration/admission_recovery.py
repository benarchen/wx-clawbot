"""Offline REC01 bridge recovery and soak against a local Unix peer; no external I/O."""

import argparse
import asyncio
import gc
import json
from pathlib import Path
import random
import resource
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from websockets.asyncio.server import unix_serve
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.catalog import CatalogSession
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.commands import parse_command
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.visible import LaunchRegistry
from wx_clawbot.routing import Target
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.service import poll
from wx_clawbot.managed import source_digest
from wx_clawbot.sessions import SessionUnbound


PROJECT = Path(__file__).resolve().parents[2]


def output_path(value):
    path = Path(value).absolute()
    if not path.resolve().is_relative_to((PROJECT/'.tmp').resolve()):
        raise argparse.ArgumentTypeError('Reports must stay in this candidate project .tmp')
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


async def until(check, jobs, timeout=15):
    async with asyncio.timeout(timeout):
        while not await check():
            for job in jobs:
                if job.done():
                    job.result()
            await asyncio.sleep(.01)


async def main(args):
    source_before=source_digest()
    rng = random.Random(20261103)
    with tempfile.TemporaryDirectory(prefix='rec01-',dir=args.output.parent) as temp, \
            tempfile.TemporaryDirectory(prefix='wx-rec01-',dir='/tmp') as socktemp:
        root=Path(temp)
        project=Project('fixture',root/'project');project.root.mkdir()
        credentials=Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','synthetic')
        state=await RuntimeState.open(root/'private/runtime.sqlite3',credentials)
        thread=lambda identity:{'id':identity,'sessionId':'native-'+identity,'cwd':str(project.root),
            'status':{'type':'idle'},'model':'synthetic','modelProvider':'synthetic'}
        threads={identity:thread(identity) for identity in ('thread-old','thread-new')}
        histories={'thread-old':[],'thread-new':[]}
        submitted=[];calls=[];blocked_read=asyncio.Event();read_entered=asyncio.Event()
        async def peer(ws):
            async for raw in ws:
                msg=json.loads(raw)
                method=msg.get('method');params=msg.get('params',{})
                if method=='initialized':continue
                calls.append((method,params.get('threadId')))
                if method=='initialize':
                    result={'userAgent':'synthetic/0.166.0','platformFamily':'unix','platformOs':'macos','codexHome':str(root)}
                elif method in {'thread/read','thread/resume'}:
                    if method=='thread/resume' and params['threadId']=='thread-old':
                        raise AssertionError('Historical thread must never be restored or subscribed')
                    result={'thread':threads[params['threadId']]}
                elif method=='thread/loaded/list':result={'data':list(threads),'nextCursor':None}
                elif method=='thread/unsubscribe':result={'status':'unsubscribed'}
                elif method=='thread/queue/list':result={'data':[],'nextCursor':None}
                elif method=='thread/turns/list':
                    identity=params['threadId']
                    if identity=='thread-old' and not blocked_read.is_set():
                        read_entered.set()
                        await blocked_read.wait()
                    rows=list(reversed(histories[identity]))
                    offset=int(params.get('cursor','0'));limit=params.get('limit',1)
                    result={'data':rows[offset:offset+limit],
                            'nextCursor':str(offset+limit) if offset+limit<len(rows) else None}
                elif method=='thread/queue/add':
                    if params['threadId']!='thread-new':raise AssertionError('Old task was replayed')
                    client=params['clientUserMessageId']
                    if client in submitted:raise AssertionError('Duplicate native submission')
                    submitted.append(client)
                    turn={'id':'turn-'+client,'status':'completed','items':[
                        {'type':'userMessage','clientId':client},
                        {'type':'agentMessage','text':'REC01-NATIVE-END'}]}
                    histories['thread-new'].append(turn)
                    await ws.send(json.dumps({'id':msg['id'],'result':{'queuedSubmission':{'id':'queue-'+client,'clientUserMessageId':client}}}))
                    await ws.send(json.dumps({'method':'item/started','params':{'threadId':'thread-new','turnId':turn['id'],'item':turn['items'][0]}}))
                    await ws.send(json.dumps({'method':'turn/completed','params':{'threadId':'thread-new','turn':{'id':turn['id']}}}))
                    continue
                else:raise AssertionError('Unexpected native method: '+str(method))
                await ws.send(json.dumps({'id':msg['id'],'result':result}))
        socket=Path(socktemp)/'peer.sock'
        server=await unix_serve(peer,socket);socket.chmod(0o600)
        native=await CodexConnection.connect(socket)
        session=CatalogSession(Target('session-new','fixture',project.root,'managed'),SimpleNamespace(thread_id='thread-new'),'REC01 fixture')
        async def require(target):
            if target!=session.target:raise SessionUnbound('Historical endpoint is absent')
            return session
        catalog=SimpleNamespace(agent=native,sessions={session.target.session_id:session},managed_threads=set(),
            unverified=[],discover=AsyncMock(return_value=(session,)),
            require=AsyncMock(side_effect=require))
        controller=Controller((project,),catalog,state,SimpleNamespace(registry=LaunchRegistry(root/'launches')),Path('/fixture/codex'),root)
        engine=Execution(controller)
        incoming=asyncio.Queue();counter=0;sent=[]
        class Api:
            async def updates(self,*_):return {'ret':0,'msgs':[await incoming.get()]}
            async def send_text(self,*_,**kwargs):
                sent.append(kwargs['client_id'])
                return {'ret':0,'message_id':len(sent)}
        def message(text):
            nonlocal counter
            counter+=1
            return {'message_id':counter,'from_user_id':credentials.owner_id,'to_user_id':credentials.bot_id,
                'message_type':1,'message_state':2,'seq':counter,'create_time_ms':counter,'context_token':'synthetic',
                'item_list':[{'type':1,'text_item':{'text':text}}]}
        async def seed_unknown(index):
            raw=message('synthetic historical task')
            batch=await state.accept_batch({'ret':0,'msgs':[raw]},phase='runtime')
            target={'session_id':'session-old','project_alias':'fixture','cwd':str(project.root),'origin':'managed',
                'thread_id':'thread-old','repository':'directory:'+str(project.root)}
            task=await state.task_intent(batch['accepted'][0].message_id,target,'synthetic historical task')
            turn_id='old-turn-'+str(index)
            await state.task_update(task['id'],'unknown',queue_id='old-queue-'+str(index),turn_id=turn_id)
            external=await state.external_task(target,turn_id,native_client_id='desktop-'+str(index))
            await state.task_update(external['id'],'unknown')
            histories['thread-old'].append({'id':turn_id,'status':'failed','items':[
                {'type':'userMessage','clientId':task['client_id']},
                {'type':'userMessage','clientId':'desktop-'+str(index)}]})
            return await state.tasks(task_id=task['id']),await state.tasks(task_id=external['id'])
        original=await seed_unknown(0)
        controller.routes.snapshot((session.target,))
        controller.routes.focus(controller.routes.select(1),expected=controller.routes.revision)
        api=Api();jobs=[asyncio.create_task(work) for work in (poll(controller,api),Sender(state,api).run(),engine.run(),engine.maintain())]
        latencies=[];cycles=0;peak_active=0
        try:
            await incoming.put(message('REC01 initial task'))
            await read_entered.wait()
            async def waiting():return any(t['state']=='received' for t in await state.tasks(active_only=True))
            await until(waiting,jobs)
            for _ in range(20):
                started=time.perf_counter();result=await engine.control(parse_command('/status'))
                latencies.append((time.perf_counter()-started)*1000)
                assert 'received' in result
            blocked_read.set()
            async def completed():return any(t['state']=='completed' for t in await state.tasks())
            await until(completed,jobs)
            assert len(submitted)==1
            for task in original:
                assert (await state.tasks(task_id=task['id']))['state']=='unknown'
            assert (await state.occupancy_counts())['released_unknown']==2
            if args.action=='soak':
                started=time.monotonic()
                while time.monotonic()-started<args.duration:
                    cycles+=1
                    pair=await seed_unknown(cycles)
                    # Exercise late activity after proof and exact revalidation.
                    if rng.random()<.3:
                        await engine.recovery.reconcile(force=True)
                        await state.reactivate_occupancy('thread-old',pair[0]['turn_id'])
                    await incoming.put(message('REC01 soak task '+str(cycles)))
                    peak_active=max(peak_active,len(await state.tasks(active_only=True)))
                    expected=len(submitted)+1
                    await until(lambda:asyncio.sleep(0,result=len(submitted)>=expected),jobs)
                    async def idle():return not await state.tasks(active_only=True)
                    await until(idle,jobs)
                    if cycles%10==0:
                        # The actual recovery transition must preserve released
                        # history rather than restoring ownership from unknown.
                        await state.native_disconnected()
                        assert (await state.occupancy_counts())['released_unknown']==2*(cycles+1)
                    await asyncio.sleep(.05)
            async def drained():return not (await state.delivery_counts()).get('pending',0)
            await until(drained,jobs)
            assert len(sent)==len(set(sent))
            assert not any(method in {'thread/resume','thread/queue/add','turn/start'} and tid=='thread-old' for method,tid in calls)
            assert max(latencies)<1000
            assert source_digest()==source_before,'Candidate source changed during this run'
            result={'action':args.action,'passed':True,'duration_seconds':args.duration if args.action=='soak' else None,
                'seed':20261103,'cycles':cycles,'source_sha256':source_before,'original_unknown_preserved':True,'original_intent_native_submissions':1,
                'native_submissions':len(submitted),'fake_sends':len(sent),'duplicate_client_ids':0,
                'control_p95_ms':sorted(latencies)[18],'control_max_ms':max(latencies),'peak_active_observed':peak_active,
                'historical_mutating_native_calls':0,'wechat_sends':0,'production_ledger_writes':0,
                'occupancy':await state.occupancy_counts(),'native_calls':len(calls),
                'max_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
        finally:
            blocked_read.set()
            for job in jobs:job.cancel()
            await asyncio.gather(*jobs,return_exceptions=True)
            await engine.close();await state.close();await native.close()
            server.close();await server.wait_closed();gc.collect()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('flow','soak'))
    parser.add_argument('--output',required=True,type=output_path)
    parser.add_argument('--duration',type=int,default=120)
    args=parser.parse_args()
    if not 120<=args.duration<=300:parser.error('Soak duration must be 120..300 seconds')
    asyncio.run(main(args))
