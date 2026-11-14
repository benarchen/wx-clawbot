"""NCM01 owned protocol probe. Prepare is offline; run needs explicit authorization."""

import argparse
import asyncio
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import shlex
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.agents.rpc import RpcError
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.config import Project
from wx_clawbot.hosts.discovery import inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, VisibleStarter
from wx_clawbot.native_controls import model_catalog, VERSIONS
from wx_clawbot.output import native_output
from wx_clawbot.runtime_discovery import discover_runtime

spec = importlib.util.spec_from_file_location('owned_fixture', Path(__file__).with_name('native_session_no_footer.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


async def settings_request(native, runtime, params):
    """A changed endpoint leaves the caller's durable intent unconfirmed."""
    def validate():
        identity = native.runtime_identity
        if identity is None or tuple(identity) != tuple(runtime):
            raise ValueError('Owned native generation changed around settings request')
    validate()
    result = await native.rpc.request('thread/settings/update', params)
    validate()
    return result


def is_single_sleep(command):
    try:
        parts=shlex.split(command)
        if len(parts)==3 and parts[0] in {'/bin/zsh','/bin/bash'} and parts[1] in {'-c','-lc'}:
            parts=shlex.split(parts[2])
        return parts==['/bin/sleep','30']
    except (TypeError,ValueError):
        return False


def prepare(root):
    private_directory(root)
    if (root/'case.json').exists():
        raise FileExistsError('Fresh owned case required')
    for name in ('ncm-a', 'ncm-b'):
        cwd = root/'projects'/name
        cwd.mkdir(parents=True)
        (cwd/'AGENTS.md').write_text('这是 NCM01 专用测试目录。仅按请求回复标记；若明确要求，只执行一次 /bin/sleep 30。不得读取或修改业务文件，不执行其他任务。\n')
    case = {'phase':'prepared','protected_hashes':fixture.protected(),'fixtures':[],
            'updates':[],'inputs':[],'max_updates':12,'max_inputs':3,
            'test_model':'gpt-6-luna','wechat_sends':0,'production_writes':0}
    write_json(root/'case.json',case)
    print(json.dumps({'phase':'prepared','actual_native_actions':0,'projects':2,
                      'maximum_native_setting_updates':12,'maximum_queue_inputs':3,'startup_handshakes':2}))


async def run(root, action):
    import iterm2
    case=read_json(root/'case.json')
    if action in {'run','bridge-run'} and case['phase']!='prepared':
        raise ValueError('Never replay an existing owned run')
    host=HostLifecycle(); native=None; pump=None
    notifications=[]
    def save():write_json(root/'case.json',case,replace=True)
    def protected():
        if fixture.protected()!=case['protected_hashes']:
            raise ValueError('Protected daily/global configuration changed')
    async def verify(item):
        metadata=await native.inspect(item['thread_id'])
        if metadata['cwd']!=str(root/'projects'/item['name']) or metadata['sessionId']!=item['native_session_id']:
            raise ValueError('Owned native identity changed')
        if list(native.runtime_identity)!=case['runtime'] or not await native.is_loaded(item['thread_id']):
            raise ValueError('Owned native generation or loaded state changed')
        return metadata
    async def snapshot(item):
        await verify(item)
        return await native.read_settings(item['thread_id'],root/'projects'/item['name'])
    async def events():
        while True:
            try: event=await native.rpc.next_event(timeout=.5)
            except TimeoutError:continue
            if event.get('method')=='thread/settings/updated' and any(
                    i.get('thread_id')==event.get('params',{}).get('threadId') for i in case['fixtures']):
                notifications.append(event)
                case['notifications']=notifications.copy();save()
                if len(notifications)>64:raise ValueError('Owned settings event bound exceeded')
    async def update(item, field, value):
        if field not in {'model','effort','serviceTier'} or len(case['updates'])>=12:
            raise ValueError('Authorized update bound exceeded')
        before=await snapshot(item); key='reasoningEffort' if field=='effort' else field
        if key in before and before[key]==value:return
        operation={'thread':item['thread_id'],'field':field,'value':value,'before':before,'phase':'intent'}
        case['updates'].append(operation);save();event_start=len(notifications)
        try:
            operation['ack']=await settings_request(native,case['runtime'],{'threadId':item['thread_id'],field:value})
        except RpcError as exc:
            after=await snapshot(item);operation.update(phase='rejected_verified_unchanged' if after==before else 'unknown',error_code=exc.code,after=after);save()
            if after!=before:raise ValueError('Native rejection left unconfirmed settings')
            return
        operation['phase']='ack_only';save()
        after=await snapshot(item)
        if after.get(key)!=value or key not in after:
            operation.update(phase='unknown',after=after);save();raise ValueError('ACK did not confirm effective settings')
        for untouched in ('model','modelProvider','reasoningEffort','serviceTier'):
            if untouched!=key and after.get(untouched)!=before.get(untouched):
                operation.update(phase='unknown',after=after);save();raise ValueError('Native silently changed an unrequested setting')
        async with asyncio.timeout(10):
            while not any(e['params'].get('threadSettings',{}).get('effort' if field=='effort' else field)==value
                          and e['params']['threadId']==item['thread_id'] for e in notifications[event_start:]):
                await asyncio.sleep(.05)
        if pump.done():
            raise ValueError('Owned native event consumer ended unexpectedly')
        operation.update(phase='confirmed',after=after,settings_event=True);save();protected()
    async def submit(item, text):
        if len(case['inputs'])>=3:raise ValueError('Authorized input bound exceeded')
        await verify(item);client='ncm-probe-'+uuid.uuid4().hex
        intent={'thread':item['thread_id'],'client_id':client,'phase':'intent','text':text}
        intent['expected']=next(v for v in ('NCM01-MODEL','NCM01-BUSY','NCM01-QUEUED') if v in text)
        case['inputs'].append(intent);save()
        result=await NativeQueue(native,item['thread_id'],root/'projects'/item['name']).add(text,client)
        intent.update(phase='queued',queue_id=result['id']);save();return intent
    async def completed(item,intent,busy=False):
        async with asyncio.timeout(180):
            while True:
                page=await native.read_turns(item['thread_id'],limit=20)
                if page.get('nextCursor'):raise ValueError('Owned history bound exceeded')
                matches=[v for v in page['data'] if any(i.get('type')=='userMessage' and i.get('clientId')==intent['client_id'] for i in v.get('items',[]))]
                if len(matches)>1:raise ValueError('Duplicate owned native input')
                if matches and matches[0]['status'] in {'completed','failed','interrupted'}:
                    turn=matches[0];intent.update(phase=turn['status'],turn_id=turn['id']);save()
                    if turn['status']!='completed':raise ValueError('Owned input did not complete')
                    if busy:
                        commands=[v for v in turn.get('items',[]) if v.get('type')=='commandExecution']
                        if len(commands)!=1 or not is_single_sleep(commands[0].get('command','')) or any(v.get('type') in {'mcpToolCall','dynamicToolCall'} for v in turn.get('items',[])):
                            raise ValueError('Owned busy test executed an unexpected command')
                    elif any(v.get('type') in {'commandExecution','mcpToolCall','dynamicToolCall'} for v in turn.get('items',[])):
                        raise ValueError('Owned marker task unexpectedly used tools')
                    intent['output']=native_output(turn);save()
                    if intent['expected'] not in intent['output']:raise ValueError('Owned reply marker missing')
                    return turn
                await asyncio.sleep(.25)
    protected()
    try:
        socket,executable=await asyncio.to_thread(discover_runtime,Path.home()/'.codex');native=await CodexConnection.connect(socket)
        if (native.server_version not in VERSIONS or case.get('expected_server_version',native.server_version)!=native.server_version):raise ValueError('Probe schema not matched')
        launching=action in {'run','bridge-run'}
        await host.ensure(launch=launching,explicit=launching);host.verified(host.generation)
        if action in {'run','bridge-run','continue-reviewed-reset'}:
            if launching:
                case.update(phase='running',runtime=list(native.runtime_identity),server_version=native.server_version);save()
            if (native.server_version not in VERSIONS or case.get('expected_server_version',native.server_version)!=native.server_version):raise ValueError('Probe schema not matched')
            registry=fixture.HiddenRegistry(root/'launches');starter=VisibleStarter(registry,ItermWindowStarter(lifecycle=host))
            for name in (('ncm-a','ncm-b') if launching else ()):
                project=Project(name,root/'projects'/name);launch_id=uuid.uuid4().hex
                record=registry.prepare(launch_id,project,project.root,executable,Path.home()/'.codex','NCM01-'+name)
                record['socket']=str(socket);registry.save(record)
                item={'name':name,'launch_id':launch_id,'phase':'intent'};case['fixtures'].append(item);save()
                await starter.start(launch_id,project,project.root,executable,Path.home()/'.codex','NCM01-'+name)
                launched=registry.load(launch_id);item.update({k:launched[k] for k in ('window_id','tab_id','terminal_id')});save()
                thread=await fixture.bootstrap(native,registry,item)
                app=await iterm2.async_get_app(host.connection);endpoint=await inspect_terminal(app.get_session_by_id(item['terminal_id']));boot=read_json(registry.root/(launch_id+'.boot.json'))
                if endpoint.process is None or endpoint.process.pid!=boot['pid'] or list(endpoint.process.started)!=boot['started']:
                    raise ValueError('Owned process does not match boot')
                item.update(thread_id=thread['id'],native_session_id=thread['sessionId'],process=asdict(endpoint.process),phase='ready');save()
                await native.observe_loaded(item['thread_id'],project.root)
            if len({i['window_id'] for i in case['fixtures']})!=1:raise ValueError('Owned terminals must share one window')
            a,b=case['fixtures']
            if launching:
                original=await snapshot(a);other=await snapshot(b);case.update(initial_a=original,initial_b=other);save()
            else:
                # A reviewed schema normalization is a new checkpoint, never a replay.
                original,other=case['initial_a'],case['initial_b']
                ops=case['updates']
                if (case['phase']!='running' or case['inputs'] or len(ops)!=3
                        or [v['phase'] for v in ops]!=['confirmed','confirmed','unknown']
                        or ops[-1]['field']!='serviceTier' or ops[-1]['value'] is not None
                        or original.get('serviceTier')!='default' or ops[-1]['after'].get('serviceTier')!='default'
                        or await snapshot(a)!=ops[-1]['after'] or await snapshot(b)!=other
                        or any([await NativeQueue(native,i['thread_id'],root/'projects'/i['name']).list() for i in (a,b)])):
                    raise ValueError('Reviewed normalization checkpoint no longer matches')
                for item in (a,b):
                    app=await iterm2.async_get_app(host.connection);terminal=app.get_session_by_id(item['terminal_id'])
                    endpoint=await inspect_terminal(terminal) if terminal else None
                    if endpoint is None or endpoint.process is None or json.loads(json.dumps(asdict(endpoint.process)))!=item['process']:
                        raise ValueError('Reviewed checkpoint lost owned terminal process')
                    if (await verify(item))['status']['type']!='idle':raise ValueError('Reviewed checkpoint not idle')
                ops[-1].update(previous_phase='unknown',phase='normalized_reset_verified',
                               review='Schema null clears override; two fresh owned reads returned original default; original notification unavailable')
                save()
            catalog=await model_catalog(native);selected=catalog.get(original.get('model'));alternate=catalog.get(case['test_model'])
            if selected is None or alternate is None or selected['model']==alternate['model']:
                raise ValueError('Two authorized catalog models are not available')
            efforts=[v for v in ('medium','high') if v in selected['efforts'] and v in alternate['efforts']]
            if len(efforts)<2:raise ValueError('Shared test efforts not advertised')
            effort=next(v for v in efforts if v!=original.get('reasoningEffort'))
            fast=[v['id'] for v in selected['tiers'] or [] if v['name'].casefold()=='fast']
            if len(fast)!=1 or selected['default'] is not None or not selected['default_provided']:
                raise ValueError('Fast on/off mapping cannot be tested safely')
            if action=='bridge-run':
                module_spec=importlib.util.spec_from_file_location('owned_bridge',Path(__file__).with_name('native_control_bridge.py'))
                module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
                await module.run_controls(root,case,native,host,save)
                for intent in case['inputs']:
                    await completed(a,intent,busy=intent['expected']=='NCM01-BRIDGE-BUSY')
                if await snapshot(a)!=original or await snapshot(b)!=other:
                    raise ValueError('Owned settings changed during Controller acceptance')
                protected();case.update(phase='probe_complete',bridge_controller='passed');save()
                print(json.dumps({'phase':'probe_complete','bridge_controller':'passed','settings_requests':len(case['updates']),
                                  'inputs':len(case['inputs']),'wechat_sends':0,'production_writes':0}))
                return
            pump=asyncio.create_task(events())
            if action=='run':await update(a,'effort',effort)
            await update(a,'serviceTier',fast[0]);await update(a,'serviceTier',None if action=='run' else original['serviceTier'])
            await update(a,'model',alternate['model'])
            marker=await submit(a,'只回复 NCM01-MODEL，不使用工具，不读取或修改文件。');await completed(a,marker)
            await update(a,'model',original['model'])
            busy=await submit(a,'只执行一次 /bin/sleep 30，然后回复 NCM01-BUSY，不读取或修改文件。')
            async with asyncio.timeout(60):
                while (await verify(a))['status']['type']!='active':await asyncio.sleep(.1)
            queued=await submit(a,'只回复 NCM01-QUEUED，不使用工具，不读取或修改文件。')
            active_before=await snapshot(a);await update(a,'effort',next(v for v in efforts if v!=active_before.get('reasoningEffort')))
            case['busy_probe_updates']=case['updates'][-1];save()
            await completed(a,busy,busy=True);await completed(a,queued)
            await update(a,'effort',original['reasoningEffort']);await update(a,'serviceTier',original['serviceTier'])
            if await snapshot(b)!=other or await snapshot(a)!=original:raise ValueError('Owned settings not preserved or restored')
            if pump.done():raise ValueError('Owned native event consumer ended unexpectedly')
            case.update(phase='probe_complete',notifications=notifications,queue_race_requires_semantic_review=True);save()
            print(json.dumps({'phase':'probe_complete','updates':len(case['updates']),'business_inputs':len(case['inputs']),
                              'write_gate_still_closed':True,'semantic_review_required':True,'wechat_sends':0,'production_writes':0}))
        elif action=='bridge-reconcile':
            for item in case['fixtures']:
                app=await iterm2.async_get_app(host.connection);terminal=app.get_session_by_id(item['terminal_id'])
                endpoint=await inspect_terminal(terminal) if terminal else None
                if endpoint is None or endpoint.process is None or json.loads(json.dumps(asdict(endpoint.process)))!=item['process']:
                    raise ValueError('Owned Controller recovery process changed')
                await verify(item)
            module_spec=importlib.util.spec_from_file_location('owned_bridge',Path(__file__).with_name('native_control_bridge.py'))
            module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
            await module.reconcile_controls(root,case,native,save)
            for intent in case['inputs']:
                await completed(case['fixtures'][0],intent,busy=intent['expected']=='NCM01-BRIDGE-BUSY')
            if await snapshot(case['fixtures'][0])!=case['initial_a'] or await snapshot(case['fixtures'][1])!=case['initial_b']:
                raise ValueError('Owned settings changed during Controller reconciliation')
            protected();case['phase']='probe_complete';save()
            print(json.dumps({'phase':'probe_complete','bridge_controller':case['bridge_controller'],'settings_requests':len(case['updates']),
                              'inputs':len(case['inputs']),'replayed_inputs':0,'wechat_sends':0,'production_writes':0}))
        elif action=='reconcile-completed-inputs':
            if case['phase']!='running' or len(case['inputs'])!=3 or len(case['updates'])!=8:
                raise ValueError('Expected exact completed probe checkpoint')
            a,b=case['fixtures']
            for intent in case['inputs']:
                await completed(a,intent,busy=intent['expected']=='NCM01-BUSY')
            if await snapshot(a)!=case['initial_a'] or await snapshot(b)!=case['initial_b']:
                raise ValueError('Owned original settings not restored')
            if any([await NativeQueue(native,i['thread_id'],root/'projects'/i['name']).list() for i in (a,b)]):
                raise ValueError('Owned queue not empty')
            protected();case.update(phase='probe_complete',queue_race_requires_semantic_review=True,
                                   reconciliation='Read original client IDs only; no task or setting replay');save()
            print(json.dumps({'phase':'probe_complete','updates':len(case['updates']),'business_inputs':len(case['inputs']),
                              'write_gate_still_closed':True,'semantic_review_required':True,'wechat_sends':0,'production_writes':0}))
        elif action=='audit':
            rows=[]
            for item in case['fixtures']:
                app=await iterm2.async_get_app(host.connection);terminal=app.get_session_by_id(item['terminal_id'])
                if terminal is None:raise ValueError('Owned audit terminal missing')
                endpoint=await inspect_terminal(terminal)
                if endpoint.process is None or json.loads(json.dumps(asdict(endpoint.process)))!=item['process']:
                    raise ValueError('Owned audit process changed')
                metadata=await verify(item)
                rows.append({'name':item['name'],'metadata':metadata,'settings':await snapshot(item),
                             'queue':await NativeQueue(native,item['thread_id'],root/'projects'/item['name']).list(),
                             'owned_turns':await native.read_turns(item['thread_id'],limit=20)})
            protected();case['last_audit']=rows;save()
            print(json.dumps({'phase':'audited','owned_threads':len(rows),
                              'idle_and_empty':all(v['metadata']['status']['type']=='idle' and not v['queue'] for v in rows),
                              'protected_configuration_unchanged':True,'settings_writes':0,'inputs':0}))
        elif action=='cleanup':
            if case.get('bridge_queue_requests') and {v['client_id'] for v in case['bridge_queue_requests']}!={v['client_id'] for v in case['inputs']}:
                raise ValueError('Bridge input intents need exact task reconciliation before cleanup')
            if any(v['phase'] not in {'confirmed','unchanged','rejected_verified_unchanged','normalized_reset_verified'} for v in case['updates']) or any(v['phase'] not in {'completed','failed','interrupted'} for v in case['inputs']):
                raise ValueError('Unconfirmed owned operations must be reviewed before cleanup')
            for item in case['fixtures']:
                app=await iterm2.async_get_app(host.connection);terminal=app.get_session_by_id(item['terminal_id'])
                if terminal is None:continue
                endpoint=await inspect_terminal(terminal)
                if endpoint.process is None or json.loads(json.dumps(asdict(endpoint.process)))!=item['process']:
                    raise ValueError('Owned process changed; do not close')
                metadata=await verify(item)
                if metadata['status']['type']!='idle' or await NativeQueue(native,item['thread_id'],root/'projects'/item['name']).list():
                    raise ValueError('Owned thread is not idle and empty')
                await terminal.async_close(force=True)
            app=await iterm2.async_get_app(host.connection)
            if any(app.get_session_by_id(i['terminal_id']) is not None for i in case['fixtures']):raise ValueError('Owned terminal absence not confirmed')
            case['phase']='cleaned';save();print(json.dumps({'phase':'cleaned','owned_terminals':len(case['fixtures'])}))
        protected()
    finally:
        if pump:
            pump.cancel();await asyncio.gather(pump,return_exceptions=True)
        if native:await native.close()
        await host.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','run','bridge-run','bridge-reconcile','audit','continue-reviewed-reset','reconcile-completed-inputs','cleanup'))
    parser.add_argument('--case-dir',required=True,type=Path);parser.add_argument('--confirm-dedicated',action='store_true')
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.case_dir.resolve())
    else:
        if not args.confirm_dedicated:parser.error('Specific owned terminal/settings/input authorization required')
        asyncio.run(run(args.case_dir.resolve(),args.action))
