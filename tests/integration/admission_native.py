"""Explicit REC01 owned-terminal smoke, per-process footer only; no WeChat I/O."""

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import sys
import tomllib
import uuid

from wx_clawbot.admission import repository_key
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import load_projects
from wx_clawbot.controller import Controller, target_record
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.identity import UUID
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.process import read_process
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchPending, LaunchRegistry, VisibleStarter, reconcile_launch
from wx_clawbot.launcher import launch_argv
from wx_clawbot.managed import source_digest
from wx_clawbot.output import native_output
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_state import RuntimeState


class FixtureRegistry(LaunchRegistry):
    def command(self, launch_id):
        if not self.load(launch_id).get('rec01_footer_override'):
            return super().command(launch_id)
        return shlex.join([str(Path(sys.executable).absolute()),'-I',str(Path(__file__).resolve()),'launch',
                          '--report-dir',str(self.root.parent),'--launch-id',launch_id])


def launch(args):
    from wx_clawbot.release import verify_active
    verify_active()
    registry=FixtureRegistry(args.report_dir/'launches')
    record=registry.load(args.launch_id)
    if record['phase'] not in {'starting','handshaking'}:
        raise ValueError('Owned launch intent is not active')
    argv=launch_argv(record)
    identity=read_process(os.getpid())
    if identity is None:raise ValueError('Own launcher process identity unavailable')
    write_json(registry.root/(args.launch_id+'.boot.json'),
               {'launch_id':args.launch_id,'pid':identity.pid,'started':identity.started,'tty_device':identity.tty_device})
    # Explicit remote avoids -c disabling implicit daemon reuse. Only the TUI's
    # local footer is overridden; the registered root already has exact trust.
    if record.get('rec01_footer_override'):
        argv=[*argv[:-1],'--remote','unix://'+record['rec01_socket'],
              '-c','tui.status_line='+json.dumps(record['rec01_footer']),argv[-1]]
    os.chdir(record['cwd'])
    os.environ.pop('WX_CLAWBOT_RELEASE_MANIFEST', None)
    os.execv(argv[0],argv)


async def main(args):
    import iterm2
    workspace=Path(__file__).resolve().parents[2]
    report=args.report_dir.absolute()
    if not report.resolve().is_relative_to((workspace/'.tmp').resolve()):
        raise ValueError('Native case must stay in the candidate project .tmp')
    report=private_directory(report)
    path=report/'case.json'
    if args.action=='report':
        case=read_json(path)
        print(json.dumps({'phase':case['phase'],'owned_terminals':len(case.get('fixtures',[])),
                          'wechat_sends':0,'production_ledger_writes':0}));return
    if not args.confirm_dedicated:
        raise ValueError('Explicit owned-fixture confirmation required')
    if args.action=='prepare' and path.exists():raise FileExistsError('Existing launch intent cannot be replayed')
    if args.action!='prepare' and not path.exists():raise ValueError('An owned case is required')
    home=Path.home()/'.codex'
    production=Path.home()/'Library/Application Support/wx-clawbot'
    protected=[home/'config.toml',production/'config.json',production/'credentials.json',
               Path.home()/'Library/LaunchAgents/local.wx-clawbot.plist']
    hashes=lambda:[hashlib.sha256(p.read_bytes()).hexdigest() for p in protected]
    projects=load_projects(production/'config.json')
    project=next(p for p in projects if p.alias=='wx-clawbot')
    config=tomllib.loads((home/'config.toml').read_text())
    if config.get('projects',{}).get(str(project.root),{}).get('trust_level')!='trusted':
        raise ValueError('Exact registered root is not already trusted; no automatic trust change')
    footer=list(config.get('tui',{}).get('status_line',[]))
    override=not any(item in {'thread-id','session-id'} for item in footer)
    if override:footer=['thread-id',*footer]
    host=HostLifecycle();native=None;engine=None;state=None;jobs=[]
    try:
        await host.ensure();host.verified(host.generation)
        socket,executable=await asyncio.to_thread(discover_runtime,home)
        native=await CodexConnection.connect(socket)
        directory=ItermDirectory(lifecycle=host)
        registry=FixtureRegistry(report/'launches')
        if args.action=='prepare':
            app=await iterm2.async_get_app(host.connection)
            case={'phase':'prepared','source_sha256':source_digest(),'protected_hashes':hashes(),
                'runtime_identity':list(native.runtime_identity),'version':native.server_version,'fixtures':[],
                'before_terminal_ids':[s.session_id for w in app.windows for t in w.tabs for s in t.sessions]}
            write_json(path,case)
            creator=ItermWindowStarter(lifecycle=host)
            starter=VisibleStarter(registry,creator)
            for index in range(2):
                launch_id=uuid.uuid4().hex
                record=registry.prepare(launch_id,project,project.root,executable,home,f'{args.title_prefix}-{index+1}-owned')
                record.update(rec01_socket=str(socket),rec01_footer=footer,rec01_footer_override=override);registry.save(record)
                fixture={'launch_id':launch_id,'phase':'launch_intent','cwd':str(project.root)}
                case['fixtures'].append(fixture);case['phase']='starting';write_json(path,case,replace=True)
                await starter.start(launch_id,project,project.root,executable,home,f'{args.title_prefix}-{index+1}-owned')
                record=registry.load(launch_id)
                fixture.update({k:record[k] for k in ('window_id','tab_id','terminal_id')});write_json(path,case,replace=True)
                async with asyncio.timeout(180):
                    while True:
                        try:
                            binding=await reconcile_launch(registry,launch_id,directory,native);break
                        except LaunchPending:await asyncio.sleep(.25)
                fixture.update(thread_id=binding.thread_id,phase='ready')
                write_json(path,case,replace=True)
                print(json.dumps({'owned_fixture_ready':index+1}),flush=True)
            assert hashes()==case['protected_hashes']
            case['phase']='ready';write_json(path,case,replace=True)
            print(json.dumps({'phase':'ready','owned_terminals':2,'global_configuration_writes':0}),flush=True)
        elif args.action=='retire-prepare':
            case=read_json(path)
            if case['phase']!='starting':raise ValueError('Only incomplete owned preparation can be retired')
            app=await iterm2.async_get_app(host.connection)
            for fixture in case['fixtures']:
                boot=read_json(registry.root/(fixture['launch_id']+'.boot.json'))
                session=app.get_session_by_id(fixture.get('terminal_id'))
                if session is None:raise ValueError('Owned endpoint is missing; inspect before retry')
                endpoint=await inspect_terminal(session)
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    raise ValueError('Owned process changed')
                marker='WX-LAUNCH-'+fixture['launch_id']
                page=await native.list_project_threads(Path(fixture['cwd']))
                matches=[t for t in page['data'] if t.get('preview','').startswith(marker)]
                if page.get('nextCursor') or len(matches)!=1:raise ValueError('Own startup nonce is not unique')
                thread=await native.inspect(matches[0]['id'])
                if thread.get('status',{}).get('type')!='idle':raise ValueError('Own handshake is not idle')
                screen=await session.async_get_screen_contents()
                row=screen.line(screen.number_of_lines-2).string.replace('\0',' ')
                visible=set(UUID.findall(row))
                if visible!={thread['id'],thread['sessionId']}:
                    raise ValueError('Own duplicate identity footer does not exactly match the native pair')
                if await NativeQueue(native,thread['id'],Path(fixture['cwd'])).list():raise ValueError('Own queue is not empty')
                history=await native.read_turns(thread['id'],limit=2)
                turns=history['data']
                if history.get('nextCursor') or len(turns)!=1 or turns[0].get('status')!='completed':
                    raise ValueError('Owned handshake contains unexpected or unfinished work')
                if marker not in native_output(turns[0]):raise ValueError('Own handshake output differs')
                fixture.update(thread_id=thread['id'],phase='close_intent');write_json(path,case,replace=True)
                await session.async_close(force=True)
                fixture['phase']='closed';write_json(path,case,replace=True)
            assert hashes()==case['protected_hashes']
            case['phase']='retired_duplicate_footer';write_json(path,case,replace=True)
            print(json.dumps({'phase':case['phase'],'own_terminals_closed':len(case['fixtures']),'global_configuration_writes':0}),flush=True)
        elif args.action=='inspect':
            case=read_json(path)
            app=await iterm2.async_get_app(host.connection)
            results=[]
            for fixture in case['fixtures']:
                receipt=registry.root/(fixture['launch_id']+'.boot.json')
                if not receipt.exists():
                    results.append({'boot_receipt':False});continue
                boot=read_json(receipt)
                session=app.get_session_by_id(fixture.get('terminal_id'))
                if session is None:
                    results.append({'owned_endpoint_present':False});continue
                endpoint=await inspect_terminal(session)
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    results.append({'own_process_unchanged':False});continue
                screen=await session.async_get_screen_contents()
                text='\n'.join(screen.line(i).string.replace('\0',' ') for i in range(screen.number_of_lines))
                text=re.sub(r'/Users/[^\s]+','<local-path>',text)
                text=re.sub(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}','<uuid>',text,flags=re.I)
                results.append({'own_process_unchanged':True,'visible_identity':await directory.current_thread_id(endpoint) is not None,'screen_tail':text[-2400:]})
            print(json.dumps({'findings':results,'wechat_sends':0},ensure_ascii=False),flush=True)
        elif args.action=='run':
            case=read_json(path)
            if case['phase']!='ready' or hashes()!=case['protected_hashes'] or list(native.runtime_identity)!=case['runtime_identity']:
                raise ValueError('Exact ready fixtures, configuration and runtime required; no replay')
            catalog=SessionCatalog(projects,directory,native)
            catalog.managed_threads={f['thread_id'] for f in case['fixtures']}
            found=await catalog.discover()
            owned=[]
            for fixture in case['fixtures']:
                matches=[s for s in found if s.binding.thread_id==fixture['thread_id'] and s.binding.endpoint.terminal_id==fixture['terminal_id']]
                if len(matches)!=1:raise ValueError('Own visible binding not uniquely verified')
                await catalog.require(matches[0].target);owned.append(matches[0])
            a,b=owned
            before=[await native.inspect(s.binding.thread_id) for s in owned]
            state=await RuntimeState.open(report/'isolated/runtime.sqlite3',Credentials('synthetic-bot','synthetic-owner','https://ilinkai.weixin.qq.com/','synthetic'))
            controller=Controller(projects,catalog,state,VisibleStarter(registry,None),executable,home,host=host)
            engine=Execution(controller)
            counter=0;sent=[]
            async def incoming(text):
                nonlocal counter
                counter+=1
                raw={'message_id':counter,'from_user_id':state.credentials.owner_id,'to_user_id':state.credentials.bot_id,
                    'message_type':1,'message_state':2,'seq':counter,'create_time_ms':counter,'context_token':'synthetic',
                    'item_list':[{'type':1,'text_item':{'text':text}}]}
                return (await state.accept_batch({'ret':0,'msgs':[raw]},phase='runtime'))['accepted'][0]
            class FakeApi:
                async def send_text(self,*_,**kwargs):
                    sent.append(kwargs['client_id']);return {'ret':0,'message_id':len(sent)}
            marker_a='REC01-A-'+uuid.uuid4().hex
            prompt_a='只回复 '+marker_a+'。不要调用工具，不读取或修改文件，不运行命令。'
            msg=await incoming(prompt_a)
            target=target_record(a);target['repository']=await repository_key(a.target.cwd,project.root)
            task_a=await state.task_intent(msg.message_id,target,prompt_a)
            case.update(phase='task_a_intent',task_a={'id':task_a['id'],'client_id':task_a['client_id']});write_json(path,case,replace=True)
            await catalog.require(a.target)
            await state.task_update(task_a['id'],'dispatching')
            receipt=await NativeQueue(native,a.binding.thread_id,a.target.cwd).add(prompt_a,task_a['client_id'])
            case.update(phase='task_a_queued',queue_a=receipt['id']);write_json(path,case,replace=True)
            async with asyncio.timeout(180):
                while True:
                    page=await native.rpc.request('thread/turns/list',{'threadId':a.binding.thread_id,'limit':1,'itemsView':'full','sortDirection':'desc'})
                    turns=page['data']
                    if turns and any(i.get('type')=='userMessage' and i.get('clientId')==task_a['client_id'] for i in turns[0]['items']):
                        turn_a=turns[0]
                        if turn_a['status'] in {'completed','failed','interrupted'}:break
                    await asyncio.sleep(.2)
            if turn_a['status']!='completed' or marker_a not in native_output(turn_a):
                raise ValueError('Real A marker did not complete; no retry')
            await state.task_update(task_a['id'],'unknown',queue_id=receipt['id'],turn_id=turn_a['id'])
            external=await state.external_task(target,turn_a['id'],native_client_id=task_a['client_id'])
            await state.task_update(external['id'],'unknown')
            # A valid bridge record plus a conflicting external association form
            # an isolated fixture, not a claim that the native TUI merged input.
            # Recover A's exact result; only the ambiguous external row stays unknown.
            controller.routes.snapshot(tuple(s.target for s in owned))
            controller.routes.focus(b.target,expected=controller.routes.revision)
            marker_b='REC01-B-'+uuid.uuid4().hex
            case.update(phase='task_b_intent',marker_b=marker_b);write_json(path,case,replace=True)
            await controller.prepare(await incoming('只回复 '+marker_b+'。不要调用工具，不读取或修改文件，不运行命令。'))
            waiting=[t for t in await state.tasks(active_only=True) if t['state']=='received']
            if len(waiting)!=1:raise ValueError('New intent was not held before recovery')
            task_b=waiting[0];case.update(phase='recovering',task_b={'id':task_b['id'],'client_id':task_b['client_id']});write_json(path,case,replace=True)
            jobs=[asyncio.create_task(work) for work in (engine.run(),engine.maintain(),Sender(state,FakeApi()).run())]
            async with asyncio.timeout(180):
                while True:
                    for job in jobs:
                        if job.done():job.result()
                    current=await state.tasks(task_id=task_b['id'])
                    if current['state'] in {'completed','failed','interrupted'}:break
                    await asyncio.sleep(.1)
            if current['state']!='completed':raise ValueError('New real task did not complete')
            turn_b=await engine.read_turn(b.binding.thread_id,current['turn_id'])
            assert marker_b in native_output(turn_b)
            for turn in (turn_a,turn_b):
                assert not any(i.get('type') in {'commandExecution','fileChange','mcpToolCall','dynamicToolCall','webSearch'} for i in turn['items'])
            assert (await state.tasks(task_id=task_a['id']))['state']=='completed'
            assert (await state.tasks(task_id=external['id']))['state']=='unknown'
            for old in (task_a,external):
                assert (await state.occupancy_snapshot(task_id=old['id']))[0]['occupancy']['state']=='released'
            after=[await native.inspect(s.binding.thread_id) for s in owned]
            assert all(all(old.get(k)==new.get(k) for k in ('model','modelProvider','cwd','sessionId')) for old,new in zip(before,after))
            assert hashes()==case['protected_hashes'] and source_digest()==case['source_sha256']
            assert len(sent)==len(set(sent))
            evidence={'passed':True,'runtime_version':native.server_version,'source_sha256':source_digest(),
                'actual_sdk_binding_verified':True,'owned_terminals':2,'real_tasks_completed':2,
                'unknown_fixture_results_preserved':1,'released_unknown_holds':1,'normal_result_recovered':True,'new_intent_submitted_once':True,
                'global_configuration_unchanged':True,'model_provider_unchanged':True,'task_tools':0,
                'wechat_sends':0,'production_ledger_writes':0,'historical_native_task_replays':0}
            case.update(phase='verified',proof=evidence);write_json(path,case,replace=True)
            (report/'proof.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence),flush=True)
        elif args.action=='cleanup':
            case=read_json(path)
            if case['phase']!='verified':raise ValueError('Only verified completed owned fixtures may close')
            app=await iterm2.async_get_app(host.connection)
            for fixture in case['fixtures']:
                boot=read_json(registry.root/(fixture['launch_id']+'.boot.json'))
                session=app.get_session_by_id(fixture['terminal_id'])
                if session is None:raise ValueError('Own endpoint missing; inspect instead of retry')
                endpoint=await inspect_terminal(session)
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    raise ValueError('Own endpoint process changed')
                if await directory.current_thread_id(endpoint)!=fixture['thread_id']:
                    raise ValueError('Own current thread changed')
                if (await native.inspect(fixture['thread_id'])).get('status',{}).get('type')!='idle':
                    raise ValueError('Own thread is not idle')
                if await NativeQueue(native,fixture['thread_id'],Path(fixture['cwd'])).list():
                    raise ValueError('Own queue is not empty')
                fixture['phase']='close_intent';write_json(path,case,replace=True)
                await session.async_close(force=True)
                fixture['phase']='closed';write_json(path,case,replace=True)
            case['phase']='cleaned';write_json(path,case,replace=True)
            print(json.dumps({'phase':'cleaned','own_terminals_closed':2,'user_terminal_inputs':0,'global_configuration_writes':0}),flush=True)
    finally:
        for job in jobs:job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
        if engine is not None:await engine.close()
        if state is not None:await state.close()
        if native is not None:await native.close()
        await host.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','run','cleanup','report','launch','inspect','retire-prepare'))
    parser.add_argument('--report-dir',required=True,type=Path)
    parser.add_argument('--confirm-dedicated',action='store_true')
    parser.add_argument('--launch-id')
    parser.add_argument('--title-prefix',default='REC01')
    args=parser.parse_args()
    if args.action=='launch':launch(args)
    else:asyncio.run(main(args))
