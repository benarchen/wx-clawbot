"""Explicit owned-TUI target switching; isolated inbox/outbox, never WeChat I/O."""

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.agents.rpc import RpcError
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import (
    ItermWindowStarter, LaunchPending, LaunchRegistry, VisibleStarter, reconcile_launch,
)
from wx_clawbot.output import native_output
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_state import RuntimeState


def protected():
    root = Path.home() / 'Library/Application Support/wx-clawbot'
    paths = [Path.home() / '.codex/config.toml', root / 'config.json',
             root / 'credentials.json', Path.home() / 'Library/LaunchAgents/local.wx-clawbot.plist']
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]


async def terminal_text(session):
    screen = await session.async_get_screen_contents()
    return '\n'.join(screen.line(i).string.replace('\0', ' ') for i in range(screen.number_of_lines))


async def terminal_turn(native, thread_id, client_id):
    async with asyncio.timeout(180):
        while True:
            page = await native.read_turns(thread_id, limit=20)
            if page.get('nextCursor'):
                raise ValueError('Owned history exceeded the exact verification bound')
            matches = [t for t in page['data'] if any(i.get('type') == 'userMessage'
                       and i.get('clientId') == client_id for i in t.get('items', []))]
            if len(matches) > 1:
                raise ValueError('Duplicate client input; no replay allowed')
            if matches and matches[0].get('status') in {'completed', 'failed', 'interrupted'}:
                turn = matches[0]
                if turn['status'] != 'completed':
                    raise ValueError('Owned native input did not complete')
                users = [i for i in turn.get('items', []) if i.get('type') == 'userMessage']
                if len(users) != 1 or any(i.get('type') in {'commandExecution', 'mcpToolCall', 'dynamicToolCall'}
                                          for i in turn.get('items', [])):
                    raise ValueError('Owned read-only task merged inputs or used tools')
                return turn
            await asyncio.sleep(.5)


async def main(args, shared=None):
    import iterm2
    project_root = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not root.resolve().is_relative_to((project_root / '.tmp').resolve()) or not args.confirm_dedicated:
        raise ValueError('Explicit owned resources inside candidate .tmp required')
    private_directory(root)
    path = root / 'case.json'
    if args.action == 'prepare' and path.exists():
        raise FileExistsError('Existing launch intent cannot be repeated')
    case = {} if args.action == 'prepare' else read_json(path)
    home = Path.home() / '.codex'
    host, native = shared if shared is not None else (HostLifecycle(), None)
    state, engine = None, None
    try:
        if shared is None:
            await host.ensure(launch=args.action == 'prepare', explicit=args.action == 'prepare')
            host.verified(host.generation)
        socket, executable = await asyncio.to_thread(discover_runtime, home)
        if native is None:
            native = await CodexConnection.connect(socket)
        directory = ItermDirectory(lifecycle=host)
        registry = LaunchRegistry(root / 'launches')
        project = Project('owned', project_root)
        if args.action == 'prepare':
            case = {'phase': 'launch_intent', 'launch_id': uuid.uuid4().hex,
                    'protected_hashes': protected(), 'runtime_identity': list(native.runtime_identity),
                    'version': native.server_version, 'results': [], 'wechat_sends': 0,
                    'production_ledger_writes': 0}
            write_json(path, case)
            starter = VisibleStarter(registry, ItermWindowStarter(lifecycle=host))
            await starter.start(case['launch_id'], project, project.root, executable, home, 'TGT01-owned')
            async with asyncio.timeout(180):
                while True:
                    try:
                        binding = await reconcile_launch(registry, case['launch_id'], directory, native)
                        break
                    except LaunchPending:
                        await asyncio.sleep(.5)
            case.update(phase='ready', thread_a=binding.thread_id,
                        terminal_id=binding.endpoint.terminal_id, process=asdict(binding.endpoint.process))
            catalog = SessionCatalog((project,), directory, native)
            a = catalog.remember_verified(binding, managed=True, title='A')
            account = Credentials('synthetic-bot', 'synthetic-owner', 'https://ilinkai.weixin.qq.com/', 'synthetic')
            state = await RuntimeState.open(root / 'isolated/runtime.sqlite3', account)
            controller = Controller((project,), catalog, state, VisibleStarter(registry, None), executable, home, host=host)
            await controller._set_focus(a.target, controller.routes.revision, controller.routes, managed=True)
            await state.save_routes(controller._snapshot(controller.routes))
            write_json(path, case, replace=True)
        else:
            if protected() != case['protected_hashes'] or list(native.runtime_identity) != case['runtime_identity']:
                raise ValueError('Protected configuration or native runtime changed')
            app = await iterm2.async_get_app(host.connection)
            session = app.get_session_by_id(case['terminal_id'])
            if session is None:
                raise ValueError('Owned terminal is absent; do not replace it')
            endpoint = await inspect_terminal(session)
            if asdict(endpoint.process) != {**case['process'], 'started': tuple(case['process']['started'])}:
                raise ValueError('Owned terminal process changed')
            if args.action == 'cleanup':
                ledger = root / 'isolated/runtime.sqlite3'
                if ledger.exists():
                    with sqlite3.connect(ledger.as_uri() + '?mode=ro', uri=True) as db:
                        pending = db.execute("SELECT count(*) FROM tasks WHERE state NOT IN "
                                             "('completed','failed','interrupted','cancelled')").fetchone()[0]
                    if pending:
                        raise ValueError('Uncertain owned task requires reconciliation before cleanup')
                for identity in {case['thread_a'], case.get('thread_b'), await directory.current_thread_id(endpoint)} - {None}:
                    thread = await native.inspect(identity)
                    if thread['status']['type'] not in {'idle', 'notLoaded'}:
                        raise ValueError('Owned thread is not idle or unloaded')
                    if thread['status']['type'] == 'idle' and await NativeQueue(native, identity, project.root).list():
                        raise ValueError('Owned queue is not empty')
                await session.async_close(force=True)
                case['phase'] = 'retired_and_cleaned'
                write_json(path, case, replace=True)
                print(json.dumps({'phase': case['phase'], 'verification_claimed': False}), flush=True)
                return
            if args.action == 'switch':
                if case['phase'] != 'ready' or await directory.current_thread_id(endpoint) != case['thread_a']:
                    raise ValueError('Exact original A must still be displayed before switching')
                if await NativeQueue(native, case['thread_a'], project.root).list():
                    raise ValueError('Original A has pending native input')
                await native.observe_loaded(case['thread_a'], project.root)
                case['phase'] = 'desktop_switch_intent'
                write_json(path, case, replace=True)
                await session.async_send_text('/new', suppress_broadcast=True)
                await asyncio.sleep(.3)
                await session.async_send_text('\r', suppress_broadcast=True)
                await asyncio.sleep(1)
                text = await terminal_text(session)
                (root / 'switch-screen.txt').write_text(text)
                print(json.dumps({'phase': case['phase'], 'screen_tail': text[-1800:]}, ensure_ascii=False))
                return
            if args.action == 'inspect':
                text = await terminal_text(session)
                (root / 'inspect-screen.txt').write_text(text)
                original = await native.inspect(case['thread_a'])
                page = await native.list_project_threads(project.root)
                rows = [t for t in page['data'] if t['id'] == case['thread_a']]
                print(json.dumps({'phase': case['phase'], 'screen_tail': text[-1200:],
                    'original_status': original.get('status'), 'original_loaded': await native.is_loaded(case['thread_a']),
                    'original_in_first_page': len(rows),
                    'original_preview_matches': bool(rows and rows[0].get('preview', '').startswith('WX-LAUNCH-' + case['launch_id'])),
                    'has_next_page': bool(page.get('nextCursor'))}, ensure_ascii=False))
                return
            if args.action == 'confirm-switch':
                text = await terminal_text(session)
                if case['phase'] != 'desktop_switch_intent' or not any(
                        line.strip() == '› /new' for line in text.splitlines()):
                    raise ValueError('Only a visibly unsubmitted owned /new may be confirmed')
                await session.async_send_text('\r', suppress_broadcast=True)
                await asyncio.sleep(1)
                print(json.dumps({'screen_tail': (await terminal_text(session))[-1800:]}, ensure_ascii=False))
                return
            if args.action == 'finish-switch':
                text = await terminal_text(session)
                if case['phase'] != 'desktop_switch_intent':
                    raise ValueError('Only the registered desktop switch may finish')
                if any(line.strip() == '› /new' for line in text.splitlines()):
                    await session.async_send_text('\r', suppress_broadcast=True)
                    await asyncio.sleep(1)
                    text = await terminal_text(session)
                if ('Where should the new conversation run?' not in text
                        or '› 1. Use current Git worktree' not in text):
                    raise ValueError('Exact current-worktree menu is not selected; inspect without guessing')
                case['phase'] = 'desktop_b_input_intent'
                case['desktop_marker'] = 'TGT01-DESKTOP-B-' + uuid.uuid4().hex
                write_json(path, case, replace=True)
                await session.async_send_text('\r', suppress_broadcast=True)
                await asyncio.sleep(1)
                await session.async_send_text('只回复 ' + case['desktop_marker'] + '。不要调用工具，不修改文件。',
                                              suppress_broadcast=True)
                await asyncio.sleep(.3)
                await session.async_send_text('\r', suppress_broadcast=True)
                await finish_desktop(native, directory, endpoint, case, path)
                print(json.dumps({'phase': case['phase'], 'same_process_different_thread': True}), flush=True)
                return
            if args.action == 'reconcile-desktop':
                if case['phase'] != 'desktop_b_input_intent':
                    raise ValueError('Only the existing desktop input may be reconciled, never resent')
                await finish_desktop(native, directory, endpoint, case, path)
                print(json.dumps({'phase': case['phase'], 'input_replayed': False}), flush=True)
                return
            if args.action == 'verify':
                if case['phase'] != 'desktop_b_ready':
                    raise ValueError('Only an unverified desktop switch may execute once')
                current = await directory.current_thread_id(endpoint)
                if current is None or current == case['thread_a']:
                    raise ValueError('A new B is not yet visibly established')
                case.update(phase='verification_intent', thread_b=current)
                write_json(path, case, replace=True)
                before_b = await native.read_turns(current, limit=20)
                binding = await reconcile_launch(registry, case['launch_id'], directory, native)
                if binding.thread_id != case['thread_a']:
                    raise ValueError('Ready launch was retargeted to desktop B')
                catalog = SessionCatalog((project,), directory, native)
                catalog.managed_threads.add(binding.thread_id)
                a = catalog.remember_verified(binding, managed=True, title='A')
                found = await catalog.discover()
                b = next(s for s in found if s.binding.thread_id == current
                         and s.binding.endpoint == endpoint)
                account = Credentials('synthetic-bot', 'synthetic-owner', 'https://ilinkai.weixin.qq.com/', 'synthetic')
                state = await RuntimeState.open(root / 'isolated/runtime.sqlite3', account)
                controller = Controller((project,), catalog, state, VisibleStarter(registry, None), executable, home, host=host)
                engine = Execution(controller)
                await controller.restore()
                if controller.routes.target != a.target:
                    raise ValueError('The explicit A selection made before desktop switching was lost')
                counter = 0

                async def incoming(text):
                    nonlocal counter
                    counter += 1
                    raw = {'message_id': counter, 'from_user_id': account.owner_id, 'to_user_id': account.bot_id,
                           'message_type': 1, 'message_state': 2, 'seq': counter, 'create_time_ms': counter,
                           'context_token': 'synthetic', 'item_list': [{'type': 1, 'text_item': {'text': text}}]}
                    return (await state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime'))['accepted'][0]

                async def submit_to(target, label):
                    marker = 'TGT01-' + label + '-' + uuid.uuid4().hex
                    prompt = '只回复 ' + marker + '。不要调用工具，不读取或修改文件。'
                    if label == 'hidden-A':
                        marker = 'WX-LAUNCH-' + case['launch_id']
                        prompt = '只回复这段对话启动时的完整 WX-LAUNCH- 标记。不要调用工具，不读取或修改文件。'
                    if label == 'hidden-A':
                        if controller.routes.target != target:
                            raise ValueError('Desktop B passively changed the selected A')
                    else:
                        await controller._set_focus(target, controller.routes.revision, controller.routes)
                    await controller.state.save_routes(controller._snapshot(controller.routes))
                    message = await incoming(prompt)
                    await controller.prepare(message)
                    tasks = await state.tasks()
                    task = next(t for t in tasks if t['source_message_id'] == message.message_id)
                    expected = (await catalog.require(target)).binding.thread_id
                    if task['thread_id'] != expected or controller.routes.target != target:
                        raise ValueError('WeChat selection or frozen task target changed')
                    turn = await terminal_turn(native, expected, task['client_id'])
                    if marker not in native_output(turn):
                        raise ValueError('Exact original thread did not return the owned marker')
                    await engine.complete(expected, turn)
                    case['results'].append({'case': label, 'status': turn['status'], 'thread_id': expected,
                                            'turn_id': turn['id'], 'client_id': task['client_id']})
                    write_json(path, case, replace=True)
                    return task

                task_a = await submit_to(a.target, 'hidden-A')
                after_b = await native.read_turns(current, limit=20)
                if after_b != before_b or await directory.current_thread_id(endpoint) != current:
                    raise ValueError('Sending to A changed desktop B or its native history')
                task_b = await submit_to(b.target, 'explicit-B')
                if task_a['thread_id'] == task_b['thread_id']:
                    raise ValueError('Explicit selection did not switch threads')
                for identity in (case['thread_a'], current):
                    if (await native.inspect(identity))['status']['type'] != 'idle':
                        raise ValueError('Owned native task is not idle before terminal close')
                    if await NativeQueue(native, identity, project.root).list():
                        raise ValueError('Owned queue is not empty before terminal close')
                case['phase'] = 'close_intent'
                write_json(path, case, replace=True)
                await session.async_close(force=True)
                await asyncio.sleep(.5)
                before_count = len(await state.tasks())
                await controller.prepare(await incoming('此消息必须因原终端退出而被拒绝。'))
                rows = await state._call(lambda: list(state.db.execute('SELECT text FROM outbox')))
                if (len(await state.tasks()) != before_count or controller.routes.target != b.target
                        or not any('所选会话无法可靠接入' in row[0] for row in rows)):
                    raise ValueError('Closed target was replaced, submitted or failed without a clear notice')
                case.update(phase='verified_and_cleaned', hidden_a_completed=True, explicit_b_completed=True,
                            desktop_b_unchanged=True, closed_target_refused=True, a_context_recalled=True)
                write_json(path, case, replace=True)
        if protected() != case['protected_hashes']:
            raise ValueError('Protected configuration changed')
        print(json.dumps({k: v for k, v in case.items() if k in {
            'phase', 'version', 'hidden_a_completed', 'explicit_b_completed', 'desktop_b_unchanged',
            'closed_target_refused', 'a_context_recalled', 'wechat_sends', 'production_ledger_writes'}}, ensure_ascii=False), flush=True)
    finally:
        if engine:
            await engine.close()
        if state:
            await state.close()
        if shared is None:
            if native:
                await native.close()
            await host.close()


async def finish_desktop(native, directory, endpoint, case, path):
    async with asyncio.timeout(180):
        while True:
            current = await directory.current_thread_id(endpoint)
            if current and current != case['thread_a']:
                try:
                    page = await native.read_turns(current, limit=20)
                except RpcError as exc:
                    if 'rollout' not in str(exc) or 'is empty' not in str(exc):
                        raise
                    await asyncio.sleep(.5)
                    continue
                completed = [t for t in page['data'] if t.get('status') == 'completed'
                             and case['desktop_marker'] in native_output(t)]
                if len(completed) == 1:
                    break
            await asyncio.sleep(.5)
    case.update(phase='desktop_b_ready', thread_b=current)
    write_json(path, case, replace=True)


async def continuous(args):
    project = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not args.confirm_dedicated or not root.resolve().is_relative_to((project / '.tmp').resolve()):
        raise ValueError('Explicit owned resources inside candidate .tmp required')
    if (root / 'case.json').exists():
        raise FileExistsError('Existing continuous workflow cannot be replayed')
    host, native = HostLifecycle(), None
    try:
        await host.ensure(launch=True, explicit=True)
        host.verified(host.generation)
        socket, _ = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        for action in ('prepare', 'switch', 'finish-switch', 'verify'):
            args.action = action
            await main(args, (host, native))
    finally:
        if native:
            await native.close()
        await host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('continuous', 'prepare', 'switch', 'inspect', 'confirm-switch', 'finish-switch',
                                         'reconcile-desktop', 'verify', 'cleanup'))
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--confirm-dedicated', action='store_true')
    arguments = parser.parse_args()
    asyncio.run(continuous(arguments) if arguments.action == 'continuous' else main(arguments))
