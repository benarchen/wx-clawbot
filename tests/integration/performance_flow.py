"""Explicit offline Unix peer + actual bridge chain and 120-second soak. Zero external I/O."""
import argparse
import asyncio
import gc
import json
from pathlib import Path
import resource
import tempfile
import time
import tracemalloc
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from websockets.asyncio.server import unix_serve
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.catalog import CatalogSession
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.visible import LaunchRegistry
from wx_clawbot.interactions import QUESTION
from wx_clawbot.routing import Target
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.service import poll
from performance import output_path, source_hash, PROJECT


async def until(check, jobs, timeout=15):
    async with asyncio.timeout(timeout):
        while not await check():
            for job in jobs:
                if job.done(): job.result()
            await asyncio.sleep(.005)


async def main(args):
    with tempfile.TemporaryDirectory(prefix='flow-',dir=args.output.parent) as tmp, \
            tempfile.TemporaryDirectory(prefix='wx-flow-',dir='/tmp') as socktmp:
        root=Path(tmp)
        projects=tuple(Project(alias,root/alias) for alias in ('one','two'))
        for project in projects: project.root.mkdir()
        state=await RuntimeState.open(root/'state/runtime.sqlite3',Credentials('synthetic-bot','synthetic-owner','https://ilinkai.weixin.qq.com/','synthetic'))
        threads={f'thread-{p.alias}': {'id':f'thread-{p.alias}','sessionId':f'native-{p.alias}',
            'cwd':str(p.root),'status':{'type':'idle'},'model':'synthetic','modelProvider':'synthetic'} for p in projects}
        turns={}; clients={}; connections=[]; responses=[]
        async def peer(ws):
            connections.append(ws)
            async for raw in ws:
                message=json.loads(raw)
                if 'method' not in message:
                    responses.append(message['id'])
                    await ws.send(json.dumps({'method':'serverRequest/resolved','params':{'threadId':'thread-one','requestId':message['id']}}))
                    continue
                method=message['method']; params=message.get('params',{})
                if method=='initialized': continue
                if method=='initialize':
                    value={'userAgent':'synthetic/0.166.0','platformFamily':'unix','platformOs':'macos','codexHome':str(root)}
                elif method in ('thread/read','thread/resume'):
                    value={'thread':threads[params['threadId']]}
                elif method=='thread/unsubscribe': value={'status':'unsubscribed'}
                elif method=='thread/queue/list': value={'data':[],'nextCursor':None}
                elif method=='thread/queue/add':
                    tid=params['threadId']; client=params['clientUserMessageId']; turn='turn-'+client
                    clients[client]=turn
                    turns[tid]={'id':turn,'status':'inProgress','items':[{'type':'userMessage','clientId':client}]}
                    threads[tid]['status']={'type':'active'}
                    value={'queuedSubmission':{'id':'queue-'+client,'clientUserMessageId':client}}
                    await ws.send(json.dumps({'id':message['id'],'result':value}))
                    await ws.send(json.dumps({'method':'item/started','params':{'threadId':tid,'turnId':turn,'item':turns[tid]['items'][0]}}))
                    continue
                elif method=='thread/turns/list': value={'data':[turns[params['threadId']]],'nextCursor':None}
                else: raise AssertionError(method)
                await ws.send(json.dumps({'id':message['id'],'result':value}))
        socket=Path(socktmp)/'peer.sock'
        server=await unix_serve(peer,socket)
        socket.chmod(0o600)
        native=await CodexConnection.connect(socket)
        sessions=[CatalogSession(Target('session-'+p.alias,p.alias,p.root),
            SimpleNamespace(thread_id='thread-'+p.alias),'synthetic') for p in projects]
        catalog=SimpleNamespace(agent=native,sessions={s.target.session_id:s for s in sessions},
            managed_threads=set(),unverified=[],discover=AsyncMock(return_value=tuple(sessions)),
            require=AsyncMock(side_effect=lambda target: next(s for s in sessions if s.target==target)))
        controller=Controller(projects,catalog,state,SimpleNamespace(registry=LaunchRegistry(root/'launches')),Path('/synthetic/codex'),root)
        engine=Execution(controller)
        incoming=asyncio.Queue(); received=0; sent=0; claims=0
        class Api:
            async def updates(self,credentials,cursor):
                return {'ret':0,'msgs':[await incoming.get()]}
            async def send_text(self,*args,**kwargs):
                nonlocal sent
                sent+=1
                return {'ret':0,'message_id':sent}
        api=Api()
        async def text(value):
            nonlocal received
            received+=1
            await incoming.put({'message_id':received,'from_user_id':'synthetic-owner','to_user_id':'synthetic-bot',
                'message_type':1,'message_state':2,'seq':received,'create_time_ms':received,
                'context_token':'synthetic-context','item_list':[{'type':1,'text_item':{'text':value}}]})
        async def notify(method,params,identity=None):
            value={'method':method,'params':params}
            if identity is not None:value['id']=identity
            await connections[0].send(json.dumps(value))
        latencies=[]; started={}; event=engine.event
        first_question_overlap=None
        questions_while_result_active=0
        task_a_id=None
        async def traced(value):
            nonlocal first_question_overlap,questions_while_result_active
            await event(value)
            if value['method']==QUESTION:
                overlap=(await state.tasks(task_id=task_a_id))['state']!='completed'
                questions_while_result_active+=int(overlap)
                if first_question_overlap is None:first_question_overlap=overlap
                latencies.append((time.perf_counter()-started[value['id']])*1000)
        engine.event=traced
        jobs=[asyncio.create_task(fn) for fn in (poll(controller,api),Sender(state,api).run(),engine.run(),engine.maintain())]
        async def answer_ready():
            return bool(engine.brokers.get('thread-one') and any(r.state=='pending' for r in engine.brokers['thread-one'].records.values()))
        render_patch=None
        try:
            await text('/sessions')
            await until(lambda: asyncio.sleep(0,result=controller.routes.list is not None),jobs)
            await text('/focus 2')
            await until(lambda:asyncio.sleep(0,result=controller.routes.target==sessions[1].target),jobs)
            await text('/attach 1')
            await until(lambda:asyncio.sleep(0,result=controller.routes.observer==sessions[0].target),jobs)
            await text('synthetic long result')
            async def running():
                return any(t['thread_id']=='thread-two' and t['state']=='running' for t in await state.tasks(active_only=True))
            await until(running,jobs)
            task=next(t for t in await state.tasks(active_only=True) if t['thread_id']=='thread-two')
            task_a_id=task['id']
            turns['thread-two']['status']='completed'
            turns['thread-two']['items'].append({'type':'agentMessage','text':'# x\n'*120000})
            threads['thread-two']['status']={'type':'idle'}
            for i in range(10000):
                await notify('item/agentMessage/delta',{'threadId':'thread-one','delta':'x'})
                if i%100==0:await asyncio.sleep(0)
            if args.control_only:
                # Amplify actual maximum-input CPU work without changing payload.
                # This is an explicit stress injection, not nominal render timing.
                from wx_clawbot import output
                original_render=output._render_process
                async def busy_render(text):
                    for index in range(5):
                        before=time.perf_counter()
                        result=await original_render(text)
                        print(json.dumps({'stress_render':index+1,'seconds':time.perf_counter()-before}),flush=True)
                    return result
                render_patch=patch.object(output,'_render_process',side_effect=busy_render)
                render_patch.start()
            await notify('turn/completed',{'threadId':'thread-two','turn':{'id':turns['thread-two']['id']}})
            for i in range(100):
                identity=f'question-{i}'; started[identity]=time.perf_counter()
                for _ in range(5):await notify('item/agentMessage/delta',{'threadId':'thread-one','delta':'x'})
                await notify(QUESTION,{'threadId':'thread-one','turnId':'question-turn','itemId':identity,
                    'questions':[{'id':'choice','question':'synthetic choice','options':[{'label':'A'},{'label':'B'}]}]},identity)
                await until(answer_ready,jobs)
                record=next(r for r in engine.brokers['thread-one'].records.values() if r.state=='pending')
                await text('/answer '+record.public_id+' A')
                await until(lambda:asyncio.sleep(0,result=record.state=='resolved'),jobs)
            async def completed():return (await state.tasks(task_id=task['id']))['state']=='completed'
            await until(completed,jobs,timeout=120 if args.control_only else 15)
            latency={'samples':len(latencies),'p95_ms':sorted(latencies)[94],'max_ms':max(latencies)}
            args.output.with_suffix('.control-metrics.json').write_text(json.dumps({
                'latency':latency,'latencies_ms':latencies,'questions_while_result_active':questions_while_result_active,
                'first_question_overlap':first_question_overlap},indent=2))
            assert latency['p95_ms']<=250 and latency['max_ms']<=1000
            assert native.rpc.failure is None and len(responses)==100
            if args.control_only:
                assert questions_while_result_active==100,'All controls must overlap result work, not be idle samples'
                result={'scope':'Unix peer actual maximum-result/control overlap, no external I/O',
                    'source_sha256':source_hash(PROJECT),'question_latency':latency,
                    'first_question_before_a_completed':first_question_overlap,
                    'questions_while_result_active':questions_while_result_active,'maximum_render_cpu_repetitions':5,
                    'responses_exactly_once':len(responses)==len(set(responses))==100,'passed':True}
                args.output.write_text(json.dumps(result,indent=2))
                print(json.dumps(result,indent=2),flush=True)
                return
            # Only the performance phase above uses maximum output. Soak runs an
            # equal steady workload; samples do not include retained raw messages.
            tracemalloc.start()
            memory=[]; end=time.monotonic()+args.seconds; last_sample=0
            while time.monotonic()<end:
                await text('/status')
                for _ in range(20):await notify('item/agentMessage/delta',{'threadId':'thread-one','delta':'x'})
                if time.monotonic()-last_sample>=10:
                    await engine.prune_memory();gc.collect()
                    memory.append({'at':time.monotonic(),'python_bytes':tracemalloc.get_traced_memory()[0]})
                    last_sample=time.monotonic()
                for job in jobs:
                    if job.done():job.result()
                await asyncio.sleep(.25)
            async def drained():
                return (await state.delivery_counts()).get('pending',0)==0
            await until(drained,jobs)
            await engine.prune_memory();gc.collect()
            ending=tracemalloc.get_traced_memory()[0]
            assert ending<=max(memory[0]['python_bytes']*1.1,memory[0]['python_bytes']+8*1024*1024)
            counts=await state.delivery_counts()
            claim=state.claim_reply
            async def counted():
                nonlocal claims
                claims+=1
                return await claim()
            state.claim_reply=counted
            await asyncio.sleep(60)
            assert claims<=14,claims
            result={'scope':'local Unix synthetic peer, actual poll/Execution/ledger/Sender; no external messages',
                'source_sha256':source_hash(PROJECT),
                'first_question_before_a_completed':first_question_overlap,
                'question_latency':latency,'responses_exactly_once':len(responses)==len(set(responses))==100,
                'native_failure':native.rpc.failure is not None,'soak_seconds':args.seconds,
                'memory_samples':memory,'ending_python_bytes':ending,'idle_60_seconds_claims':claims,
                'delivery_counts':counts,'input_messages':received,'fake_api_calls':sent,
                'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'passed':True}
            args.output.write_text(json.dumps(result,indent=2))
            print(json.dumps(result,indent=2),flush=True)
        finally:
            tracemalloc.stop()
            for job in jobs:job.cancel()
            await asyncio.gather(*jobs,return_exceptions=True)
            await engine.close();await native.close();await state.close()
            if render_patch is not None:render_patch.stop()
            server.close();await server.wait_closed()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=output_path)
    parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--control-only',action='store_true')
    args=parser.parse_args()
    if not 120<=args.seconds<=600:raise ValueError('Soak must last 120 to 600 seconds')
    asyncio.run(main(args))
