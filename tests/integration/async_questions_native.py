"""Explicit owned native ASK01 candidate proof; fake delivery, no WeChat I/O."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.commands import parse_command
from wx_clawbot.config import load_projects
from wx_clawbot.controller import Controller, target_record
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.managed import source_digest
from wx_clawbot.output import native_output
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_state import RuntimeState


async def main(args):
    import iterm2
    project = Path(__file__).resolve().parents[2]
    for path in (args.case_dir,args.report_dir):
        if not path.resolve().is_relative_to((project/'.tmp').resolve()):
            raise ValueError('Owned case and evidence must stay in this candidate .tmp')
    output = private_directory(args.report_dir.absolute())
    record_path = output/'case.json'
    if args.action == 'report':
        record = read_json(record_path)
        print(json.dumps({'phase':record['phase'],'source_sha256':record['source_sha256'],
            'native_submissions':record['native_submissions'],'wechat_sends':0}))
        return
    if not args.confirm_dedicated or record_path.exists():
        raise ValueError('A fresh, explicitly owned test intent required; never retry old input')
    owned = read_json(args.case_dir/'case.json')
    if owned['phase'] != 'ready':
        raise ValueError('Owned preparation is not ready')
    fixture = owned['fixtures'][1]
    boot = read_json(args.case_dir/'launches'/(fixture['launch_id']+'.boot.json'))
    home = Path.home()/'.codex'
    production = Path.home()/'Library/Application Support/wx-clawbot'
    protected = [home/'config.toml',production/'config.json',production/'credentials.json',
                 Path.home()/'Library/LaunchAgents/local.wx-clawbot.plist']
    hashes = lambda:[hashlib.sha256(p.read_bytes()).hexdigest() for p in protected]
    before = hashes()
    record = {'phase':'prepared','source_sha256':source_digest(),'native_submissions':0,'answer_calls':0}
    write_json(record_path,record)
    host = HostLifecycle()
    native = engine = state = None
    jobs=[]
    try:
        await host.ensure()
        app = await iterm2.async_get_app(host.connection)
        terminal = app.get_session_by_id(fixture['terminal_id'])
        if terminal is None:
            raise ValueError('Owned terminal no longer exists; do not recreate implicitly')
        endpoint = await inspect_terminal(terminal)
        assert endpoint.process.pid == boot['pid'] and list(endpoint.process.started) == boot['started']
        socket,executable = await asyncio.to_thread(discover_runtime,home)
        native = await CodexConnection.connect(socket)
        projects = load_projects(production/'config.json')
        catalog = SessionCatalog(projects,ItermDirectory(lifecycle=host),native)
        catalog.managed_threads = {f['thread_id'] for f in owned['fixtures']}
        sessions = await catalog.discover()
        matches = [s for s in sessions if s.binding.thread_id==fixture['thread_id']
                   and s.binding.endpoint.terminal_id==fixture['terminal_id']]
        assert len(matches)==1
        session = await catalog.require(matches[0].target)
        assert (await native.inspect(fixture['thread_id']))['status']['type']=='idle'
        assert not await NativeQueue(native,fixture['thread_id'],session.target.cwd).list()
        state = await RuntimeState.open(output/'isolated/runtime.sqlite3',
            Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','fixture-token'))
        controller = Controller(projects,catalog,state,None,executable,home)
        controller.routes.target = session.target
        engine = Execution(controller)
        delivered=[]
        question_delivered=asyncio.Event()
        class Api:
            async def send_text(self,*_,**kwargs):
                delivered.append(kwargs['text'])
                if '/answer q-' in kwargs['text']:
                    question_delivered.set()
                return {'message_id':'synthetic-'+str(len(delivered))}
        sender=Sender(state,Api())
        jobs=[asyncio.create_task(engine.run()),asyncio.create_task(sender.run())]
        nonce=uuid.uuid4().hex[:12]
        marker='ASK01-CANDIDATE-END-'+nonce
        prompt=('ASK01 自有候选原生验收。只授权一次 request_user_input_async 与一次等待命令，不读写文件、'
            '不联网、不发消息、不调用其他工具或执行项目工作。立即提出一个问题，标题 ASK01-CANDIDATE-'+nonce+
            '，选项 ALPHA 与 BETA。问题发出后仅运行一次 python3 -c "import time; time.sleep(20)"，'
            '等待另一个原生客户端的真实补充答案。不要默认选择、不要重复提问。收到后仅复述真实答案并输出 '+marker+
            '。等待结束没有答案则明确未收到，不编造。')
        source=str(uuid.uuid4().int & (2**63-1))
        raw={'message_id':source,'from_user_id':'fixture-owner','to_user_id':'fixture-bot','message_type':1,
             'message_state':2,'create_time_ms':1,'seq':1,'context_token':'synthetic-context',
             'item_list':[{'type':1,'text_item':{'text':prompt}}]}
        batch=await state.accept_batch({'ret':0,'msgs':[raw]},phase='runtime')
        assert len(batch['accepted'])==1
        source=batch['accepted'][0].message_id
        task=await state.task_intent(source,target_record(session),prompt)
        await state.task_update(task['id'],'received')
        record.update(phase='native_intent',task_id=task['id'],client_id=task['client_id'],marker=marker,
                      thread_id=fixture['thread_id'])
        write_json(record_path,record,replace=True)
        # Explicitly isolated, read-only owned task; no production admission view is modified.
        await engine.dispatch(await state.tasks(task_id=task['id']))
        record['native_submissions']=1
        write_json(record_path,record,replace=True)
        async with asyncio.timeout(180):
            while not question_delivered.is_set():
                for job in jobs:
                    if job.done(): job.result()
                current=await state.tasks(task_id=task['id'])
                if current['state'] in {'completed','failed','interrupted','cancelled'} and not await state.async_rows(task_id=task['id']):
                    record['phase']='ended_without_structured_async_question'
                    raise ValueError('Native task ended without a structured async question; check model/tool availability')
                await asyncio.sleep(.05)
        rows=await state.async_rows(task_id=task['id'])
        assert len(rows)==1 and rows[0]['state']=='pending'
        question=rows[0]
        assert (await engine.read_turn(fixture['thread_id'],question['turn_id']))['status']=='inProgress'
        record.update(phase='answer_intent',question_id=question['public_id'],turn_id=question['turn_id'],
                      question_delivered_before_answer=True)
        write_json(record_path,record,replace=True)
        receipt=await engine.control(parse_command('/answer '+question['public_id']+' BETA '+nonce))
        record.update(answer_calls=1,answer_receipt=receipt)
        write_json(record_path,record,replace=True)
        async with asyncio.timeout(180):
            while True:
                for job in jobs:
                    if job.done():job.result()
                current=await state.tasks(task_id=task['id'])
                if current['state'] in {'completed','failed','interrupted'}:
                    break
                await asyncio.sleep(.1)
        assert current['state']=='completed'
        turn=await engine.read_turn(fixture['thread_id'],question['turn_id'])
        answer=(await state.async_rows(public_id=question['public_id']))[0]
        clients=[i.get('clientId') for i in turn['items'] if i.get('type')=='userMessage']
        assert len(clients)==2 and clients.count(task['client_id'])==1 and clients.count(answer['answer_client'])==1
        assert answer['state']=='observed'
        text=native_output(turn)
        assert marker in text and 'BETA' in text and nonce in text
        async with asyncio.timeout(10):
            while not any(marker in text for text in delivered):
                await asyncio.sleep(.05)
        assert before==hashes() and source_digest()==record['source_sha256']
        proof={'passed':True,'source_sha256':source_digest(),'native_version':native.server_version,
               'schema':6,'original_task_submissions':1,'answer_submissions':1,'original_client_occurrences':1,
               'answer_client_occurrences':1,'user_messages':2,'original_turn_preserved':True,
               'question_delivered_before_answer':True,'answer_observed':True,'model_observed_answer':True,
               'task_status':'completed','protected_files_unchanged':True,'wechat_sends':0,'production_ledger_writes':0}
        write_json(output/'proof.json',proof)
        record['phase']='verified'
        write_json(record_path,record,replace=True)
        print(json.dumps(proof),flush=True)
    except BaseException as exc:
        record.update(error_type=type(exc).__name__,error=str(exc)[:200])
        write_json(record_path,record,replace=True)
        raise
    finally:
        for job in jobs:job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
        if engine:await engine.close()
        if state:await state.close()
        if native:await native.close()
        await host.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','report'])
    parser.add_argument('--case-dir',required=True,type=Path)
    parser.add_argument('--report-dir',required=True,type=Path)
    parser.add_argument('--confirm-dedicated',action='store_true')
    asyncio.run(main(parser.parse_args()))
