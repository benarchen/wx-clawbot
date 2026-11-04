"""Explicit PERF01 native smoke in two owned visible terminals; never uses WeChat."""
import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import time
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.config import load_projects
from wx_clawbot.hosts.discovery import ItermDirectory
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter, LaunchPending, reconcile_launch
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.controller import Controller
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.interactions import QUESTION
from wx_clawbot.output import native_output
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.commands import parse_command


def settings(reply):
    keys=('approvalPolicy','approvalsReviewer','sandbox','collaborationMode','activePermissionProfile')
    if not isinstance(reply.get('collaborationMode'),dict) or not isinstance(reply.get('sandbox'),dict):
        raise ValueError('Complete thread settings required')
    return {key:reply.get(key) for key in keys}


async def main(args):
    import iterm2
    workspace=Path.cwd().resolve()
    if not (workspace/'AGENTS.md').exists() or not args.report_dir.resolve().is_relative_to(workspace/'.tmp'):
        raise ValueError('Run only from this project, with a report directory inside its .tmp')
    report=private_directory(args.report_dir.absolute())
    path=report/'native-case.json'
    if args.action=='report':
        case=read_json(path)
        print(json.dumps({'phase':case['phase'],'owned_terminals':len(case.get('fixtures',[])),
                          'wechat_sends':0,'production_ledger_writes':0}))
        return
    if not args.confirm_dedicated:
        raise ValueError('Explicit dedicated fixture confirmation required')
    if args.action=='prepare' and path.exists():
        raise FileExistsError('Existing fixture intent is not replayable')
    if args.action!='prepare' and not path.exists():
        raise ValueError('An existing owned fixture is required before host I/O')
    home=Path.home()/'.codex'
    runtime=Path.home()/'Library/Application Support/wx-clawbot'
    protected=[runtime/'config.json',runtime/'credentials.json',home/'config.toml',
               Path.home()/'Library/LaunchAgents/local.wx-clawbot.plist']
    hashes=lambda:[hashlib.sha256(p.read_bytes()).hexdigest() for p in protected]
    host=HostLifecycle()
    native=None
    try:
        # Explicit dedicated smoke may start an absent host, never restart it.
        await host.ensure(launch=True, explicit=True)
        host.verified(host.generation)
        socket,executable=await asyncio.to_thread(discover_runtime,home)
        native=await CodexConnection.connect(socket)
        directory=ItermDirectory(lifecycle=host)
        if args.action=='run':
            case=read_json(path)
            if case['phase']!='ready' or hashes()!=case['protected_hashes'] or list(native.runtime_identity)!=case['runtime_identity']:
                raise ValueError('Exact ready native fixture/config/runtime required; no replay')
            projects=load_projects(runtime/'config.json')
            catalog=SessionCatalog(projects,directory,native)
            found=await catalog.discover()
            owned=[]
            for fixture in case['fixtures']:
                matches=[s for s in found if s.target.session_id==fixture['session_id'] and s.binding.thread_id==fixture['thread_id']]
                if len(matches)!=1:raise ValueError('Current full fixture identity changed')
                await catalog.require(matches[0].target)
                owned.append(matches[0])
            a,b=owned
            resumed=await native.rpc.request('thread/resume',{'threadId':b.binding.thread_id,'excludeTurns':True})
            original=settings(resumed); plan=copy.deepcopy(original['collaborationMode']);plan['mode']='plan'
            case.update(phase='plan_intent',original_settings=original,applied_collaboration_mode=plan)
            write_json(path,case,replace=True)
            await native.rpc.request('thread/settings/update',{'threadId':b.binding.thread_id,'collaborationMode':plan})
            async with asyncio.timeout(5):
                while True:
                    current=await native.rpc.request('thread/resume',{'threadId':b.binding.thread_id,'excludeTurns':True})
                    if settings(current)=={**original,'collaborationMode':plan}:break
                    await asyncio.sleep(.1)
            synthetic_bot='perf01-synthetic-bot-'+hashlib.sha256(str(report).encode()).hexdigest()[:16]
            state=await RuntimeState.open(report/'isolated-ledger/runtime.sqlite3',Credentials(synthetic_bot,'perf01-synthetic-owner','https://ilinkai.weixin.qq.com/','synthetic'))
            controller=Controller(projects,catalog,state,VisibleStarter(LaunchRegistry(report/'unused-launches'),None),executable,home,host=host)
            engine=Execution(controller)
            counter=0;fake_sends=[];jobs=[];questions=[]
            class FakeApi:
                async def send_text(self,*_,**kwargs):
                    fake_sends.append(kwargs['client_id'])
                    return {'ret':0,'message_id':len(fake_sends)}
            async def command(text):
                nonlocal counter
                counter+=1
                raw={'message_id':counter,'from_user_id':state.credentials.owner_id,'to_user_id':state.credentials.bot_id,
                     'message_type':1,'message_state':2,'seq':counter,'create_time_ms':counter,'context_token':'synthetic',
                     'item_list':[{'type':1,'text_item':{'text':text}}]}
                batch=await state.accept_batch({'ret':0,'msgs':[raw]},phase='runtime')
                await controller.prepare(batch['accepted'][0])
            def healthy():
                for job in jobs:
                    if job.done():job.result()
            async def wait_for(check,timeout=180):
                async with asyncio.timeout(timeout):
                    while not await check():
                        healthy();await asyncio.sleep(.1)
            event=engine.event
            async def tracked(value):
                await event(value)
                if value['method']==QUESTION:questions.append((value['id'],time.monotonic()))
            engine.event=tracked
            try:
                controller.routes.snapshot(tuple(s.target for s in owned))
                jobs=[asyncio.create_task(job) for job in (engine.run(),engine.maintain(),Sender(state,FakeApi()).run())]
                await command('/focus 1');await command('/attach 2')
                prompt_a=('PERF01 只读原生输出验收。不要调用任何工具，不读取或修改任何文件。'
                    '请依次输出 160 行，从 PERF01-LINE-000-abcdefghijkl 到 PERF01-LINE-159-abcdefghijkl，'
                    '中间序号连续，每行一个，不省略；最后单独输出 PERF01-NATIVE-END。')
                case['phase']='task_a_intent';write_json(path,case,replace=True)
                await command(prompt_a)
                tasks=[t for t in await state.tasks() if t['target'].get('source')!='external']
                if len(tasks)!=1 or tasks[0]['state'] not in {'queued','running','waiting_interaction'}:
                    raise ValueError('Native A submission not confirmed; never resubmit')
                task_a=tasks[0];case['task_a']={'id':task_a['id'],'client_id':task_a['client_id']}
                await catalog.require(b.target)
                prompt_b=('PERF01 自动化原生追问验收。这一条只允许调用一次 request_user_input，不调用其他工具，'
                    '不读取或修改文件。立即提出一个问题 id=choice，选项严格为 PERF01_ALPHA 和 PERF01_BETA，'
                    '等待外部测试客户端的真实答复，不自行选择或重复提问；收到后只复述选中标记。')
                client_b='perf01-native-'+uuid.uuid4().hex
                case.update(phase='task_b_intent',client_b=client_b);write_json(path,case,replace=True)
                receipt=await NativeQueue(native,b.binding.thread_id,b.target.cwd).add(prompt_b,client_b)
                case.update(phase='running',queue_b=receipt['id']);write_json(path,case,replace=True)
                await wait_for(lambda:asyncio.sleep(0,result=bool(questions)))
                broker=engine.brokers[b.binding.thread_id]
                pending=[r for r in broker.records.values() if r.state=='pending']
                if len(pending)!=1:raise ValueError('Exactly one unanswered owned native question required')
                request=pending[0]
                qs=request.params['questions']
                if len(qs)!=1 or qs[0]['id']!='choice' or [o['label'] for o in qs[0].get('options',[])]!=['PERF01_ALPHA','PERF01_BETA']:
                    raise ValueError('Native question differs from frozen scope; no automatic answer')
                turn=await engine.read_turn(b.binding.thread_id,request.turn_id)
                users=[i for i in turn['items'] if i.get('type')=='userMessage']
                if len(users)!=1 or users[0].get('clientId')!=client_b:
                    raise ValueError('Question belongs to another native client')
                case.update(phase='answer_intent',request_id=request.public_id,turn_b=request.turn_id)
                write_json(path,case,replace=True)
                await engine.control(parse_command('/answer '+request.public_id+' PERF01_BETA'))
                case['phase']='answered';write_json(path,case,replace=True)
                async def finished():
                    task=await state.tasks(task_id=task_a['id'])
                    records=await state.tasks(native_turn=(b.binding.thread_id,request.turn_id))
                    return task['state']=='completed' and records is not None and records['state']=='completed' and request.state=='resolved'
                await wait_for(finished)
                turn_a=await engine.read_turn(a.binding.thread_id,(await state.tasks(task_id=task_a['id']))['turn_id'])
                turn_b=await engine.read_turn(b.binding.thread_id,request.turn_id)
                output_a=native_output(turn_a); output_b=native_output(turn_b)
                assert 'PERF01-NATIVE-END' in output_a and 'PERF01_BETA' in output_b
                tools=[i.get('type') for turn in (turn_a,turn_b) for i in turn['items'] if i.get('type') not in {'userMessage','agentMessage','reasoning','plan','tool'}]
                forbidden={'commandExecution','fileChange','mcpToolCall','webSearch'}
                assert not any(kind in forbidden for kind in tools)
                if args.verify_controls:
                    controller.routes.focus(b.target, expected=controller.routes.revision)
                    prompt_c=('ENG01 独立控制验收。本次只输出 10000 行文字，'
                        '每行格式为 ENG01-CONTROL-WAIT- 加连续五位序号，从 00000 开始，'
                        '不省略、不总结。不调用工具，不读写文件、不运行命令、不联网、不提问。'
                        '取消或中断后不得重试。')
                    case['phase']='control_task_intent';write_json(path,case,replace=True)
                    await command(prompt_c)
                    candidates=[t for t in await state.tasks(active_only=True) if t['input']==prompt_c]
                    if len(candidates)!=1:raise ValueError('Unique owned control task required')
                    task_c=candidates[0]
                    case['task_c']=task_c['id'];write_json(path,case,replace=True)
                    async def pending_control():
                        current=await state.tasks(task_id=task_c['id'])
                        if current['state'] in {'completed','failed','interrupted','cancelled'}:
                            raise ValueError('Owned control task ended before queue checks; never resubmit')
                        if not current.get('turn_id'):return False
                        turn=await engine.read_turn(b.binding.thread_id,current['turn_id'])
                        return turn['status']=='inProgress'
                    await wait_for(pending_control)
                    control=await state.tasks(task_id=task_c['id'])
                    turn_c=await engine.read_turn(b.binding.thread_id,control['turn_id'])
                    users=[i for i in turn_c['items'] if i.get('type')=='userMessage']
                    if len(users)!=1 or users[0].get('clientId')!=task_c['client_id']:
                        raise ValueError('Control wait is not the exact owned input')
                    prompt_d='ENG01 待取消队列验收。不要调用工具，只回复 ENG01-UNEXPECTED-RUN。'
                    case.update(phase='queued_control_intent',task_c=task_c['id']);write_json(path,case,replace=True)
                    await command(prompt_d)
                    queued=[t for t in await state.tasks(active_only=True) if t['input']==prompt_d]
                    if len(queued)!=1 or queued[0]['state']!='queued':
                        raise ValueError('Owned second input was not confirmed queued; no retry')
                    task_d=queued[0]
                    case.update(phase='cancel_queued_intent',task_d=task_d['id']);write_json(path,case,replace=True)
                    await command('/stop '+task_d['id'])
                    assert (await state.tasks(task_id=task_d['id']))['state']=='cancelled'
                    assert not await NativeQueue(native,b.binding.thread_id,b.target.cwd).list()
                    case['phase']='interrupt_owned_intent';write_json(path,case,replace=True)
                    await command('/stop '+task_c['id'])
                    async def interrupted():
                        return (await state.tasks(task_id=task_c['id']))['state']=='interrupted'
                    await wait_for(interrupted)
                    turn_c=await engine.read_turn(b.binding.thread_id,control['turn_id'])
                    assert turn_c['status']=='interrupted'
                    assert not any(i.get('type') in forbidden for i in turn_c['items'])
                    case.update(queued_cancelled=True,running_interrupted=True)
                await native.rpc.request('thread/settings/update',{'threadId':b.binding.thread_id,'collaborationMode':original['collaborationMode']})
                async with asyncio.timeout(5):
                    while True:
                        restored=await native.rpc.request('thread/resume',{'threadId':b.binding.thread_id,'excludeTurns':True})
                        if settings(restored)==original:break
                        await asyncio.sleep(.1)
                async def drained():return (await state.delivery_counts()).get('pending',0)==0
                await wait_for(drained,15)
                assert hashes()==case['protected_hashes']
                assert len(fake_sends)==len(set(fake_sends))
                case.update(phase='verified',settings_restored=True)
                write_json(path,case,replace=True)
                evidence={'phase':'verified','runtime_version':native.server_version,'owned_terminals':2,
                    'candidate_sdk_identity_verified':True,'original_native_queue':True,
                    'question_calls':len(questions),'resolved':request.state=='resolved','selected_marker':'PERF01_BETA',
                    'real_native_long_result_end':True,'task_a_state':'completed','task_b_state':'completed',
                    'settings_restored':True,'protected_configuration_unchanged':True,
                    'fake_sends':len(fake_sends),'wechat_sends':0,'production_ledger_writes':0}
                if args.verify_controls:
                    evidence.update(queued_cancelled=True,running_interrupted=True,control_task_tools=0)
                (report/'native-proof.json').write_text(json.dumps(evidence,indent=2))
                print(json.dumps(evidence),flush=True)
            finally:
                for job in jobs:job.cancel()
                await asyncio.gather(*jobs,return_exceptions=True)
                await engine.close();await state.close()
        elif args.action=='cleanup':
            from wx_clawbot.hosts.discovery import inspect_terminal
            case=read_json(path)
            if case['phase']!='verified' or not case.get('settings_restored'):
                raise ValueError('Only verified finished fixtures may close automatically')
            registry=LaunchRegistry(report/'launches')
            app=await iterm2.async_get_app(host.connection)
            for fixture in case['fixtures']:
                boot=read_json(registry.root/(fixture['launch_id']+'.boot.json'))
                session=app.get_session_by_id(fixture['terminal_id'])
                if session is None:raise ValueError('Inspect uncertain cleanup before retry')
                endpoint=await inspect_terminal(session)
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    raise ValueError('Own fixture process changed')
                if await directory.current_thread_id(endpoint)!=fixture['thread_id']:
                    raise ValueError('Own terminal current native thread changed')
                if (await native.inspect(fixture['thread_id'])).get('status',{}).get('type')!='idle':
                    raise ValueError('Own fixture still has active native work')
                if await NativeQueue(native,fixture['thread_id'],Path(fixture['cwd'])).list():
                    raise ValueError('Own fixture still has queued work')
                fixture['phase']='close_intent';write_json(path,case,replace=True)
                await session.async_close(force=True)
                fixture['phase']='closed';write_json(path,case,replace=True)
            case['phase']='cleaned';write_json(path,case,replace=True)
            print(json.dumps({'phase':'cleaned','owned_terminals_closed':2,'existing_user_terminal_inputs':0}),flush=True)
        elif args.action=='retire-prepare':
            from wx_clawbot.hosts.discovery import inspect_terminal
            case=read_json(path)
            if case['phase']!='starting':
                raise ValueError('Only the incomplete preparation can be retired')
            registry=LaunchRegistry(report/'launches')
            app=await iterm2.async_get_app(host.connection)
            for fixture in case['fixtures']:
                boot=read_json(registry.root/(fixture['launch_id']+'.boot.json'))
                session=app.get_session_by_id(fixture['terminal_id'])
                if session is None:raise ValueError('Inspect an uncertain close before any retry')
                endpoint=await inspect_terminal(session)
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    raise ValueError('Owned launcher process changed')
                marker='WX-LAUNCH-'+fixture['launch_id']
                page=await native.list_project_threads(Path(fixture['cwd']))
                found=[t for t in page['data'] if t.get('preview','').startswith(marker)]
                if len(found)!=1 or found[0].get('status',{}).get('type')!='idle':
                    raise ValueError('Own handshake is not uniquely idle')
                history=await native.read_turns(found[0]['id'],limit=1)
                turns=history['data']
                if history.get('nextCursor') or len(turns)!=1 or turns[0].get('status')!='completed':
                    raise ValueError('Own handshake has additional or unfinished work')
                answers=[i.get('text','') for i in turns[0]['items'] if i.get('type')=='agentMessage']
                if not any(marker in answer for answer in answers):raise ValueError('Handshake output mismatch')
                fixture['phase']='close_intent';write_json(path,case,replace=True)
                await session.async_close(force=True)
                fixture['phase']='closed';write_json(path,case,replace=True)
            case['phase']='retired_missing_footer'
            write_json(path,case,replace=True)
            print(json.dumps({'phase':case['phase'],'owned_closed':len(case['fixtures']),
                'user_terminal_inputs':0,'task_replays':0}),flush=True)
        elif args.action=='inspect':
            import re
            from wx_clawbot.hosts.discovery import inspect_terminal
            case=read_json(path)
            registry=LaunchRegistry(report/'launches')
            app=await iterm2.async_get_app(host.connection)
            findings=[]
            for fixture in case['fixtures']:
                boot=read_json(registry.root/(fixture['launch_id']+'.boot.json'))
                session=app.get_session_by_id(fixture['terminal_id'])
                if session is None:
                    findings.append({'phase':'terminal_missing'});continue
                endpoint=await inspect_terminal(session)
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    findings.append({'phase':'process_changed'});continue
                screen=await session.async_get_screen_contents()
                lines=[screen.line(i).string.replace('\0',' ') for i in range(screen.number_of_lines)]
                text='\n'.join(lines)
                sanitized=re.sub(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}','<uuid>',text,flags=re.I)
                sanitized=re.sub(r'/Users/[^\s]+','<local-path>',sanitized)
                findings.append({'phase':'owned_screen_read','visible_thread':await directory.current_thread_id(endpoint) is not None,
                    'screen_tail':sanitized[-2000:]})
            print(json.dumps({'findings':findings,'wechat_sends':0},ensure_ascii=False),flush=True)
        elif args.action=='prepare':
            projects=load_projects(runtime/'config.json')
            if {p.alias for p in projects}!={'guixu','wx-clawbot'}:
                raise ValueError('Expected the two explicitly registered test projects')
            app=await iterm2.async_get_app(host.connection)
            case={'phase':'prepared','protected_hashes':hashes(),'fixtures':[],
                  'before_terminal_ids':[s.session_id for w in app.windows for t in w.tabs for s in t.sessions],
                  'runtime_identity':list(native.runtime_identity),'version':native.server_version}
            write_json(path,case)
            registry=LaunchRegistry(report/'launches')
            creator=ItermWindowStarter(lifecycle=host)
            starter=VisibleStarter(registry,creator)
            for index,project in enumerate(sorted(projects,key=lambda p:p.alias)):
                launch_id=uuid.uuid4().hex
                fixture={'launch_id':launch_id,'project_alias':project.alias,'cwd':str(project.root),'phase':'starting'}
                case['fixtures'].append(fixture)
                case['phase']='starting'
                write_json(path,case,replace=True)
                await starter.start(launch_id,project,project.root,executable,home,f'PERF01-{index+1}-owned')
                record=registry.load(launch_id)
                fixture.update({key:record[key] for key in ('window_id','tab_id','terminal_id')})
                write_json(path,case,replace=True)
                async with asyncio.timeout(180):
                    while True:
                        try:
                            binding=await reconcile_launch(registry,launch_id,directory,native)
                            break
                        except LaunchPending:
                            await asyncio.sleep(.5)
                fixture.update(phase='ready',thread_id=binding.thread_id,native_session_id=binding.native_session_id)
                write_json(path,case,replace=True)
            catalog=SessionCatalog(projects,directory,native)
            found=await catalog.discover()
            for fixture in case['fixtures']:
                matches=[s for s in found if s.binding.thread_id==fixture['thread_id']]
                if len(matches)!=1:
                    raise ValueError('Owned terminal identity is not unique')
                await catalog.require(matches[0].target)
                fixture['session_id']=matches[0].target.session_id
            assert len({f['window_id'] for f in case['fixtures']})==1
            assert hashes()==case['protected_hashes']
            case['phase']='ready'
            write_json(path,case,replace=True)
            print(json.dumps({'phase':'ready','owned_windows':1,'owned_terminals':2,
                'runtime_version':native.server_version,'candidate_sdk_identity_verified':True,
                'protected_configuration_unchanged':True,'wechat_sends':0,'production_ledger_writes':0}),flush=True)
        else:
            raise ValueError('Only prepared/report implemented; do not replay an existing case')
    finally:
        if native:
            await native.close()
        await host.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','report','inspect','retire-prepare','run','cleanup'))
    parser.add_argument('--report-dir',required=True,type=Path)
    parser.add_argument('--confirm-dedicated',action='store_true')
    parser.add_argument('--verify-controls',action='store_true',help='Explicit ENG01 owned queue cancellation and interruption')
    asyncio.run(main(parser.parse_args()))
