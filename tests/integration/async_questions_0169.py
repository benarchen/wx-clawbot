"""Owned 0.169.0 async acceptance; isolated ledger, no real WeChat or settings writes."""

import argparse
import asyncio
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.commands import CommandError, parse_command
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller, target_record
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter, reconcile_launch
from wx_clawbot.managed import source_digest
from wx_clawbot.output import native_output
from wx_clawbot.release import verify_active
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_state import RuntimeState


spec = importlib.util.spec_from_file_location('owned_async_fixture',
    Path(__file__).with_name('native_session_no_footer.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def save(root, case):
    write_json(root / 'case.json', case, replace=(root / 'case.json').exists())


def prepare(root):
    private_directory(root)
    if (root / 'case.json').exists():
        raise FileExistsError('Never overwrite an owned acceptance intent')
    for name in ('async-a', 'async-b'):
        cwd = private_directory(root / 'projects' / name)
        (cwd / 'AGENTS.md').write_text(
            '这是本人授权的异步追问专用验收临时项目。启动时按提示只读取本文件并回复完整 WX-LAUNCH 标记。'
            '后续仅在明确验收任务中调用一次 request_user_input_async（两题），仅执行一次 /bin/sleep 30，'
            '根据真实补充答复输出要求的标记。不得读取其他文件、联网、修改文件、另开任务或调用其他工具。\n')
    save(root, {'phase': 'prepared', 'protected': fixture.protected(), 'fixtures': [],
                'checks': {}, 'startup_inputs': 0, 'business_inputs': 0, 'answer_calls': 0,
                'wechat_sends': 0, 'production_writes': 0, 'settings_writes': 0})
    print(json.dumps({'phase': 'prepared', 'maximum_owned_terminals': 2,
                      'maximum_business_inputs': 1, 'maximum_answers': 1}), flush=True)


async def run(root, action, manifest):
    import iterm2
    release = verify_active(manifest)
    if release is None:
        raise ValueError('Live acceptance requires a frozen non-editable release manifest')
    case = read_json(root / 'case.json')
    if action == 'run' and case['phase'] != 'prepared':
        raise ValueError('Never replay a previous owned launch, task or answer')
    if case['protected'] != fixture.protected():
        raise ValueError('Protected configuration changed')
    host, native, state, engine, jobs = HostLifecycle(), None, None, None, []
    registry = LaunchRegistry(root / 'launches')
    projects = tuple(Project(name, root / 'projects' / name) for name in ('async-a', 'async-b'))
    try:
        socket, executable = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        if native.server_version != '0.169.0':
            raise ValueError('Only the reviewed 0.169.0 runtime is allowed')
        if action == 'cleanup' and list(native.runtime_identity) != case['runtime']:
            raise ValueError('Owned native runtime changed')
        await host.ensure(launch=action == 'run', explicit=action == 'run')
        directory = ItermDirectory(lifecycle=host)
        catalog = SessionCatalog(projects, directory, native)

        async def idle(item):
            metadata = await native.inspect(item['thread_id'])
            if (list(native.runtime_identity) != case['runtime']
                    or metadata.get('sessionId') != item['native_session_id']
                    or metadata.get('cwd') != str(root / 'projects' / item['name'])
                    or metadata.get('status', {}).get('type') != 'idle'
                    or await NativeQueue(native, item['thread_id'], Path(metadata['cwd'])).list()):
                raise ValueError('Owned exact thread is not idle with a complete empty queue')

        async def cleanup():
            if case.get('business_inputs') or case.get('task_id'):
                current = await state.tasks(task_id=case['task_id'])
                if current is None or current['state'] != 'completed' or not current['turn_id']:
                    raise ValueError('Owned business intent requires exact terminal reconciliation')
                turn = await native.read_turns(current['thread_id'], limit=20)
                matches = [t for t in turn['data'] if t['id'] == current['turn_id']]
                if len(matches) != 1 or matches[0]['status'] != 'completed':
                    raise ValueError('Owned exact business turn has no completed evidence')
            for item in case['fixtures']:
                if item.get('phase') != 'ready':
                    raise ValueError('Unconfirmed startup needs read-only reconciliation')
                await idle(item)
                app = await iterm2.async_get_app(host.connection)
                terminal = app.get_session_by_id(item['terminal_id'])
                if terminal is None and item.get('closed'):
                    continue
                if terminal is None:
                    raise ValueError('Owned terminal disappeared before close intent')
                endpoint = await inspect_terminal(terminal)
                if (endpoint.process is None or json.loads(json.dumps(asdict(endpoint.process)))
                        != json.loads(json.dumps(item['process']))):
                    raise ValueError('Owned terminal process changed')
                item['close_intent'] = True
                save(root, case)
                await terminal.async_close(force=True)
                item['closed'] = True
                save(root, case)
                await native.unsubscribe(item['thread_id'])
            if fixture.protected() != case['protected']:
                raise ValueError('Protected configuration changed')
            case['phase'] = 'verified_and_closed' if case['checks'].get('native_flow') else 'cleaned'
            save(root, case)

        if action == 'cleanup':
            state = await RuntimeState.open(root / 'isolated/runtime.sqlite3',
                Credentials('fixture-bot', 'fixture-owner', 'https://ilinkai.weixin.qq.com/', 'fixture-token'))
            await cleanup()
            return
        case.update(phase='launching', runtime=list(native.runtime_identity),
                    source_sha256=source_digest(), wheel_sha256=release['wheel_sha256'])
        save(root, case)
        starter = VisibleStarter(registry, ItermWindowStarter(lifecycle=host))
        sessions = []
        for project in projects:
            item = {'name': project.alias, 'launch_id': uuid.uuid4().hex, 'phase': 'intent'}
            case['fixtures'].append(item)
            case['startup_inputs'] += 1
            save(root, case)
            await starter.start(item['launch_id'], project, project.root, executable, Path.home() / '.codex', project.alias)
            record = registry.load(item['launch_id'])
            item.update({key: record[key] for key in ('window_id', 'tab_id', 'terminal_id')})
            save(root, case)
            thread = await fixture.bootstrap(native, registry, item)
            binding = await reconcile_launch(registry, item['launch_id'], directory, native)
            if binding.thread_id != thread['id']:
                raise ValueError('Owned unique startup handshake mismatch')
            endpoint = await inspect_terminal((await iterm2.async_get_app(host.connection)).get_session_by_id(item['terminal_id']))
            boot = read_json(registry.root / (item['launch_id'] + '.boot.json'))
            if (endpoint.process is None or endpoint.process.pid != boot['pid']
                    or list(endpoint.process.started) != boot['started']
                    or endpoint.process.tty_device != boot['tty_device']):
                raise ValueError('Owned process differs from its boot receipt')
            item.update(phase='ready', thread_id=thread['id'], native_session_id=thread['sessionId'],
                        process=asdict(endpoint.process))
            sessions.append(catalog.remember_verified(binding, managed=True))
            save(root, case)
            print(json.dumps({'phase': 'owned_startup_verified', 'project': project.alias}), flush=True)
        if len({item['window_id'] for item in case['fixtures']}) != 1:
            raise ValueError('Owned fixtures must share one dedicated window')
        state = await RuntimeState.open(root / 'isolated/runtime.sqlite3',
            Credentials('fixture-bot', 'fixture-owner', 'https://ilinkai.weixin.qq.com/', 'fixture-token'))
        controller = Controller(projects, catalog, state, starter, executable, Path.home() / '.codex')
        engine = Execution(controller)
        a, b = sessions
        await controller.subscriptions.acquire(a.target, 'route')
        controller.routes.focus(a.target, expected=controller.routes.revision)
        delivered = []

        class Api:
            async def send_text(self, *_, **kwargs):
                delivered.append(kwargs['text'])
                return {'message_id': 'synthetic-' + str(len(delivered))}

        jobs = [asyncio.create_task(engine.run()), asyncio.create_task(Sender(state, Api()).run())]

        async def wait_for(check):
            async with asyncio.timeout(180):
                while True:
                    for job in jobs:
                        if job.done():
                            job.result()
                    value = await check()
                    if value:
                        return value
                    await asyncio.sleep(.1)

        nonce = uuid.uuid4().hex[:12]
        marker, question_marker = 'ASK0169-END-' + nonce, 'ASK0169-QUESTION-' + nonce
        prompt = ('本人授权的异步接口验收：只调用一次 request_user_input_async，一次提出两题，'
            f'第一题标题 {question_marker}-FREE，允许自由文字；第二题标题 {question_marker}-CHOICE，'
            '选项 ALPHA、BETA。发出后仅执行一次 /bin/sleep 30 等待真实补充输入；'
            '不默认选择、不重复提问、不调用其他工具。收到真实补充后仅输出标记 ' + marker +
            ' 及两题的真实答案值，不复述题目标题。没有收到就明确未收到，不编造答案。')
        raw = {'message_id': str(uuid.uuid4().int & (2**63 - 1)), 'from_user_id': 'fixture-owner',
               'to_user_id': 'fixture-bot', 'message_type': 1, 'message_state': 2,
               'create_time_ms': 1, 'seq': 1, 'context_token': 'synthetic-context',
               'item_list': [{'type': 1, 'text_item': {'text': prompt}}]}
        batch = await state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
        task = await state.task_intent(batch['accepted'][0].message_id, target_record(a), prompt)
        await state.task_update(task['id'], 'received')
        case.update(phase='business_intent', business_inputs=1, task_id=task['id'])
        save(root, case)
        await engine.dispatch(await state.tasks(task_id=task['id']))

        async def question_ready():
            rows = await state.async_rows(task_id=task['id'])
            current = await state.tasks(task_id=task['id'])
            if current['state'] in {'completed', 'failed', 'interrupted', 'unknown'} and not rows:
                raise ValueError('Owned task ended without a usable structured question; never replay')
            return rows[0] if len(rows) == 1 and any('/answer ' + rows[0]['public_id'] in t for t in delivered) else None

        question = await wait_for(question_ready)
        if question['state'] != 'pending' or len(question['questions']) != 2:
            raise ValueError('A complete two-question pending card required')
        await controller.subscriptions.acquire(b.target, 'route')
        controller.routes.focus(b.target, expected=controller.routes.revision)
        await controller.subscriptions.release(a.target, 'route')
        values = {'q1': 'NOTE-' + nonce, 'q2': 'BETA-' + nonce}
        command = parse_command('/answer ' + question['public_id'] + ' ' + json.dumps(values))
        case.update(phase='answer_intent', question_id=question['public_id'],
                    turn_id=question['turn_id'], answer_calls=1)
        save(root, case)
        receipt = await engine.control(command)
        case['answer_receipt'] = receipt
        save(root, case)
        try:
            await engine.control(command)
        except CommandError:
            case['checks']['duplicate_refused'] = True
        else:
            raise ValueError('A duplicate answer was not refused')
        print(json.dumps({'phase': 'exact_original_answer_submitted', 'current_target': 'async-b'}), flush=True)

        async def terminal():
            current = await state.tasks(task_id=task['id'])
            if current['state'] == 'unknown':
                raise ValueError('Original task became unknown; never replay')
            return current if current['state'] in {'completed', 'failed', 'interrupted'} else None

        current = await wait_for(terminal)
        if current['state'] != 'completed':
            raise ValueError('Original task did not complete')
        turn = await engine.read_turn(a.binding.thread_id, question['turn_id'])
        answer = (await state.async_rows(public_id=question['public_id']))[0]
        clients = [i.get('clientId') for i in turn['items'] if i.get('type') == 'userMessage']
        text = native_output(turn)
        if (len(clients) != 2 or clients.count(task['client_id']) != 1
                or clients.count(answer['answer_client']) != 1 or answer['state'] != 'observed'
                or marker not in text or any(v not in text for v in values.values())
                or question_marker in text or current['turn_id'] != question['turn_id']):
            raise ValueError('Exact original turn, unique inputs, answer adoption or final separation failed')
        async def final_delivered():
            return any(marker in t and '任务完成' in t and question_marker not in t for t in delivered)
        await wait_for(final_delivered)
        try:
            await engine.control(command)
        except CommandError:
            case['checks']['late_refused'] = True
        else:
            raise ValueError('A late answer was not refused')
        if controller.routes.target != b.target or fixture.protected() != case['protected']:
            raise ValueError('Selected target or protected configuration changed')
        for item in case['fixtures']:
            await idle(item)
        b_turns = (await native.read_turns(b.binding.thread_id, limit=20))['data']
        if len(b_turns) != 1:
            raise ValueError('Other target received an unexpected input')
        case['checks']['native_flow'] = True
        case['phase'] = 'verified'
        save(root, case)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        jobs = []
        await cleanup()
        proof = {'passed': True, 'native_version': native.server_version, 'schema': 6,
                 'source_sha256': source_digest(), 'wheel_sha256': release['wheel_sha256'],
                 'startup_inputs': 2, 'business_inputs': 1, 'answer_submissions': 1,
                 'original_turn_preserved': True, 'answer_observed': True, 'model_adopted_both_answers': True,
                 'target_switch_preserved': True, 'other_target_startup_only': True,
                 'duplicate_refused': True, 'late_refused': True, 'final_excludes_async_question': True,
                 'question_delivered_before_answer': True, 'owned_terminals_closed': True,
                 'protected_configuration_unchanged': True, 'wechat_sends': 0,
                 'production_writes': 0, 'settings_writes': 0}
        write_json(root / 'proof.json', proof)
        print(json.dumps(proof), flush=True)
    except BaseException as error:
        case['failure'] = {'type': type(error).__name__, 'message': str(error)[:250], 'automatic_replay': False}
        save(root, case)
        raise
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        if engine:
            await engine.close()
        if state:
            await state.close()
        if native:
            await native.close()
        await host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run', 'cleanup'))
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--release-manifest', type=Path)
    parser.add_argument('--confirm-dedicated', action='store_true')
    args = parser.parse_args()
    root = args.case_dir.absolute()
    workspace = Path(__file__).resolve().parents[2]
    if not root.resolve().is_relative_to((workspace / '.tmp').resolve()):
        parser.error('Owned evidence must stay in project .tmp')
    os.umask(0o077)
    if args.action == 'prepare':
        prepare(root)
    elif not args.confirm_dedicated:
        parser.error('Explicit dedicated acceptance confirmation required')
    else:
        asyncio.run(run(root, args.action, args.release_manifest))
