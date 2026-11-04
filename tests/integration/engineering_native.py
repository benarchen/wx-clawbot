"""Explicit ENG01 owned-native workflow. All delivery is fake; no WeChat I/O."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.managed import source_digest


async def performance_case(owned, output):
    from wx_clawbot.agents.codex import CodexConnection
    from wx_clawbot.agents.queue import NativeQueue
    from wx_clawbot.catalog import SessionCatalog
    from wx_clawbot.config import load_projects
    from wx_clawbot.hosts.discovery import ItermDirectory
    from wx_clawbot.hosts.lifecycle import HostLifecycle
    from wx_clawbot.runtime_discovery import discover_runtime
    original = read_json(owned / 'case.json')
    host, native = HostLifecycle(), None
    try:
        await host.ensure()
        home = Path.home() / '.codex'
        socket, _ = await asyncio.to_thread(discover_runtime, home)
        native = await CodexConnection.connect(socket)
        catalog = SessionCatalog(load_projects(Path.home() / 'Library/Application Support/wx-clawbot/config.json'),
                                 ItermDirectory(lifecycle=host), native)
        sessions = await catalog.discover()
        fixtures = []
        for fixture in original['fixtures']:
            matches = [s for s in sessions if s.binding.thread_id == fixture['thread_id']
                       and s.binding.endpoint.terminal_id == fixture['terminal_id']]
            if len(matches) != 1:
                raise ValueError('Owned fixture identity cannot be verified')
            session = await catalog.require(matches[0].target)
            boot = read_json(owned / 'launches' / (fixture['launch_id'] + '.boot.json'))
            process = session.binding.endpoint.process
            if process.pid != boot['pid'] or list(process.started) != boot['started']:
                raise ValueError('Owned process differs from its frozen launch receipt')
            if (await native.inspect(fixture['thread_id']))['status']['type'] != 'idle':
                raise ValueError('Owned fixture is not idle')
            if await NativeQueue(native, fixture['thread_id'], session.target.cwd).list():
                raise ValueError('Owned fixture queue is not empty')
            fixtures.append({**fixture, 'session_id': session.target.session_id})
        if source_digest() != original['source_sha256'] or list(native.runtime_identity) != original['runtime_identity']:
            raise ValueError('Candidate or native runtime changed after preparation')
        production = Path.home() / 'Library/Application Support/wx-clawbot'
        files = [home / 'config.toml', production / 'config.json', production / 'credentials.json',
                 Path.home() / 'Library/LaunchAgents/local.wx-clawbot.plist']
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
        if hashes != original['protected_hashes']:
            raise ValueError('Protected configuration changed after owned preparation')
        write_json(output / 'native-case.json', {**original, 'fixtures': fixtures, 'phase': 'ready',
            'protected_hashes': [hashes[1], hashes[2], hashes[0], hashes[3]]})
    finally:
        if native:
            await native.close()
        await host.close()


def main(args):
    if args.release_manifest is not None:
        from wx_clawbot.release import verify_active
        verify_active(args.release_manifest)
    project = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not root.resolve().is_relative_to((project / '.tmp').resolve()):
        raise ValueError('Owned resources and evidence must stay in this candidate .tmp')
    record = root / 'workflow.json'
    helpers = {name: hashlib.sha256((project / 'tests/integration' / name).read_bytes()).hexdigest()
               for name in ('engineering_native.py', 'admission_native.py', 'performance_native.py',
                            'async_questions_native.py', 'engineering_async_model.py')}
    if args.action == 'report':
        value = read_json(record)
        print(json.dumps({k: value[k] for k in ('phase', 'source_sha256', 'completed_steps')}))
        return
    if not args.confirm_dedicated:
        raise ValueError('Explicit owned-resource confirmation required')
    if args.async_test_model and not args.confirm_temporary_model:
        raise ValueError('A specific temporary test-model authorization is required')
    if args.action == 'prepare':
        if root.exists():
            raise FileExistsError('Existing preparation intents cannot be repeated')
        private_directory(root)
        value = {'phase': 'prepare_intent', 'source_sha256': source_digest(),
                 'helper_sha256': helpers, 'completed_steps': [],
                 'async_test_model': args.async_test_model}
        write_json(record, value)
    else:
        value = read_json(record)
    if value['source_sha256'] != source_digest():
        raise ValueError('Candidate source changed; old intents cannot be replayed')
    if value.get('helper_sha256') != helpers:
        raise ValueError('Native verification helpers changed after the frozen preparation')
    if args.action == 'run' and value.get('async_test_model') != args.async_test_model:
        raise ValueError('The temporary model exception differs from the frozen preparation')
    owned = root / 'owned'
    def persist(phase):
        value['phase'] = phase
        write_json(record, value, replace=True)
    def invoke(script, action, *arguments):
        with (root / (script.removesuffix('.py') + '-' + action + '.log')).open('w') as stream:
            subprocess.run([sys.executable, '-I', str(project / 'tests/integration' / script), action,
                            *arguments], cwd=project, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=900)
    if args.action == 'prepare':
        async def host_ready():
            from wx_clawbot.hosts.lifecycle import HostLifecycle
            host = HostLifecycle()
            try:
                await host.ensure(launch=True, explicit=True)
            finally:
                await host.close()
        asyncio.run(host_ready())
        invoke('admission_native.py', 'prepare', '--report-dir', str(owned), '--confirm-dedicated', '--title-prefix', 'ENG01')
        value['completed_steps'].append('prepare')
        persist('ready')
    elif args.action == 'run':
        if value['phase'] != 'ready':
            raise ValueError('Only a fresh ready workflow may run; uncertain intent is never retried')
        persist('sync_intent')
        synchronous = private_directory(root / 'sync')
        asyncio.run(performance_case(owned, synchronous))
        invoke('performance_native.py', 'run', '--report-dir', str(synchronous), '--confirm-dedicated')
        value['completed_steps'].append('sync')
        persist('async_intent')
        if args.async_test_model:
            invoke('engineering_async_model.py', 'run', '--case-dir', str(owned),
                   '--report-dir', str(root / 'async-model'), '--model', args.async_test_model,
                   '--confirm-dedicated', '--confirm-temporary-model')
        else:
            invoke('async_questions_native.py', 'run', '--case-dir', str(owned),
                   '--report-dir', str(root / 'async'), '--confirm-dedicated')
        value['completed_steps'].append('async')
        persist('admission_intent')
        invoke('admission_native.py', 'run', '--report-dir', str(owned), '--confirm-dedicated')
        value['completed_steps'].append('admission')
        # Native clients may pause automatic queue consumption after interruption.
        # Exercise destructive controls last; never force-start a paused user queue.
        persist('controls_intent')
        controls = private_directory(root / 'controls')
        asyncio.run(performance_case(owned, controls))
        invoke('performance_native.py', 'run', '--report-dir', str(controls), '--confirm-dedicated', '--verify-controls')
        value['completed_steps'].append('controls')
        persist('verified')
    elif args.action == 'cleanup':
        if value['phase'] != 'verified':
            raise ValueError('Uncertain workflow requires read-only inspection, not automatic cleanup')
        persist('cleanup_intent')
        invoke('admission_native.py', 'cleanup', '--report-dir', str(owned), '--confirm-dedicated')
        value['completed_steps'].append('cleanup')
        persist('cleaned')
    print(json.dumps({'phase': value['phase'], 'completed_steps': value['completed_steps'],
                      'wechat_sends': 0, 'production_ledger_writes': 0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run', 'report', 'cleanup'))
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--confirm-dedicated', action='store_true')
    parser.add_argument('--release-manifest', type=Path)
    parser.add_argument('--async-test-model')
    parser.add_argument('--confirm-temporary-model', action='store_true')
    main(parser.parse_args())
