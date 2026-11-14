"""NCM01 owned Controller acceptance; invoked only by the authorized probe driver."""

import asyncio
import hashlib
from pathlib import Path

from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.visible import LaunchRegistry, VisibleStarter
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.sessions import SessionBinding


async def consume_events(native,engine):
    while True:
        try:event=await native.rpc.next_event(timeout=1)
        except TimeoutError:continue
        await engine.event(event)


async def run_controls(root,case,native,host,save):
    """Synthetic owner commands exercise real Controller and native RPC, never WeChat."""
    if case['inputs'] or case['updates'] or len(case['fixtures'])!=2:
        raise ValueError('Fresh, exactly two owned fixtures required')
    original,other=case['initial_a'],case['initial_b']
    if original.get('serviceTier')!='default' or original.get('reasoningEffort')!='high':
        raise ValueError('Owned test requires verified default tier and high baseline')
    projects=tuple(Project(i['name'],root/'projects'/i['name']) for i in case['fixtures'])
    class NoHostDiscovery:
        async def discover(self):return ()
    catalog=SessionCatalog(projects,NoHostDiscovery(),native)
    for item,project in zip(case['fixtures'],projects):
        catalog.managed_threads.add(item['thread_id'])
        catalog.remember_verified(SessionBinding(None,project.root,native.runtime_identity,
                                  item['thread_id'],item['native_session_id']),managed=True,title='NCM01 owned')
    state=await RuntimeState.open(root/'bridge-private/runtime.sqlite3',
        Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','fixture-token'))
    # No launch records or terminal callback: this Controller only selects exact loaded fixtures.
    starter=VisibleStarter(LaunchRegistry(root/'bridge-private/unused-launches'),None)
    controller=Controller(projects,catalog,state,starter,Path('/unused'),Path.home()/'.codex')
    engine=Execution(controller);counter=0;case['controller_commands']=[];case['bridge_queue_requests']=[]
    raw_request=native.rpc.request
    async def request(method,params,**kwargs):
        if method=='thread/settings/update':
            if len(case['updates'])>=8:raise ValueError('Bridge probe setting budget exhausted')
            case['updates'].append({'phase':'intent','params':params.copy()});save()
        if method=='thread/queue/add':
            if len(case['bridge_queue_requests'])>=3:raise ValueError('Bridge probe input budget exhausted')
            case['bridge_queue_requests'].append({'phase':'intent','client_id':params['clientUserMessageId']});save()
        result=await raw_request(method,params,**kwargs)
        if method=='thread/queue/add':case['bridge_queue_requests'][-1]['phase']='acknowledged';save()
        return result
    native.rpc.request=request
    pump=asyncio.create_task(consume_events(native,engine))
    async def command(text):
        nonlocal counter
        if pump.done():raise ValueError('Owned event consumer ended')
        counter+=1
        source={'message_id':counter,'from_user_id':'fixture-owner','to_user_id':'fixture-bot',
            'message_type':1,'message_state':2,'create_time_ms':counter,'seq':counter,
            'context_token':'fixture-context','item_list':[{'type':1,'text_item':{'text':text}}]}
        batch=await state.accept_batch({'ret':0,'msgs':[source]},phase='runtime')
        message=batch['accepted'][0]
        await controller.prepare(message)
        record=engine.native_controls.journal().read(message.message_id)
        if record is not None:
            for item in case['updates']:
                if item['phase']=='intent' and item['params']=={'threadId':record['target']['thread_id'],
                        **record['setting']}:
                    item['phase']=record['phase'];item['source_id']=message.message_id
        rows=await state._call(lambda:[r[0] for r in state.db.execute('SELECT text FROM outbox ORDER BY rowid')])
        if len(rows)>256:raise ValueError('Owned response bound exceeded')
        case['controller_commands'].append({'text':text,'source_id':message.message_id,'record':record,'replies':rows[-4:]});save()
        if record is not None and record['phase'] not in {'confirmed','unchanged'}:
            raise ValueError('Owned Controller setting was not confirmed')
        if text.startswith(('/model ','/fast ')) and record is None and any(
                v in text for v in ('/model set ','/fast on','/fast off')):
            # Busy negative checks are verified explicitly by the caller.
            return False
        return record is not None
    async def task(text,expected):
        before=await state.tasks();await command(text)
        tasks=[v for v in await state.tasks() if v['id'] not in {t['id'] for t in before}]
        if len(tasks)!=1:raise ValueError('Owned task admission not unique')
        task=tasks[0];intent={'phase':'queued','client_id':task['client_id'],'task_id':task['id'],'expected':expected}
        case['inputs'].append(intent);save();return intent
    async def completed(intent):
        async with asyncio.timeout(180):
            while True:
                if pump.done():raise ValueError('Owned event consumer ended during task')
                item=await state.tasks(task_id=intent['task_id'])
                if item['state'] in {'completed','failed','interrupted','cancelled','unknown'}:
                    intent.update(phase=item['state'],turn_id=item['turn_id']);save()
                    if item['state']!='completed':raise ValueError('Owned Controller task did not complete')
                    return
                await asyncio.sleep(.1)
    async def settings(text):
        if not await command(text):raise ValueError('Owned settings command did not create a confirmed record')
        save()
    try:
        await command('/sessions');await command('/focus 1');await command('/model list');await command('/model')
        await settings('/model set '+original['model']+' medium');await settings('/fast on');await command('/fast')
        await settings('/fast off');await settings('/model set '+case['test_model']+' medium')
        count=len(case['updates']);await settings('/model set '+case['test_model']+' medium')
        if len(case['updates'])!=count:raise ValueError('Explicit same value produced another native setting write')
        import iterm2
        app=await iterm2.async_get_app(host.connection)
        terminal=app.get_session_by_id(case['fixtures'][0]['terminal_id'])
        screen=await terminal.async_get_screen_contents()
        text='\n'.join(screen.line(i).string for i in range(screen.number_of_lines))
        (root/'owned-tui-after-settings.txt').write_text(text)
        case['tui_observation']={'only_owned_terminal':True,'screen_sha256':hashlib.sha256(text.encode()).hexdigest(),
                                 'new_model_visible':case['test_model'] in text};save()
        marker=await task('只回复 NCM01-BRIDGE-MODEL，不使用工具，不读取或修改文件。','NCM01-BRIDGE-MODEL')
        await completed(marker)
        await settings('/model set '+original['model']+' '+original['reasoningEffort'])
        busy=await task('只执行一次 /bin/sleep 30，然后回复 NCM01-BRIDGE-BUSY，不读取或修改文件。','NCM01-BRIDGE-BUSY')
        async with asyncio.timeout(60):
            while (await native.inspect(case['fixtures'][0]['thread_id']))['status']['type']!='active':await asyncio.sleep(.1)
        queued=await task('只回复 NCM01-BRIDGE-QUEUED，不使用工具，不读取或修改文件。','NCM01-BRIDGE-QUEUED')
        count=len(case['updates'])
        if await command('/model set '+original['model']+' medium') or len(case['updates'])!=count:
            raise ValueError('Known busy Controller setting was sent')
        await command('/codex status');await completed(busy);await completed(queued)
        await command('/focus 2');await command('/model');await command('/help');await command('/unfocus')
        for item,expected in zip(case['fixtures'],(original,other)):
            if await native.read_settings(item['thread_id'],root/'projects'/item['name'])!=expected:
                raise ValueError('Owned original settings changed')
        if pump.done():raise ValueError('Owned event consumer unexpectedly ended')
        case.update(bridge_controller='candidate_completed',phone_tested=False);save()
    finally:
        native.rpc.request=raw_request
        if pump.done() and not pump.cancelled() and pump.exception() is not None:
            case['bridge_event_error']={'type':type(pump.exception()).__name__};save()
        pump.cancel();await asyncio.gather(pump,return_exceptions=True)
        await engine.close();await state.close()


async def reconcile_controls(root,case,native,save):
    """Finish the exact accepted inputs after an observed driver failure; no replay."""
    if (case['phase']!='running' or len(case['inputs'])!=3 or len(case['updates']) not in {5,6}
            or any(v['phase']!='confirmed' for v in case['updates'])):
        raise ValueError('Exact accepted Controller checkpoint required')
    projects=tuple(Project(i['name'],root/'projects'/i['name']) for i in case['fixtures'])
    class NoHostDiscovery:
        async def discover(self):return ()
    catalog=SessionCatalog(projects,NoHostDiscovery(),native)
    for item,project in zip(case['fixtures'],projects):
        catalog.managed_threads.add(item['thread_id'])
        catalog.remember_verified(SessionBinding(None,project.root,native.runtime_identity,
            item['thread_id'],item['native_session_id']),managed=True,title='NCM01 owned')
    state=await RuntimeState.open(root/'bridge-private/runtime.sqlite3',
        Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','fixture-token'))
    starter=VisibleStarter(LaunchRegistry(root/'bridge-private/unused-launches'),None)
    controller=Controller(projects,catalog,state,starter,Path('/unused'),Path.home()/'.codex');engine=Execution(controller)
    raw=native.rpc.request
    async def readonly(method,params,**kwargs):
        if method in {'thread/settings/update','thread/queue/add','turn/start','thread/queue/delete','turn/interrupt'}:
            raise ValueError('Recovery cannot mutate native state')
        return await raw(method,params,**kwargs)
    native.rpc.request=readonly
    try:
        await controller.restore();await state.native_disconnected();await engine.reconcile()
        for intent in case['inputs']:
            task=await state.tasks(task_id=intent['task_id'])
            if task is None or task['client_id']!=intent['client_id'] or task['state']!='completed':
                raise ValueError('Exact Controller task did not reconcile to completed')
            intent.update(phase=task['state'],turn_id=task['turn_id'])
        if await state.tasks(active_only=True):raise ValueError('Owned active occupancy remains')
        counter=len(case['controller_commands'])+100
        for text in ('/sessions','/focus 2','/model','/help','/unfocus'):
            counter+=1
            source={'message_id':counter,'from_user_id':'fixture-owner','to_user_id':'fixture-bot',
                'message_type':1,'message_state':2,'create_time_ms':counter,'seq':counter,
                'context_token':'fixture-context','item_list':[{'type':1,'text_item':{'text':text}}]}
            batch=await state.accept_batch({'ret':0,'msgs':[source]},phase='runtime')
            await controller.prepare(batch['accepted'][0])
        b=case['fixtures'][1]
        if await native.read_settings(b['thread_id'],root/'projects'/b['name'])!=case['initial_b']:
            raise ValueError('Owned B settings changed')
        case.update(bridge_controller='passed_after_readonly_driver_reconciliation',
                    driver_recovery={'idle_poll_timeout_reproduced_and_fixed':True,'native_inputs_replayed':0,
                                     'native_settings_replayed':0,'tasks_reconciled':3,'remaining_queries_completed':True});save()
    finally:
        native.rpc.request=raw
        await engine.close();await state.close()
