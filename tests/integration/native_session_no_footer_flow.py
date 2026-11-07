"""Explicit TGT02 controller acceptance on owned no-ID terminals; no WeChat I/O."""

import argparse
import asyncio
from contextlib import ExitStack
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import uuid
from unittest.mock import patch

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution, restore_target
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, VisibleStarter
from wx_clawbot.output import native_output
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.routing import RouteError


spec = importlib.util.spec_from_file_location('owned_no_footer', Path(__file__).with_name('native_session_no_footer.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


async def main(args):
    import iterm2
    workspace = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not args.confirm_dedicated or not root.resolve().is_relative_to((workspace / '.tmp').resolve()):
        raise ValueError('Explicit owned case under project .tmp required')
    case_path, result_path = root / 'case.json', root / 'flow.json'
    if result_path.exists():
        raise FileExistsError('An existing acceptance intent cannot be replayed')
    case = read_json(case_path)
    if case['phase'] != 'probe_verified' or fixture.protected() != case['protected_hashes']:
        raise ValueError('Verified no-ID fixtures and unchanged configuration required')
    flow = {'phase': 'intent', 'checks': {}, 'inputs': [], 'wechat_sends': 0, 'production_writes': 0}
    write_json(result_path, flow)

    def save(phase=None, **checks):
        if phase:
            flow['phase'] = phase
        flow['checks'].update(checks)
        write_json(result_path, flow, replace=True)
        print(json.dumps({'phase': flow['phase'], 'checks': checks}), flush=True)

    host, native, state, engine = HostLifecycle(), None, None, None
    controller = catalog = None
    jobs = []
    counter = 1000
    account = Credentials('synthetic-tgt02', 'synthetic-owner', 'https://ilinkai.weixin.qq.com/', 'synthetic')
    try:
        await host.ensure(launch=False, explicit=False)
        host.verified(host.generation)
        socket, executable = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        if list(native.runtime_identity) != case['runtime']:
            raise ValueError('The original fixture runtime changed')
        flow['version'] = native.server_version
        app = await iterm2.async_get_app(host.connection)
        a, obsolete = case['fixtures']

        async def own_session(record):
            app = await iterm2.async_get_app(host.connection)
            session = app.get_session_by_id(record['terminal_id'])
            if session is None:
                raise ValueError('Owned fixture is absent; never replace it')
            endpoint = await inspect_terminal(session)
            expected = {**record['process'], 'started': tuple(record['process']['started'])}
            if endpoint.process is None or asdict(endpoint.process) != expected:
                raise ValueError('Owned process changed')
            return session

        async def close_owned(record):
            session = await own_session(record)
            thread = await native.inspect(record['thread_id'])
            if thread['status']['type'] != 'idle' or await NativeQueue(native, thread['id'], workspace).list():
                raise ValueError('Owned native work must be terminal and queue empty before closing')
            await session.async_close(force=True)

        await close_owned(obsolete)
        obsolete['phase'] = 'retired'
        write_json(case_path, case, replace=True)
        a_session = await own_session(a)
        if not await fixture.hidden(a_session, await native.inspect(a['thread_id'])):
            raise ValueError('Existing fixture identity is displayed')
        directory = ItermDirectory(lifecycle=host)
        creator = ItermWindowStarter(lifecycle=host, owned_window_id=a['window_id'])
        creator.host_generation = host.generation
        registry = fixture.HiddenRegistry(root / 'candidate-launches', socket)
        starter = VisibleStarter(registry, creator)
        project = Project('owned', workspace)

        async def start_controller(*, restore=False):
            nonlocal state, engine, controller, catalog, jobs
            state = await RuntimeState.open(root / 'flow-state/runtime.sqlite3', account)
            catalog = SessionCatalog((project,), directory, native)
            controller = Controller((project,), catalog, state, starter, executable, Path.home() / '.codex',
                                    host=host, launch_timeout=180)
            engine = Execution(controller)
            if restore:
                await controller.restore()
            jobs = [asyncio.create_task(engine.run()), asyncio.create_task(engine.maintain())]

        async def stop_controller():
            nonlocal state, engine, jobs
            for job in jobs:
                job.cancel()
            results = await asyncio.gather(*jobs, return_exceptions=True)
            errors = [r for r in results if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError)]
            await engine.close()
            await state.close()
            jobs, engine, state = [], None, None
            if errors:
                raise RuntimeError('Candidate event worker failed') from errors[0]

        async def incoming(text):
            nonlocal counter
            counter += 1
            raw = {'message_id': counter, 'from_user_id': account.owner_id, 'to_user_id': account.bot_id,
                   'message_type': 1, 'message_state': 2, 'seq': counter, 'create_time_ms': counter,
                   'context_token': 'synthetic', 'item_list': [{'type': 1, 'text_item': {'text': text}}]}
            return (await state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime'))['accepted'][0]

        def screen_forbidden(*_args, **_kwargs):
            raise AssertionError('Routing attempted to read displayed native identity')

        async def command(text):
            message = await incoming(text)
            with ExitStack() as stack:
                stack.enter_context(patch.object(ItermDirectory, 'current_thread_id', screen_forbidden))
                stack.enter_context(patch.object(iterm2.Session, 'async_get_screen_contents', screen_forbidden))
                await controller.prepare(message)
            return message

        async def select(label, expected):
            await command('/sessions ' + label)
            targets = controller.routes.list.targets
            if len(targets) != 1:
                raise ValueError('Human-readable explicit selection is ambiguous')
            await command('/focus 1')
            target = controller.routes.target
            if (await catalog.require(target)).binding.thread_id != expected:
                raise ValueError('Explicit native selection changed identity')
            return target

        async def submit(label, expected, marker):
            intent = {'label': label, 'thread_id': expected, 'phase': 'intent'}
            flow['inputs'].append(intent)
            save()
            message = await command('只回复这段对话启动时的完整 WX-LAUNCH- 标记。不要调用工具，不读取或修改文件。')
            tasks = [t for t in await state.tasks() if t['source_message_id'] == message.message_id]
            if len(tasks) != 1 or tasks[0]['thread_id'] != expected:
                raise ValueError('Accepted task was redirected or duplicated')
            task = tasks[0]
            intent.update(task_id=task['id'], client_id=task['client_id'], phase='submitted')
            save()
            turn = await fixture.completed(native, expected, task['client_id'])
            if marker not in native_output(turn):
                raise ValueError('Original context was not retained')
            async with asyncio.timeout(20):
                while (await state.tasks(task_id=task['id']))['state'] != 'completed':
                    for job in jobs:
                        if job.done():
                            job.result()
                    await asyncio.sleep(.1)
            intent.update(phase='completed', turn_id=turn['id'])
            if label == 'existing-first-entry':
                count = len(await state.tasks())
                await controller.prepare(message)
                if len(await state.tasks()) != count:
                    raise ValueError('Repeated inbound identity created another native task')
                flow['checks']['duplicate_inbound_single_task'] = True
            save()
            return task

        await start_controller()
        a_target = await select('TGT02-existing', a['thread_id'])
        await submit('existing-first-entry', a['thread_id'], 'WX-LAUNCH-' + a['launch_id'])
        save('existing_verified', existing_no_screen_first_entry=True)
        # The candidate creates B, rather than remembering the prototype's B.
        create = controller.prepare(await incoming('/new TGT02-managed'))
        try:
            controller.prepare(await incoming('/new concurrent-must-be-refused'))
        except RouteError:
            save(concurrent_creation_explicitly_refused=True)
        else:
            create.close()
            raise ValueError('Concurrent selection was not refused before creation')
        with patch.object(ItermDirectory, 'current_thread_id', screen_forbidden), \
                patch.object(iterm2.Session, 'async_get_screen_contents', screen_forbidden):
            await create
        b_target = controller.routes.target
        b_binding = (await catalog.require(b_target)).binding
        records = [registry.load(p.stem) for p in registry.root.glob('*.json') if not p.name.endswith('.boot.json')]
        if len(records) != 1 or records[0]['phase'] != 'ready':
            raise ValueError('Visible creation did not produce one exact ready record')
        b = records[0]
        if b_binding.thread_id == a['thread_id'] or b['window_id'] != a['window_id']:
            raise ValueError('Visible creation replaced A or escaped the owned window')
        b_session = await own_session(b)
        await fixture.hidden(b_session, await native.inspect(b_binding.thread_id))
        await submit('created-first-entry', b_binding.thread_id, 'WX-LAUNCH-' + b['launch_id'])
        # Same launch identity must not create another tab, even after ready.
        await starter.start(b['launch_id'], project, workspace, executable, Path.home() / '.codex', 'TGT02-managed')
        app = await iterm2.async_get_app(host.connection)
        if len(app.get_window_by_id(a['window_id']).tabs) != 2:
            raise ValueError('Duplicate launch created an extra owned tab')
        await command('/cd owned')
        if controller.routes.target != b_target:
            raise ValueError('cd did not reuse exact managed B')
        await select('TGT02-existing', a['thread_id'])
        await command('/attach 1')
        if controller.routes.observer != a_target or controller.routes.target != a_target:
            raise ValueError('Independent native observer not confirmed')
        await command('/detach')
        if controller.routes.observer is not None or controller.routes.target != a_target:
            raise ValueError('Detach changed input focus')
        await submit('switch-back-A', a['thread_id'], 'WX-LAUNCH-' + a['launch_id'])
        await select('TGT02-managed', b_binding.thread_id)
        await submit('switch-back-B', b_binding.thread_id, 'WX-LAUNCH-' + b['launch_id'])
        save('switch_verified', candidate_visible_handshake=True, hidden_created=True, explicit_switch=True,
             cd_reuse=True, independent_observer=True, duplicate_launch_no_extra_tab=True)

        # A real bridge-side connection restart, with both original TUIs alive.
        await stop_controller()
        await native.close()
        native = await CodexConnection.connect(socket)
        await start_controller(restore=True)
        if controller.routes.target != b_target:
            raise ValueError('Same-generation bridge restart did not restore B and its stable number')
        await submit('restart-B', b_binding.thread_id, 'WX-LAUNCH-' + b['launch_id'])
        save('restart_verified', exact_restart_restore=True, stable_number=True)

        # Change the dialogue shown by the same owned TUI while WeChat keeps A.
        await select('TGT02-existing', a['thread_id'])
        desktop_marker = 'TGT02-DESKTOP-' + uuid.uuid4().hex
        flow.update(desktop_marker=desktop_marker, desktop_terminal=a['terminal_id'])
        save('desktop_switch_intent')
        await a_session.async_send_text('/new', suppress_broadcast=True)
        await asyncio.sleep(.3)
        await a_session.async_send_text('\r', suppress_broadcast=True)
        await asyncio.sleep(1)

        async def displayed():
            screen = await a_session.async_get_screen_contents()
            return '\n'.join(screen.line(i).string.replace('\0', ' ') for i in range(screen.number_of_lines))

        text = await displayed()
        if any(line.strip() == '› /new' for line in text.splitlines()):
            await a_session.async_send_text('\r', suppress_broadcast=True)
            await asyncio.sleep(1)
            text = await displayed()
        if ('Where should the new conversation run?' not in text
                or '› 1. Use current Git worktree' not in text):
            (root / 'desktop-menu.txt').write_text(text)
            raise ValueError('Exact owned current-worktree menu was not confirmed')
        await a_session.async_send_text('\r', suppress_broadcast=True)
        await asyncio.sleep(1)
        prompt = '只回复 ' + desktop_marker + '。不要调用工具，不读取或修改文件。'
        save('desktop_input_intent')
        await a_session.async_send_text(prompt, suppress_broadcast=True)
        await asyncio.sleep(.3)
        await a_session.async_send_text('\r', suppress_broadcast=True)
        async with asyncio.timeout(180):
            while True:
                rows = [t for t in await fixture.project_threads(native, workspace)
                        if t.get('preview', '').startswith(prompt)]
                if len(rows) > 1:
                    raise ValueError('Desktop switch produced ambiguous native candidates')
                if rows:
                    turns = (await native.read_turns(rows[0]['id'], limit=20))['data']
                    done = [t for t in turns if t.get('status') == 'completed' and desktop_marker in native_output(t)]
                    if done:
                        if len(done) != 1 or any(i.get('type') in {'commandExecution', 'mcpToolCall', 'dynamicToolCall'}
                                                for i in done[0].get('items', [])):
                            raise ValueError('Desktop input was duplicated or used tools')
                        desktop_thread = rows[0]['id']
                        flow.update(desktop_thread=desktop_thread, desktop_turn=done[0]['id'])
                        break
                await asyncio.sleep(.5)
        if desktop_thread == a['thread_id'] or not await native.is_loaded(a['thread_id']):
            raise ValueError('Desktop change did not retain distinct original A')
        await own_session(a)  # The Codex process must be unchanged.
        before_desktop = await native.read_turns(desktop_thread, limit=20)
        await fixture.hidden(a_session, await native.inspect(desktop_thread))
        await submit('same-process-desktop-switch-A', a['thread_id'], 'WX-LAUNCH-' + a['launch_id'])
        if await native.read_turns(desktop_thread, limit=20) != before_desktop:
            raise ValueError('WeChat A changed the dialogue now shown by the desktop')
        save('desktop_switch_verified', same_process_desktop_switch=True, desktop_dialogue_unchanged=True)

        # Close only owned A while its native subscription still holds the thread.
        if (await native.inspect(desktop_thread))['status']['type'] != 'idle' or await NativeQueue(
                native, desktop_thread, workspace).list():
            raise ValueError('Desktop dialogue is not terminal with an empty queue')
        await close_owned(a)
        await asyncio.sleep(.5)
        if not await native.is_loaded(a['thread_id']):
            raise ValueError('Expected the verified observer to retain A after its TUI closed')
        await submit('closed-but-loaded-A', a['thread_id'], 'WX-LAUNCH-' + a['launch_id'])
        # Drop this verifier's exact native subscription; do not hydrate an archive.
        await native.unsubscribe(a['thread_id'])
        async with asyncio.timeout(180):
            while await native.is_loaded(a['thread_id']):
                await asyncio.sleep(.1)
        count = len(await state.tasks())
        before_target = controller.routes.target
        await command('此消息必须因准确原生会话卸载而被拒绝。')
        texts = await state._call(lambda: [r[0] for r in state.db.execute('SELECT text FROM outbox')])
        if (len(await state.tasks()) != count or controller.routes.target != before_target
                or not any('所选会话无法可靠接入' in t and '不会自动切换' in t for t in texts)):
            raise ValueError('Unloaded target was submitted, replaced or lacked a clear failure notice')
        save('close_verified', closed_loaded_still_executes=True, unloaded_refused_without_retarget=True)
        if any(t['state'] not in {'completed', 'failed', 'interrupted', 'cancelled'} for t in await state.tasks()):
            raise ValueError('Uncertain candidate work must not be cleaned up')
        await close_owned(b)
        await stop_controller()
        if fixture.protected() != case['protected_hashes']:
            raise ValueError('Protected production/global configuration changed')
        save('verified_and_cleaned', owned_terminals_closed=True, protected_configuration_unchanged=True,
             business_tools=0, screen_identity_reads=0)
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


async def finish(args):
    """Read-only completion after native delayed unloading; never replay business input."""
    import iterm2
    workspace = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not args.confirm_dedicated or not root.resolve().is_relative_to((workspace / '.tmp').resolve()):
        raise ValueError('Explicit owned case required')
    case, flow = read_json(root / 'case.json'), read_json(root / 'flow.json')
    if (flow['phase'] != 'desktop_switch_verified' or not flow['inputs']
            or any(i['phase'] != 'completed' for i in flow['inputs'])
            or flow['inputs'][-1]['label'] != 'closed-but-loaded-A'):
        raise ValueError('Only completed original work awaiting native unload may finish')
    host, native, state, engine = HostLifecycle(), None, None, None
    try:
        if fixture.protected() != case['protected_hashes']:
            raise ValueError('Protected configuration changed')
        await host.ensure(launch=False, explicit=False)
        host.verified(host.generation)
        socket, executable = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        if list(native.runtime_identity) != case['runtime']:
            raise ValueError('Original native generation changed')
        a = case['fixtures'][0]
        app = await iterm2.async_get_app(host.connection)
        if app.get_session_by_id(a['terminal_id']) is not None:
            raise ValueError('The original owned TUI has not closed')
        if (await native.inspect(a['thread_id']))['status']['type'] != 'notLoaded' or await native.is_loaded(a['thread_id']):
            raise ValueError('Native unloading is not yet confirmed; do not force it')
        registry = fixture.HiddenRegistry(root / 'candidate-launches', socket)
        account = Credentials('synthetic-tgt02', 'synthetic-owner', 'https://ilinkai.weixin.qq.com/', 'synthetic')
        state = await RuntimeState.open(root / 'flow-state/runtime.sqlite3', account)
        snapshot = await state.load_routes()
        if snapshot['target']['thread_id'] != a['thread_id']:
            raise ValueError('The saved explicit A selection changed')
        project = Project('owned', workspace)
        catalog = SessionCatalog((project,), ItermDirectory(lifecycle=host), native)
        controller = Controller((project,), catalog, state, VisibleStarter(registry, None), executable,
                                Path.home() / '.codex', host=host)
        # Model the retained explicit selection at the instant unloading was
        # observed, not a new routing grant or successful restart restoration.
        target = restore_target(snapshot['target'])
        controller.routes.target, controller.routes.mode = target, snapshot['mode']
        controller.routes.project, controller.routes.cwd = project, workspace
        engine = Execution(controller)
        tasks = await state.tasks()
        if any(t['state'] != 'completed' for t in tasks):
            raise ValueError('Uncertain original task requires reconciliation first')
        before = await native.read_turns(a['thread_id'], limit=20)
        raw = {'message_id': 999001, 'from_user_id': account.owner_id, 'to_user_id': account.bot_id,
               'message_type': 1, 'message_state': 2, 'seq': 999001, 'create_time_ms': 999001,
               'context_token': 'synthetic', 'item_list': [{'type': 1, 'text_item': {
                   'text': '此消息必须因准确原生会话卸载而被拒绝。'}}]}
        accepted = (await state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime'))['accepted']
        if len(accepted) != 1:
            raise ValueError('The failed-path input already exists; never replay it')
        def forbidden(*_args, **_kwargs):
            raise AssertionError('Unloaded target attempted submission, resume or screen identity access')
        with patch.object(ItermDirectory, 'current_thread_id', forbidden), \
                patch.object(iterm2.Session, 'async_get_screen_contents', forbidden), \
                patch.object(native, 'observe_loaded', forbidden), patch.object(NativeQueue, 'add', forbidden):
            await controller.prepare(accepted[0])
        texts = await state._call(lambda: [r[0] for r in state.db.execute('SELECT text FROM outbox')])
        if (len(await state.tasks()) != len(tasks) or controller.routes.target != target
                or not any('所选会话无法可靠接入' in t and '不会自动切换' in t for t in texts)
                or await native.is_loaded(a['thread_id']) or await native.read_turns(a['thread_id'], limit=20) != before):
            raise ValueError('Unloaded target did not fail with unchanged history and explicit notice')
        records = [registry.load(p.stem) for p in registry.root.glob('*.json') if not p.name.endswith('.boot.json')]
        if len(records) != 1:
            raise ValueError('Unexpected owned creation count')
        b = records[0]
        session = app.get_session_by_id(b['terminal_id'])
        if session is None:
            raise ValueError('Owned B cleanup source disappeared')
        endpoint = await inspect_terminal(session)
        if asdict(endpoint.process) != {**b['process'], 'started': tuple(b['process']['started'])}:
            raise ValueError('Owned B process changed before cleanup')
        if (await native.inspect(b['thread_id']))['status']['type'] != 'idle' or await NativeQueue(
                native, b['thread_id'], workspace).list():
            raise ValueError('Owned B is not idle with an empty queue')
        await session.async_close(force=True)
        if fixture.protected() != case['protected_hashes']:
            raise ValueError('Protected configuration changed')
        flow.update(phase='verified_and_cleaned', unload_confirmation='deferred_native_notLoaded')
        flow['checks'].update(closed_loaded_still_executes=True, unloaded_refused_without_retarget=True,
                              owned_terminals_closed=True, protected_configuration_unchanged=True,
                              business_tools=0, screen_identity_reads=0)
        write_json(root / 'flow.json', flow, replace=True)
        print(json.dumps({'phase': flow['phase'], 'checks': flow['checks'],
                          'unload_confirmation': flow['unload_confirmation']}), flush=True)
    finally:
        if engine:
            await engine.close()
        if state:
            await state.close()
        if native:
            await native.close()
        await host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--confirm-dedicated', action='store_true')
    parser.add_argument('--finish', action='store_true')
    args = parser.parse_args()
    asyncio.run(finish(args) if args.finish else main(args))
