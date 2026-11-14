"""Owned live session-notice acceptance; never sends WeChat or restarts the daemon."""

import argparse
import asyncio
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import time
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter, reconcile_launch
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_state import RuntimeState


spec = importlib.util.spec_from_file_location('owned_notice_fixture', Path(__file__).with_name('native_session_no_footer.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def save(root, case):
    write_json(root / 'case.json', case, replace=(root / 'case.json').exists())


def prepare(root):
    private_directory(root)
    if (root / 'case.json').exists():
        raise FileExistsError('An owned acceptance intent cannot be replayed')
    for name in ('notice-a', 'notice-b'):
        cwd = private_directory(root / 'projects' / name)
        (cwd / 'AGENTS.md').write_text('这是本人授权的会话通知验收临时项目。仅按可见启动提示读取本文件并回复完整 WX-LAUNCH 标记；不修改文件，不运行测试，不执行其他任务。\n')
    save(root, {'phase': 'prepared', 'protected': fixture.protected(), 'fixtures': [], 'checks': {},
                'maximum_startup_inputs': 2, 'extra_native_inputs': 0, 'wechat_sends': 0,
                'production_writes': 0, 'daemon_restarts': 0})
    print(json.dumps({'phase': 'prepared', 'maximum_owned_terminals': 2}), flush=True)


async def run(root, action):
    import iterm2
    case = read_json(root / 'case.json')
    if action == 'run' and case['phase'] != 'prepared':
        raise ValueError('Only a fresh owned run is permitted; inspect failures before cleanup')
    if action == 'resume-reviewed':
        if (case['phase'] != 'selected' or len(case['fixtures']) != 2
                or not case['checks'].get('real_transport_reconnect_and_30_second_notice')
                or case.get('failure', {}).get('message') != 'Owned terminal process differs from its boot receipt'
                or any(item.get('close_intent') for item in case['fixtures'])
                or not (root / 'reviewed-process-check.json').is_file()):
            raise ValueError('Only the independently reviewed, pre-close checkpoint may continue')
        case['reviewed_failure'] = case.pop('failure')
        save(root, case)
    if case['protected'] != fixture.protected():
        raise ValueError('Protected daily configuration changed')
    host, connections, state = HostLifecycle(), [], None
    registry = LaunchRegistry(root / 'launches')
    projects = tuple(Project(name, root / 'projects' / name) for name in ('notice-a', 'notice-b'))
    try:
        socket, executable = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        connections.append(native)
        if native.server_version != '0.169.0':
            raise ValueError('This live acceptance requires the reviewed 0.169.0 protocol')
        await host.ensure(launch=action == 'run', explicit=action == 'run')
        host.verified(host.generation)
        directory = ItermDirectory(lifecycle=host)
        starter = VisibleStarter(registry, ItermWindowStarter(lifecycle=host))

        async def checkpoint(name):
            case['checks'][name] = True
            save(root, case)
            print(json.dumps({'phase': case['phase'], 'check': name}), flush=True)

        async def owned_idle(item):
            metadata = await native.inspect(item['thread_id'])
            if (metadata.get('sessionId') != item['native_session_id']
                    or metadata.get('cwd') != str(root / 'projects' / item['name'])
                    or metadata.get('status', {}).get('type') != 'idle'
                    or list(native.runtime_identity) != case['runtime']
                    or await NativeQueue(native, item['thread_id'], Path(metadata['cwd'])).list()):
                raise ValueError('Owned exact thread is no longer verified idle with an empty queue')

        async def close_owned(item):
            app = await iterm2.async_get_app(host.connection)
            terminal = app.get_session_by_id(item['terminal_id'])
            if terminal is None:
                if item.get('closed') is True:
                    return
                raise ValueError('Owned terminal disappeared before a close intent')
            endpoint = await inspect_terminal(terminal)
            if (endpoint.process is None or json.loads(json.dumps(asdict(endpoint.process)))
                    != json.loads(json.dumps(item['process']))):
                raise ValueError('Owned terminal process differs from its boot receipt')
            await owned_idle(item)
            item['close_intent'] = True
            save(root, case)
            await terminal.async_close(force=True)
            item['closed'] = True
            save(root, case)

        async def unload(item):
            await native.unsubscribe(item['thread_id'])
            if await native.is_loaded(item['thread_id']):
                # 0.169.0 may retain a thread after unsubscribe. Archive only our
                # closed, exactly verified and idle fixture, as in the existing
                # native lifecycle probe; never infer unloading from a timeout.
                if not item.get('closed') or item.get('archive_intent'):
                    raise ValueError('Only one archive of an exact closed owned fixture is allowed')
                await owned_idle(item)
                item['archive_intent'] = True
                save(root, case)
                await native.rpc.request('thread/archive', {'threadId': item['thread_id']})
                item['archive_confirmed'] = True
                save(root, case)
            async with asyncio.timeout(15):
                while await native.is_loaded(item['thread_id']):
                    await asyncio.sleep(.1)

        if action == 'cleanup':
            for item in case['fixtures']:
                if item.get('phase') != 'ready':
                    raise ValueError('Unconfirmed owned startup needs read-only reconciliation')
                await close_owned(item)
                await native.unsubscribe(item['thread_id'])
            case['phase'] = 'cleaned'
            save(root, case)
            return

        if action == 'run':
            case.update(phase='launching', server_version=native.server_version, runtime=list(native.runtime_identity))
            save(root, case)
        elif list(native.runtime_identity) != case['runtime']:
            raise ValueError('Original runtime changed before reviewed continuation')
        for project in (projects if action == 'run' else ()):
            launch_id = uuid.uuid4().hex
            item = {'name': project.alias, 'launch_id': launch_id, 'phase': 'intent'}
            case['fixtures'].append(item)
            save(root, case)
            await starter.start(launch_id, project, project.root, executable, Path.home() / '.codex', project.alias)
            record = registry.load(launch_id)
            item.update({key: record[key] for key in ('window_id', 'tab_id', 'terminal_id')})
            save(root, case)
            thread = await fixture.bootstrap(native, registry, item)
            binding = await reconcile_launch(registry, launch_id, directory, native)
            if binding.thread_id != thread['id']:
                raise ValueError('Unique owned handshake identity mismatch')
            app = await iterm2.async_get_app(host.connection)
            endpoint = await inspect_terminal(app.get_session_by_id(item['terminal_id']))
            boot = read_json(registry.root / (launch_id + '.boot.json'))
            if (endpoint.process is None or endpoint.process.pid != boot['pid']
                    or list(endpoint.process.started) != boot['started']
                    or endpoint.process.tty_device != boot['tty_device']):
                raise ValueError('Visible owned process does not match its boot')
            item.update(thread_id=thread['id'], native_session_id=thread['sessionId'],
                        process=asdict(endpoint.process), phase='ready')
            save(root, case)
        if len({item['window_id'] for item in case['fixtures']}) != 1:
            raise ValueError('Both owned terminals must share one test window')
        await checkpoint('two_exact_owned_startups')

        state = await RuntimeState.open(root / 'state' / 'runtime.sqlite3', Credentials(
            'fixture-bot', 'fixture-owner', 'https://ilinkai.weixin.qq.com/', 'synthetic'))

        def controller():
            return Controller(projects, SessionCatalog(projects, directory, native), state, starter,
                              executable, Path.home() / '.codex', host=host)

        async def notices():
            return await state._call(lambda: [row[0] for row in state.db.execute(
                "SELECT text FROM outbox WHERE id LIKE 'session-%' ORDER BY rowid")])

        first = controller()
        if action == 'run':
            await first._refresh()
        else:
            await first.restore()
        a, b = [next(s.target for s in first.catalog.sessions.values() if s.target.project_alias == p.alias)
                for p in projects]
        if action == 'run':
            await first.subscriptions.acquire(a, 'route')
            first.routes.focus(a, expected=first.routes.revision)
            await first.subscriptions.acquire(b, 'observer')
            first.routes.attach_confirmed(b, expected=first.routes.revision)
            await state.save_routes(first._snapshot(first.routes))
        original = await state.load_routes()
        case['phase'] = 'selected'
        save(root, case)

        # Close only this probe's native transport, never the shared daemon/TUI.
        if action == 'run':
            await native.close()
            await state.session_notifications.begin()
            started = time.monotonic()
            await state.session_notifications.tick()
            if await notices():
                raise ValueError('Short transport loss unexpectedly notified')
            while time.monotonic() - started < 30.1:
                await asyncio.sleep(.5)
            await state.session_notifications.tick()
            if len(await notices()) != 1 or '连接暂时不可用' not in (await notices())[0]:
                raise ValueError('Real elapsed 30-second disconnect did not produce one fault')
            synthetic = {'message_id': 1, 'from_user_id': 'fixture-owner', 'to_user_id': 'fixture-bot',
                     'message_type': 1, 'message_state': 2, 'create_time_ms': 1, 'seq': 1,
                     'context_token': 'synthetic', 'item_list': [{'type': 1, 'text_item': {'text': '/status'}}]}
            await state.accept_batch({'ret': 0, 'msgs': [synthetic]}, phase='runtime')
            claim = await state.claim_reply()
            await state.finish_reply(claim['id'], 'accepted', 'synthetic-receipt')
            native = await CodexConnection.connect(socket)
            connections.append(native)
        if list(native.runtime_identity) != case['runtime']:
            raise ValueError('Shared runtime changed during dedicated acceptance')
        restored = controller()
        await restored.restore()
        await state.session_notifications.recovered()
        if restored.routes.target != a or restored.routes.observer != b or len(await notices()) != 2:
            raise ValueError('Exact same-runtime reconnect did not restore both roles')
        if '已重新核验并恢复' not in (await notices())[-1]:
            raise ValueError('Accurate reconnect recovery notice missing')
        await checkpoint('real_transport_reconnect_and_30_second_notice')

        item_a, item_b = case['fixtures']
        await close_owned(item_a)
        await owned_idle(item_a)
        again = controller()
        await again.restore()
        if again.routes.target != a or len(await notices()) != 2:
            raise ValueError('Closing only the owned TUI invalidated its loaded native selection')
        await checkpoint('closed_tui_valid_native_is_silent')
        await unload(item_a)
        failed = controller()
        await failed.restore()
        text = (await notices())[-1]
        if (failed.routes.target is not None or failed.routes.observer != b
                or '已不在原生运行时中加载' not in text or '/focus <序号>' not in text
                or '/attach' in text or len(await notices()) != 3):
            raise ValueError('Unloaded input did not preserve and distinguish the valid observer')
        await failed.restore()
        if len(await notices()) != 3:
            raise ValueError('Repeated restoration duplicated a selection notice')
        await checkpoint('unloaded_input_reason_observer_preserved_and_deduplicated')

        history = await state.load_routes()
        history.update(target=history['observer'], mode='focused', last_managed=[original['target']])
        await state.session_notifications.select(history, ('target',))
        historical = controller()
        await historical.restore()
        if historical.routes.target != b or len(await notices()) != 3:
            raise ValueError('Stale history falsely notified or lost the selected input')
        await checkpoint('unloaded_history_only_is_silent')

        await close_owned(item_b)
        await unload(item_b)
        observer_only = await state.load_routes()
        observer_only.update(target=None, mode='unbound')
        await state.save_routes(observer_only)
        await controller().restore()
        text = (await notices())[-1]
        if '/attach <序号>' not in text or '/focus' in text or len(await notices()) != 4:
            raise ValueError('Observer-only failure did not name its own action')
        await checkpoint('observer_only_reason_and_attach_action')
        for item in case['fixtures']:
            page = await native.read_turns(item['thread_id'], limit=20)
            if len(page['data']) != 1 or page.get('nextCursor') or page['data'][0]['status'] != 'completed':
                raise ValueError('Owned thread has unexpected additional work')
            if await native.is_loaded(item['thread_id']):
                raise ValueError('Owned closed thread remains loaded after release')
        if await state.tasks() or case['protected'] != fixture.protected():
            raise ValueError('A task was admitted or protected configuration changed')
        case['phase'] = 'verified_and_closed'
        await checkpoint('two_startup_turns_only_no_wechat_production_or_global_changes')
    except BaseException as error:
        case['failure'] = {'error_type': type(error).__name__, 'message': str(error), 'automatic_replay': False}
        save(root, case)
        raise
    finally:
        if state is not None:
            await state.close()
        for native in connections:
            await native.close()
        await host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run', 'resume-reviewed', 'cleanup'))
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--confirm-dedicated', action='store_true')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not root.resolve().is_relative_to((project / '.tmp').resolve()):
        parser.error('A dedicated case under project .tmp is required')
    os.umask(0o077)
    if args.action == 'prepare':
        prepare(root)
    elif not args.confirm_dedicated:
        parser.error('Explicit dedicated live acceptance confirmation required')
    else:
        asyncio.run(run(root, args.action))
