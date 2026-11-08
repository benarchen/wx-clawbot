"""Explicit PRJ01 owned A/B acceptance; synthetic inbox, no real WeChat sends."""

import argparse
import asyncio
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, VisibleStarter
from wx_clawbot.operations import ForegroundInstance
from wx_clawbot.project_control import ProjectServer, project_operation
from wx_clawbot.project_registry import ProjectManager, ProjectStore
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_lifecycle import BridgeRuntime
from wx_clawbot.runtime_state import RuntimeState

spec=importlib.util.spec_from_file_location('owned_fixture',Path(__file__).with_name('native_session_no_footer.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


def prepare(root):
    if (root/'case.json').exists():raise FileExistsError('Fresh owned intent required')
    private_directory(root)
    workspace=root/'projects';workspace.mkdir();(workspace/'prj-a').mkdir()
    private=private_directory(root/'private');store=ProjectStore(private/'config.json',private)
    preview=store.preview(str(workspace));_,payload=store.plan('init',root=str(workspace),apply=True,confirm=preview['confirm'],request='owned-init')
    store.commit(payload);(workspace/'prj-b').mkdir()
    # Keep test rules in the two owned projects, never edit an ancestor's rules.
    for name in ('prj-a','prj-b'):
        (workspace/name/'AGENTS.md').write_text('这是 PRJ01 专用测试目录。只按测试请求回复准确标记，不修改任何文件，不执行业务命令。\n')
    case={'phase':'prepared','protected_hashes':fixture.protected(),'fixtures':[],'inputs':[],
          'wechat_sends':0,'production_writes':0,'checks':{}}
    write_json(root/'case.json',case)
    print(json.dumps({'phase':'prepared','projects':2,'actual_native_actions':0,'wechat_sends':0}))


async def run(root,action):
    import iterm2
    case=read_json(root/'case.json');private=root/'private';workspace=root/'projects'
    if fixture.protected()!=case['protected_hashes']:raise ValueError('Protected configuration changed')
    host=HostLifecycle();native=state=engine=control=instance=None;jobs=[]
    def save():write_json(root/'case.json',case,replace=True)
    try:
        await host.ensure(launch=action=='run',explicit=action=='run');host.verified(host.generation)
        socket,executable=await asyncio.to_thread(discover_runtime,Path.home()/'.codex')
        native=await CodexConnection.connect(socket)
        if action=='run':
            if case['phase']!='prepared':raise ValueError('Existing run intent must not be replayed')
            case.update(phase='running',server_version=native.server_version,runtime=list(native.runtime_identity));save()
            registry=fixture.HiddenRegistry(root/'launches');starter=VisibleStarter(registry,ItermWindowStarter(lifecycle=host))
            for name in ('prj-a','prj-b'):
                project=Project(name,workspace/name);launch_id=uuid.uuid4().hex
                record=registry.prepare(launch_id,project,project.root,executable,Path.home()/'.codex','PRJ01-'+name)
                record['socket']=str(socket);registry.save(record)
                item={'name':name,'launch_id':launch_id,'phase':'intent'};case['fixtures'].append(item);save()
                await starter.start(launch_id,project,project.root,executable,Path.home()/'.codex','PRJ01-'+name)
                launched=registry.load(launch_id);item.update({k:launched[k] for k in ('terminal_id','window_id','tab_id')});save()
                thread=await fixture.bootstrap(native,registry,item)
                app=await iterm2.async_get_app(host.connection);terminal=app.get_session_by_id(item['terminal_id'])
                endpoint=await inspect_terminal(terminal);boot=read_json(registry.root/(launch_id+'.boot.json'))
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    raise ValueError('Owned process differs from boot receipt')
                item.update(thread_id=thread['id'],native_session_id=thread['sessionId'],process=asdict(endpoint.process),phase='ready');save()
            if len({v['window_id'] for v in case['fixtures']})!=1:raise ValueError('Owned terminals must share one window')
            account=Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','synthetic-prj01')
            state=await RuntimeState.open(private/'runtime.sqlite3',account)
            store=ProjectStore(private/'config.json',private)
            runtime=BridgeRuntime(store.config.projects,state,starter,host,socket,executable,Path.home()/'.codex')
            catalog=SessionCatalog(store.config.projects,ItermDirectory(lifecycle=host),native)
            runtime.controller=Controller(store.config.projects,catalog,state,starter,executable,Path.home()/'.codex',host=host)
            runtime.controller.native_generation=1
            manager=ProjectManager(store,runtime);runtime.project_manager=manager
            instance=ForegroundInstance(private);control=ProjectServer(manager,instance);await control.start()
            engine=Execution(runtime.controller);jobs=[asyncio.create_task(engine.run()),asyncio.create_task(engine.maintain())]
            counter=1000
            async def incoming(text):
                nonlocal counter
                counter+=1
                row={'message_id':counter,'from_user_id':'fixture-owner','to_user_id':'fixture-bot','message_type':1,
                     'message_state':2,'create_time_ms':counter,'seq':counter,'context_token':'synthetic',
                     'item_list':[{'type':1,'text_item':{'text':text}}]}
                return (await state.accept_batch({'ret':0,'msgs':[row]},phase='runtime'))['accepted'][0]
            async def command(text):await runtime.prepare(await incoming(text))
            async def select(name):
                await command('/sessions')
                entries=runtime.controller.routes.list.targets
                expected=next(v for v in case['fixtures'] if v['name']==name)
                index=next(i for i,t in enumerate(entries,1) if t.project_alias==name and catalog.sessions[t.session_id].binding.thread_id==expected['thread_id'])
                await command('/focus '+str(index));return runtime.controller.routes.target
            await command('/sessions')
            if {t.project_alias for t in runtime.controller.routes.list.targets}!={'prj-a'}:raise ValueError('Unregistered B discovered')
            target_a=await select('prj-a')
            await project_operation(store.path,private,'add',name='prj-b',request='owned-cli-add')
            if runtime.controller.routes.target!=target_a:raise ValueError('Add changed selected A')
            case['checks']['add_live_preserves_a']=True;save()
            for name in ('prj-a','prj-b'):
                await select(name)
                message=await incoming('只回复这段对话启动时的完整 WX-LAUNCH- 标记。不要调用工具，不读取或修改文件。')
                case['inputs'].append({'message_id':message.message_id,'name':name,'phase':'intent'});save()
                await runtime.prepare(message)
                async with asyncio.timeout(180):
                    while True:
                        rows=await state.tasks()
                        task=next((t for t in rows if t['source_message_id']==message.message_id),None)
                        if task and task['state'] in {'completed','failed','interrupted','unknown'}:break
                        await asyncio.sleep(.5)
                if task['state']!='completed':raise ValueError('Owned business task did not complete')
                owned=next(v for v in case['fixtures'] if v['name']==name)
                if task['thread_id']!=owned['thread_id']:raise ValueError('Task redirected')
                turn=await fixture.completed(native,task['thread_id'],task['client_id'])
                if 'WX-LAUNCH-'+owned['launch_id'] not in fixture.native_output(turn):raise ValueError('Original context lost')
                case['inputs'][-1].update(phase='completed',client_id=task['client_id'],thread_id=task['thread_id'],turn_id=turn['id']);save()
            try:await project_operation(store.path,private,'remove',name='prj-b',request='owned-blocked')
            except ValueError:pass
            else:raise ValueError('Selected B removed')
            await command('/unfocus')
            async with asyncio.timeout(40):
                while await manager.blockers('prj-b'):await asyncio.sleep(.5)
            await command('/project remove prj-b')
            if 'prj-b' in runtime.controller.routes.projects:raise ValueError('B removal not installed')
            case['checks'].update(registered_discovery_only=True,two_original_threads_completed=True,
                selected_remove_blocked=True,remove_live=True,no_redirection=True)
            case['phase']='verified';save()
            print(json.dumps({'phase':case['phase'],'checks':case['checks'],'wechat_sends':0}),flush=True)
        elif action=='cleanup':
            if case['phase'] not in {'verified','cleaned'} or any(v['phase']!='completed' for v in case['inputs']):
                raise ValueError('Unknown test intents must be reconciled before cleanup')
            app=await iterm2.async_get_app(host.connection)
            for item in case['fixtures']:
                terminal=app.get_session_by_id(item['terminal_id'])
                if terminal is None:continue
                endpoint=await inspect_terminal(terminal)
                if endpoint.process is None or asdict(endpoint.process)!={**item['process'],'started':tuple(item['process']['started'])}:
                    raise ValueError('Owned process changed; do not close')
                info=await native.inspect(item['thread_id'])
                if info['status']['type']!='idle' or await NativeQueue(native,item['thread_id'],workspace/item['name']).list():
                    raise ValueError('Owned native work is not idle')
                await terminal.async_close(force=True)
            app=await iterm2.async_get_app(host.connection)
            if any(app.get_session_by_id(item['terminal_id']) is not None for item in case['fixtures']):
                raise ValueError('Owned terminal cleanup not yet confirmed')
            case['phase']='cleaned';save()
            print(json.dumps({'phase':'cleaned','owned_terminals_only':True,'owned_terminals_absent':len(case['fixtures'])}))
        if fixture.protected()!=case['protected_hashes']:raise ValueError('Protected configuration changed')
    finally:
        for job in jobs:job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
        if engine:await engine.close()
        if control:await control.close()
        if instance:instance.close()
        if state:await state.close()
        if native:await native.close()
        await host.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','run','cleanup'))
    parser.add_argument('--case-dir',type=Path,required=True)
    parser.add_argument('--confirm-dedicated',action='store_true')
    args=parser.parse_args();root=args.case_dir.absolute();workspace=Path(__file__).resolve().parents[2]
    if not root.resolve().is_relative_to((workspace/'.tmp/prj01-project-management').resolve()):
        parser.error('Owned PRJ01 case required')
    if args.action=='prepare':prepare(root)
    else:
        if not args.confirm_dedicated:parser.error('Explicit dedicated terminal authorization required')
        asyncio.run(run(root,args.action))
