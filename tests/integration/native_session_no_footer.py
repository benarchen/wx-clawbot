"""Explicit TGT02 owned TUI without displayed IDs; no real WeChat or production writes."""

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.config import Project
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.process import read_process
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter
from wx_clawbot.launcher import launch_argv
from wx_clawbot.output import native_output
from wx_clawbot.runtime_discovery import discover_runtime


class HiddenRegistry(LaunchRegistry):
    def __init__(self, root, socket=None):
        super().__init__(root)
        self.socket = socket

    def prepare(self, *args, **kwargs):
        record = super().prepare(*args, **kwargs)
        if self.socket is not None:
            if record.get('socket') not in {None, str(self.socket)}:
                raise ValueError('Owned runtime endpoint changed')
            record['socket'] = str(self.socket)
            self.save(record)
        return record

    def command(self, launch_id):
        self.load(launch_id)
        return shlex.join([str(Path(sys.executable).absolute()), '-I', str(Path(__file__).resolve()),
                           'launch', '--case-dir', str(self.root.parent), '--registry', str(self.root),
                           '--launch-id', launch_id])


def launch(args):
    registry = HiddenRegistry(args.registry or args.case_dir / 'launches')
    record = registry.load(args.launch_id)
    if record['phase'] not in {'starting', 'handshaking'}:
        raise ValueError('Only an active owned launch may start')
    argv = launch_argv(record)
    identity = read_process(os.getpid())
    if identity is None:
        raise ValueError('Owned launcher process cannot be verified')
    write_json(registry.root / (args.launch_id + '.boot.json'),
               {'launch_id': args.launch_id, 'pid': identity.pid, 'started': identity.started,
                'tty_device': identity.tty_device})
    argv = [*argv[:-1], '--remote', 'unix://' + record['socket'], '-c',
            'tui.status_line=["model-name","context-remaining"]', argv[-1]]
    os.chdir(record['cwd'])
    os.environ.pop('WX_CLAWBOT_RELEASE_MANIFEST', None)
    os.execv(argv[0], argv)


def protected():
    root = Path.home() / 'Library/Application Support/wx-clawbot'
    paths = [Path.home() / '.codex/config.toml', root / 'config.json', root / 'credentials.json',
             Path.home() / 'Library/LaunchAgents/local.wx-clawbot.plist']
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]


async def project_threads(native, project):
    rows, cursor, seen = [], None, set()
    for _ in range(10):
        page = await native.list_project_threads(project, cursor=cursor)
        rows.extend(page['data'])
        cursor = page.get('nextCursor')
        if cursor is None:
            return rows
        if cursor in seen:
            raise ValueError('Cyclic native page')
        seen.add(cursor)
    raise ValueError('Owned verification exceeded the project page bound')


async def bootstrap(native, registry, fixture):
    record = registry.load(fixture['launch_id'])
    marker = 'WX-LAUNCH-' + fixture['launch_id']
    async with asyncio.timeout(180):
        while True:
            rows = await project_threads(native, Path(record['cwd']))
            matches = [t for t in rows if t.get('preview', '').startswith(marker)
                       and t.get('forkedFromId') is None]
            if len(matches) > 1:
                raise ValueError('Owned handshake has multiple native candidates')
            if len(matches) == 1:
                thread = await native.inspect(matches[0]['id'])
                if await native.is_loaded(thread['id']):
                    turns = (await native.read_turns(thread['id'], limit=1))['data']
                    if turns and turns[0].get('status') == 'completed':
                        users = [i for i in turns[0].get('items', []) if i.get('type') == 'userMessage']
                        if len(users) != 1 or not any(c.get('text', '').startswith(marker)
                                for c in users[0].get('content', [])) or marker not in native_output(turns[0]):
                            raise ValueError('Owned native startup input/reply does not match')
                        return thread
            await asyncio.sleep(.5)


async def hidden(session, thread):
    screen = await session.async_get_screen_contents()
    text = '\n'.join(screen.line(i).string.replace('\0', ' ') for i in range(screen.number_of_lines))
    title = await session.async_get_variable('session.name')
    if not isinstance(title, str):
        raise ValueError('Owned terminal title cannot be verified')
    if any(identity in text or identity in title for identity in {thread['id'], thread['sessionId']}):
        raise ValueError('Owned screen/title still displays native identity')
    return True


async def completed(native, thread_id, client_id):
    async with asyncio.timeout(180):
        while True:
            page = await native.read_turns(thread_id, limit=20)
            if page.get('nextCursor'):
                raise ValueError('Owned history exceeds bound')
            matches = [t for t in page['data'] if any(i.get('type') == 'userMessage' and i.get('clientId') == client_id
                                                   for i in t.get('items', []))]
            if len(matches) > 1:
                raise ValueError('Duplicate native client input')
            if matches and matches[0].get('status') in {'completed', 'failed', 'interrupted'}:
                turn = matches[0]
                if turn['status'] != 'completed' or any(i.get('type') in {'commandExecution', 'mcpToolCall', 'dynamicToolCall'}
                                                       for i in turn.get('items', [])):
                    raise ValueError('Owned business input failed or called tools')
                if len([i for i in turn['items'] if i.get('type') == 'userMessage']) != 1:
                    raise ValueError('Owned business input merged with another input')
                return turn
            await asyncio.sleep(.5)


async def main(args):
    import iterm2
    workspace = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not args.confirm_dedicated or not root.resolve().is_relative_to((workspace / '.tmp').resolve()):
        raise ValueError('Explicit dedicated case inside project .tmp required')
    path = root / 'case.json'
    if args.action == 'probe' and path.exists():
        raise FileExistsError('Owned intent cannot be repeated')
    private_directory(root)
    home = Path.home() / '.codex'
    host, native = HostLifecycle(), None
    try:
        await host.ensure(launch=args.action == 'probe', explicit=args.action == 'probe')
        host.verified(host.generation)
        socket, executable = await asyncio.to_thread(discover_runtime, home)
        native = await CodexConnection.connect(socket)
        directory = ItermDirectory(lifecycle=host)
        registry = HiddenRegistry(root / 'launches')
        if args.action == 'probe':
            case = {'phase': 'preparing', 'server_version': native.server_version, 'runtime': list(native.runtime_identity),
                    'protected_hashes': protected(), 'fixtures': [], 'inputs': [], 'wechat_sends': 0,
                    'direct_production_writes': 0}
            write_json(path, case)
            starter = VisibleStarter(registry, ItermWindowStarter(lifecycle=host))
            project = Project('owned', workspace)
            for label in ('existing', 'created'):
                launch_id = uuid.uuid4().hex
                record = registry.prepare(launch_id, project, project.root, executable, home, 'TGT02-' + label)
                record['socket'] = str(socket)
                registry.save(record)
                fixture = {'launch_id': launch_id, 'label': label, 'phase': 'launch_intent'}
                case['fixtures'].append(fixture)
                write_json(path, case, replace=True)
                await starter.start(launch_id, project, project.root, executable, home, 'TGT02-' + label)
                launch_record = registry.load(launch_id)
                fixture.update({k: launch_record[k] for k in ('terminal_id', 'window_id', 'tab_id')})
                write_json(path, case, replace=True)
                thread = await bootstrap(native, registry, fixture)
                app = await iterm2.async_get_app(host.connection)
                session = app.get_session_by_id(fixture['terminal_id'])
                endpoint = await inspect_terminal(session)
                boot = read_json(registry.root / (launch_id + '.boot.json'))
                if (endpoint.process is None or endpoint.process.pid != boot['pid']
                        or list(endpoint.process.started) != boot['started'] or endpoint.process.tty_device != boot['tty_device']):
                    raise ValueError('Owned startup process differs from boot receipt')
                fixture.update(thread_id=thread['id'], native_session_id=thread['sessionId'],
                               process=asdict(endpoint.process), hidden=await hidden(session, thread), phase='ready')
                await native.rpc.request('thread/name/set', {'threadId': thread['id'], 'name': 'TGT02-' + label})
                # A fresh backend selection, without a screen-derived binding.
                candidates = [t for t in await project_threads(native, workspace) if t.get('name') == 'TGT02-' + label]
                if len(candidates) != 1 or candidates[0]['id'] != thread['id']:
                    raise ValueError('Explicit backend selection is ambiguous')
                selected = await native.inspect(candidates[0]['id'])
                if selected['cwd'] != str(workspace) or not await native.is_loaded(selected['id']):
                    raise ValueError('Selected backend identity is not loaded in the registered project')
                await native.observe_loaded(selected['id'], workspace)
                client = 'tgt02-' + uuid.uuid4().hex
                intent = {'label': label, 'thread_id': selected['id'], 'client_id': client, 'phase': 'submit_intent'}
                case['inputs'].append(intent)
                write_json(path, case, replace=True)
                await NativeQueue(native, selected['id'], workspace).add(
                    '只回复这段对话启动时的完整 WX-LAUNCH- 标记。不要调用工具，不读取或修改文件。', client)
                turn = await completed(native, selected['id'], client)
                if 'WX-LAUNCH-' + launch_id not in native_output(turn):
                    raise ValueError('Original native context was not retained')
                intent.update(phase='completed', turn_id=turn['id'], hidden_after=await hidden(session, selected))
                write_json(path, case, replace=True)
                print(json.dumps({'path': label, 'hidden_initial_binding_and_native_completion': True}), flush=True)
            if case['fixtures'][0]['thread_id'] == case['fixtures'][1]['thread_id']:
                raise ValueError('The two owned native dialogues were merged')
            if protected() != case['protected_hashes']:
                raise ValueError('Protected configuration changed')
            case['phase'] = 'probe_verified'
            write_json(path, case, replace=True)
            print(json.dumps({'phase': case['phase'], 'server_version': native.server_version,
                              'hidden_before_first_binding': True, 'wechat_sends': 0}), flush=True)
        else:
            case = read_json(path)
            app = await iterm2.async_get_app(host.connection)
            findings = []
            for fixture in case['fixtures']:
                session = app.get_session_by_id(fixture.get('terminal_id'))
                if session is None:
                    findings.append({'label': fixture['label'], 'present': False})
                    continue
                endpoint = await inspect_terminal(session)
                if endpoint.process is None or asdict(endpoint.process) != {**fixture['process'], 'started': tuple(fixture['process']['started'])}:
                    raise ValueError('Owned fixture process changed')
                thread = await native.inspect(fixture['thread_id'])
                findings.append({'label': fixture['label'], 'present': True, 'status': thread['status']['type'],
                                 'hidden': await hidden(session, thread)})
                if args.action == 'cleanup':
                    if thread['status']['type'] != 'idle' or await NativeQueue(native, thread['id'], workspace).list():
                        raise ValueError('Owned thread not idle with an empty queue')
                    if any(i['phase'] != 'completed' for i in case['inputs']):
                        raise ValueError('Uncertain owned input must be reconciled before cleanup')
                    await session.async_close(force=True)
            if args.action == 'cleanup':
                case['phase'] = 'cleaned'
                write_json(path, case, replace=True)
            print(json.dumps({'phase': case['phase'], 'findings': findings}), flush=True)
    finally:
        if native:
            await native.close()
        await host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('launch', 'probe', 'inspect', 'cleanup'))
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--launch-id')
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--confirm-dedicated', action='store_true')
    args = parser.parse_args()
    if args.action == 'launch':
        launch(args)
    else:
        asyncio.run(main(args))
