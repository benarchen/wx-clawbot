"""Explicit cold /cd on two owned projects; no WeChat or production ledger I/O."""

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import time

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, write_json
from wx_clawbot.channels.wechat import Credentials, FIXED_BASE
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter
from wx_clawbot.release import ENVIRONMENT_KEY, verify_active
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.runtime_state import RuntimeState


class CandidateRegistry(LaunchRegistry):
    def command(self, launch_id):
        # The GUI may have inherited another release's environment. Pin only
        # this owned test child to the same frozen candidate as its controller.
        manifest = os.environ[ENVIRONMENT_KEY]
        return shlex.join(['/usr/bin/env', ENVIRONMENT_KEY + '=' + manifest]) + ' ' + super().command(launch_id)


def protected():
    private = Path.home() / 'Library/Application Support/wx-clawbot'
    paths = [private / 'config.json', private / 'credentials.json',
             Path.home() / '.codex/config.toml',
             Path.home() / 'Library/LaunchAgents/local.wx-clawbot.plist']
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]


def startup_preferences():
    path = Path.home() / 'Library/Preferences/com.googlecode.iterm2.plist'
    saved = plistlib.loads(path.read_bytes()) if path.exists() else {}
    return {key: saved.get(key) for key in ('OpenNewWindowAtStartup', 'OpenUntitledFile',
                                          'OpenNoWindowsAtStartup', 'OpenArrangementAtStartup')}


async def main(args):
    import iterm2
    root = args.case_dir.absolute()
    workspace = Path(__file__).resolve().parents[2]
    if not args.confirm_dedicated or not root.resolve().is_relative_to((workspace / '.tmp').resolve()):
        raise ValueError('Dedicated cold-start case inside project .tmp required')
    if (root / 'case.json').exists():
        raise FileExistsError('An existing creation intent must be inspected, never replayed')
    manifest = verify_active(args.manifest)
    host, native, state, engine = HostLifecycle(), None, None, None
    if await host.backend.identity() is not None:
        raise ValueError('iTerm2 is running; preserve user windows and wait for a real cold start')
    before = protected()
    preferences = startup_preferences()
    private_directory(root)
    case = {'phase': 'intent', 'source_sha256': manifest['source_sha256'],
            'validator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'cold_start': True, 'commands': [], 'calls': {}, 'wechat_sends': 0,
            'production_ledger_direct_writes': 0}
    path = root / 'case.json'
    write_json(path, case)

    def save():
        write_json(path, case, replace=True)

    def count(name, original):
        async def call(*args, **kwargs):
            case['calls'][name] = case['calls'].get(name, 0) + 1
            save()
            return await original(*args, **kwargs)
        return call

    for name in ('launch', 'wait_ready', 'connect'):
        setattr(host.backend, name, count(name, getattr(host.backend, name)))
    sessions, projects = [], []
    started = time.monotonic()
    try:
        for alias in ('cold-owned-a', 'cold-owned-b'):
            cwd = root / alias
            cwd.mkdir(mode=0o700)
            (cwd / 'AGENTS.md').write_text(
                '# Dedicated startup verification\n\n'
                'Only read the applicable AGENTS.md and echo the requested WX-LAUNCH- marker. '
                'Do not modify files, run tests, or submit code.\n')
            projects.append(Project(alias, cwd))
        socket, executable = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        case['native_version'] = native.server_version
        state = await RuntimeState.open(root / 'runtime.sqlite3',
            Credentials('synthetic-cold', 'synthetic-owner', FIXED_BASE, 'synthetic-token'))
        directory = ItermDirectory(lifecycle=host)
        catalog = SessionCatalog(tuple(projects), directory, native)
        registry = CandidateRegistry(root / 'launches')
        creator = ItermWindowStarter(lifecycle=host)
        starter = VisibleStarter(registry, count('create_terminal', creator))
        controller = Controller(tuple(projects), catalog, state, starter, executable, Path.home() / '.codex', host=host)
        engine = Execution(controller)

        async def command(text):
            index = len(case['commands']) + 1
            case['commands'].append({'index': index, 'text': text, 'phase': 'intent'})
            save()
            raw = {'message_id': index, 'from_user_id': 'synthetic-owner', 'to_user_id': 'synthetic-cold',
                   'message_type': 1, 'message_state': 2, 'create_time_ms': index, 'seq': index,
                   'context_token': 'synthetic', 'item_list': [{'type': 1, 'text_item': {'text': text}}]}
            batch = await state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
            await asyncio.wait_for(controller.prepare(batch['accepted'][0]), 165)
            case['commands'][-1]['phase'] = 'returned'
            save()

        for index, project in enumerate(projects, 1):
            await command('/cd ' + project.alias)
            target = controller.routes.target
            if target is None or target.cwd != project.root:
                raise ValueError('The single cd did not select its accurate native target')
            session = await catalog.require(target)
            records = [registry.load(p.stem) for p in registry.root.glob('*.json') if not p.name.endswith('.boot.json')]
            matches = [r for r in records if r.get('thread_id') == session.binding.thread_id]
            if len(matches) != 1:
                raise ValueError('Owned launch receipt is not unique')
            record = matches[0]
            app = await iterm2.async_get_app(host.connection)
            terminal = app.get_session_by_id(record['terminal_id'])
            endpoint = await inspect_terminal(terminal) if terminal else None
            if endpoint is None or endpoint.process is None or asdict(endpoint.process) != {
                    **record['process'], 'started': tuple(record['process']['started'])}:
                raise ValueError('Owned process/TTY receipt changed')
            sessions.append((session, terminal, endpoint))
            windows = {w.window_id: [s.session_id for t in w.tabs for s in t.sessions] for w in app.windows}
            expected = [t.session_id for _, t, _ in sessions]
            if len(windows) != 1 or sorted(next(iter(windows.values()))) != sorted(expected):
                case.update(phase='unexpected_windows', windows=windows)
                save()
                raise ValueError('Extra/restored terminal present; never adopt or close an unowned shell')
            if case['calls'].get('launch') != 1 or case['calls'].get('create_terminal') != index:
                raise ValueError('Application or terminal creation was repeated')
            history = (await native.read_turns(session.binding.thread_id))['data']
            if len(history) != 1 or history[0]['status'] != 'completed':
                raise ValueError('The owned startup handshake was not uniquely completed')
            case['commands'][-1].update(phase='verified', binding=json.loads(json.dumps(asdict(session.binding), default=str)),
                                       terminal_id=terminal.session_id, process=asdict(endpoint.process))
            save()
            await command('/cd ' + project.alias)
            if controller.routes.target != target or case['calls'].get('create_terminal') != index:
                raise ValueError('Repeated cd did not reuse the exact managed object')
        if protected() != before:
            raise ValueError('Protected configuration changed')
        if startup_preferences() != preferences:
            raise ValueError('Persistent startup preferences changed')
        case.update(phase='verified', seconds=round(time.monotonic() - started, 3),
                    one_owned_window=True, owned_terminals=2, default_shells=0, configuration_preserved=True,
                    persistent_startup_preferences_preserved=True)
        save()
    except BaseException as error:
        case.update(error_type=type(error).__name__)
        save()
        raise
    finally:
        # Close only endpoints proven owned, idle and empty. Preserve uncertain
        # resources for inspection; never close an unexpected default window.
        cleanup = []
        for session, terminal, endpoint in sessions:
            try:
                thread = await native.inspect(session.binding.thread_id)
                if (thread['status']['type'] != 'idle'
                        or await NativeQueue(native, thread['id'], session.target.cwd).list()
                        or await inspect_terminal(terminal) != endpoint):
                    cleanup.append({'terminal_id': terminal.session_id, 'closed': False, 'reason': 'not_idle_empty_or_original'})
                    continue
                await terminal.async_close(force=True)
                cleanup.append({'terminal_id': terminal.session_id, 'closed': True})
            except Exception as error:
                cleanup.append({'terminal_id': terminal.session_id, 'closed': False, 'reason': type(error).__name__})
        case['cleanup'] = cleanup
        if cleanup:
            try:
                async with asyncio.timeout(2):
                    app = await iterm2.async_get_app(host.connection)
                    remaining = {s.session_id for w in app.windows for t in w.tabs for s in t.sessions}
                    case['owned_terminals_absent_after_cleanup'] = not remaining.intersection(
                        row['terminal_id'] for row in cleanup)
            except Exception:
                case['owned_terminals_absent_after_cleanup'] = await host.backend.identity() is None
        case['configuration_preserved_after_cleanup'] = protected() == before and startup_preferences() == preferences
        save()
        if engine:
            await engine.close()
        if native:
            await native.close()
        await host.close()
        if state:
            await state.close()
    print(json.dumps({key: value for key, value in case.items()
        if key not in {'commands', 'windows', 'cleanup'}}, ensure_ascii=False))
    if (not all(row['closed'] for row in case['cleanup'])
            or not case.get('owned_terminals_absent_after_cleanup')
            or not case['configuration_preserved_after_cleanup']):
        raise ValueError('Owned cleanup is incomplete; inspect the private case before continuing')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-dir', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--confirm-dedicated', action='store_true')
    asyncio.run(main(parser.parse_args()))
