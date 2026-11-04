"""Explicit, authorized model exception for one owned async test; never global."""

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.config import load_projects
from wx_clawbot.hosts.discovery import ItermDirectory
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.managed import source_digest
from wx_clawbot.runtime_discovery import discover_runtime


SETTINGS = ('model', 'modelProvider', 'collaborationMode', 'reasoningEffort', 'approvalPolicy',
            'approvalsReviewer', 'sandbox', 'activePermissionProfile', 'cwd', 'disabledPluginIds',
            'multiAgentMode', 'serviceTier', 'runtimeWorkspaceRoots')


def view(reply):
    required = {'model', 'modelProvider', 'collaborationMode', 'reasoningEffort', 'approvalPolicy',
                'approvalsReviewer', 'sandbox', 'cwd'}
    if (not required <= reply.keys() or not isinstance(reply.get('model'), str)
            or not isinstance(reply.get('modelProvider'), str) or not isinstance(reply.get('sandbox'), dict)
            or not isinstance(reply.get('collaborationMode'), dict)
            or not isinstance(reply['collaborationMode'].get('settings'), dict)):
        raise ValueError('Complete owned thread settings required')
    return {name: copy.deepcopy(reply.get(name)) for name in SETTINGS}


async def main(args):
    from wx_clawbot.release import verify_active
    verify_active(args.release_manifest)
    project = Path(__file__).resolve().parents[2]
    owned, output = args.case_dir.absolute(), args.report_dir.absolute()
    if any(not p.resolve().is_relative_to((project / '.tmp').resolve()) for p in (owned, output)):
        raise ValueError('Owned resources and evidence must stay in the project .tmp')
    path = output / 'model-exception.json'
    if args.action == 'report':
        record = read_json(path)
        print(json.dumps({k:record.get(k) for k in ('phase', 'source_sha256', 'settings_restored')}))
        return
    if not args.confirm_dedicated or (args.action == 'run' and (not args.confirm_temporary_model or not args.model)):
        raise ValueError('Specific owned-resource and temporary-model authorization required')
    if args.action == 'cleanup':
        record = read_json(path)
        original_case = read_json(owned / 'case.json')
        if record['phase'] != 'verified' or not record['settings_restored']:
            raise ValueError('Only verified and restored model tests may close')
        await cleanup(owned, original_case, output, record, path)
        return
    if output.exists():
        raise FileExistsError('Old model or task intents must not be repeated')
    private_directory(output)
    original_case = read_json(owned / 'case.json')
    if original_case['phase'] != 'ready' or original_case['source_sha256'] != source_digest():
        raise ValueError('Fresh ready owned fixtures and exact candidate required')
    fixture = original_case['fixtures'][1]
    files = [Path.home() / '.codex/config.toml',
             Path.home() / 'Library/Application Support/wx-clawbot/config.json',
             Path.home() / 'Library/Application Support/wx-clawbot/credentials.json',
             Path.home() / 'Library/LaunchAgents/local.wx-clawbot.plist']
    hashes = lambda: [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    if hashes() != original_case['protected_hashes']:
        raise ValueError('Protected configuration changed')
    record = {'phase':'verification_intent', 'source_sha256':source_digest(),
              'requested_model':args.model, 'settings_restored':False,
              'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'async_helper_sha256':hashlib.sha256((project / 'tests/integration/async_questions_native.py').read_bytes()).hexdigest()}
    write_json(path, record)
    host, native = HostLifecycle(), None
    try:
        await host.ensure()
        socket, _ = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        if list(native.runtime_identity) != original_case['runtime_identity']:
            raise ValueError('Owned native runtime changed')
        catalog = SessionCatalog(load_projects(files[1]), ItermDirectory(lifecycle=host), native)
        found = await catalog.discover()
        matches = [s for s in found if s.binding.thread_id == fixture['thread_id']
                   and s.binding.endpoint.terminal_id == fixture['terminal_id']]
        if len(matches) != 1:
            raise ValueError('Owned test endpoint not uniquely verified')
        session = await catalog.require(matches[0].target)
        boot = read_json(owned / 'launches' / (fixture['launch_id'] + '.boot.json'))
        process = session.binding.endpoint.process
        if process.pid != boot['pid'] or list(process.started) != boot['started']:
            raise ValueError('Owned test process changed')
        queue = NativeQueue(native, fixture['thread_id'], session.target.cwd)
        async def idle():
            if (await native.inspect(fixture['thread_id']))['status']['type'] != 'idle' or await queue.list():
                raise ValueError('Owned native thread is not idle with an empty queue')
        await idle()
        models = await native.rpc.request('model/list', {'limit':100})
        if models.get('nextCursor') is not None or args.model not in {m.get('model') for m in models['data']}:
            raise ValueError('Requested test model is not in the complete native catalog')
        async def current():
            return view(await native.rpc.request('thread/resume',
                {'threadId':fixture['thread_id'], 'excludeTurns':True}))
        original = await current()
        desired = copy.deepcopy(original)
        desired['model'] = args.model
        desired['collaborationMode']['settings']['model'] = args.model
        record.update(phase='model_change_intent', original_settings=original, desired_settings=desired)
        write_json(path, record, replace=True)
        try:
            await native.rpc.request('thread/settings/update', {'threadId':fixture['thread_id'],
                'model':args.model, 'effort':original['reasoningEffort'],
                'collaborationMode':desired['collaborationMode']})
            async with asyncio.timeout(5):
                while await current() != desired:
                    await asyncio.sleep(.1)
            record['phase'] = 'async_test_intent'
            write_json(path, record, replace=True)
            with (output / 'async.log').open('w') as stream:
                completed = await asyncio.to_thread(subprocess.run,
                    [sys.executable, '-I', str(project / 'tests/integration/async_questions_native.py'),
                     'run', '--case-dir',str(owned), '--report-dir',str(output / 'async'),
                     '--confirm-dedicated'], cwd=project, stdout=stream, stderr=subprocess.STDOUT,
                     timeout=300)
            record['test_exit_code'] = completed.returncode
            if completed.returncode:
                raise ValueError('Owned async test failed; its input and answer must not be retried')
        finally:
            # Never modify a running/unknown thread to manufacture a clean result.
            await catalog.require(session.target)
            await idle()
            present = await current()
            if present not in (original, desired):
                raise ValueError('Owned settings changed outside the frozen model exception')
            record['phase'] = 'model_restore_intent'
            write_json(path, record, replace=True)
            if present != original:
                await native.rpc.request('thread/settings/update', {'threadId':fixture['thread_id'],
                    'model':original['model'], 'effort':original['reasoningEffort'],
                    'collaborationMode':original['collaborationMode']})
            async with asyncio.timeout(5):
                while await current() != original:
                    await asyncio.sleep(.1)
            record['settings_restored'] = True
            write_json(path, record, replace=True)
        if hashes() != original_case['protected_hashes']:
            raise ValueError('Protected configuration changed')
        proof = read_json(output / 'async/proof.json')
        if proof.get('passed') is not True or proof.get('source_sha256') != source_digest():
            raise ValueError('Exact async evidence missing')
        record['phase'] = 'verified'
        write_json(path, record, replace=True)
        public = {'passed':True, 'source_sha256':source_digest(), 'temporary_model':args.model,
                  'settings_restored':True, 'global_configuration_unchanged':True,
                  'original_task_submissions':1, 'answer_submissions':1, 'wechat_sends':0,
                  'production_ledger_writes':0}
        write_json(output / 'proof.json', public)
        print(json.dumps(public))
    finally:
        if native:
            await native.close()
        await host.close()


async def cleanup(owned, original_case, output, record, path):
    import iterm2
    if source_digest() != record['source_sha256'] or original_case['source_sha256'] != source_digest():
        raise ValueError('Owned source identity changed')
    proof = read_json(output / 'async/proof.json')
    case = read_json(output / 'async/case.json')
    if proof.get('passed') is not True or case['phase'] != 'verified':
        raise ValueError('Actual async terminal proof required')
    files = [Path.home() / '.codex/config.toml',
             Path.home() / 'Library/Application Support/wx-clawbot/config.json',
             Path.home() / 'Library/Application Support/wx-clawbot/credentials.json',
             Path.home() / 'Library/LaunchAgents/local.wx-clawbot.plist']
    hashes = lambda: [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    if hashes() != original_case['protected_hashes']:
        raise ValueError('Protected configuration changed')
    host, native = HostLifecycle(), None
    try:
        await host.ensure()
        socket, _ = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        if list(native.runtime_identity) != original_case['runtime_identity']:
            raise ValueError('Owned native runtime changed')
        catalog = SessionCatalog(load_projects(files[1]), ItermDirectory(lifecycle=host), native)
        found = await catalog.discover()
        sessions = []
        for fixture in original_case['fixtures']:
            matches = [s for s in found if s.binding.thread_id == fixture['thread_id']
                       and s.binding.endpoint.terminal_id == fixture['terminal_id']]
            if len(matches) != 1:
                raise ValueError('Owned cleanup endpoint not uniquely verified')
            session = await catalog.require(matches[0].target)
            boot = read_json(owned / 'launches' / (fixture['launch_id'] + '.boot.json'))
            process = session.binding.endpoint.process
            if process.pid != boot['pid'] or list(process.started) != boot['started']:
                raise ValueError('Owned cleanup process changed')
            if (await native.inspect(fixture['thread_id']))['status']['type'] != 'idle':
                raise ValueError('Owned cleanup thread not idle')
            if await NativeQueue(native, fixture['thread_id'], session.target.cwd).list():
                raise ValueError('Owned cleanup queue not empty')
            sessions.append(session)
        restored = view(await native.rpc.request('thread/resume',
            {'threadId':original_case['fixtures'][1]['thread_id'], 'excludeTurns':True}))
        if restored != record['original_settings']:
            raise ValueError('Owned original model and settings are no longer restored')
        turns = await native.rpc.request('thread/turns/list',
            {'threadId':case['thread_id'], 'limit':20, 'itemsView':'full', 'sortDirection':'desc'})
        completed = [t for t in turns['data'] if t['id'] == case['turn_id']]
        if len(completed) != 1 or completed[0]['status'] != 'completed':
            raise ValueError('Exact owned async turn is not completed')
        record['phase'] = 'cleanup_intent'
        write_json(path, record, replace=True)
        app = await iterm2.async_get_app(host.connection)
        for fixture, session in zip(original_case['fixtures'], sessions):
            await catalog.require(session.target)
            endpoint = app.get_session_by_id(fixture['terminal_id'])
            if endpoint is None:
                raise ValueError('Owned cleanup endpoint disappeared')
            fixture['phase'] = 'close_intent'
            write_json(owned / 'case.json', original_case, replace=True)
            await endpoint.async_close(force=True)
            fixture['phase'] = 'closed'
            write_json(owned / 'case.json', original_case, replace=True)
        app = await iterm2.async_get_app(host.connection)
        present = {s.session_id for w in app.windows for t in w.tabs for s in t.sessions}
        if not set(original_case['before_terminal_ids']) <= present or any(
                f['terminal_id'] in present for f in original_case['fixtures']):
            raise ValueError('Owned cleanup or original user endpoint preservation not confirmed')
        if hashes() != original_case['protected_hashes']:
            raise ValueError('Protected configuration changed during cleanup')
        original_case['phase'] = 'cleaned'
        write_json(owned / 'case.json', original_case, replace=True)
        record.update(phase='cleaned', own_terminals_closed=2, user_terminals_preserved=True)
        write_json(path, record, replace=True)
        print(json.dumps({'phase':'cleaned', 'settings_restored':True,
                          'own_terminals_closed':2, 'user_terminals_preserved':True}))
    finally:
        if native:
            await native.close()
        await host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('run','report','cleanup'))
    parser.add_argument('--case-dir',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--release-manifest',type=Path)
    parser.add_argument('--model')
    parser.add_argument('--confirm-dedicated',action='store_true')
    parser.add_argument('--confirm-temporary-model',action='store_true')
    asyncio.run(main(parser.parse_args()))
