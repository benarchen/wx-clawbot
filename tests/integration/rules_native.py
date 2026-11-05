"""Explicit AUD01 owned-session rule experiment; never connects to WeChat."""

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import time
import uuid

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.config import Project
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter, reconcile_launch, LaunchPending, LaunchError
from wx_clawbot.output import native_output
from wx_clawbot.runtime_discovery import discover_runtime
from wx_clawbot.sessions import verify_binding
from wx_clawbot.release import ENVIRONMENT_KEY, verify_active


class DiagnosticRegistry(LaunchRegistry):
    """Capture Python startup failures privately without redirecting the native TUI."""

    def command(self, launch_id):
        self.load(launch_id)  # Validate identity and the existing intent before building argv.
        script = ('import os,runpy,sys,traceback\n'
                  'diagnostic=sys.argv.pop(1)\n'
                  'try:\n'
                  ' runpy.run_module("wx_clawbot.launcher",run_name="__main__")\n'
                  'except BaseException:\n'
                  ' fd=os.open(diagnostic,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)\n'
                  ' with os.fdopen(fd,"w") as stream: stream.write(traceback.format_exc()[:16384])\n'
                  ' raise\n')
        manifest = os.environ.get(ENVIRONMENT_KEY)
        environment = [ENVIRONMENT_KEY + '=' + manifest] if manifest else ['-u', ENVIRONMENT_KEY]
        return shlex.join(['/usr/bin/env', *environment, str(Path(sys.executable).absolute()), '-I', '-c', script,
                           str(self.root / (launch_id + '.startup-error.txt')),
                           '--registry', str(self.root), '--launch-id', launch_id])


def rules(token):
    return ('# AUD01 temporary fixture\n\n'
            'Only perform the read-only AUD01 experiment. Never call tools or read files. '
            'For a prompt beginning WX-LAUNCH-, echo that complete marker. '
            'For all other prompts, reply with this exact project rule marker: ' + token + '\n')


def protect():
    root = Path.home() / 'Library/Application Support/wx-clawbot'
    paths = [root / 'config.json', root / 'credentials.json',
             Path.home() / '.codex/config.toml',
             Path.home() / 'Library/LaunchAgents/local.wx-clawbot.plist']
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]


async def record_result(native, thread_id, case, intent, path):
    async with asyncio.timeout(180):
        while True:
            page = await native.read_turns(thread_id, limit=20)
            if page.get('nextCursor'):
                raise ValueError('Owned history exceeds the experiment bound')
            matches = [t for t in page['data'] if any(i.get('type') == 'userMessage'
                and i.get('clientId') == intent['client'] for i in t.get('items', []))]
            if len(matches) > 1:
                raise ValueError('Duplicate native submission identity')
            if matches and matches[0]['status'] in {'completed','failed','interrupted'}:
                turn = matches[0]
                break
            await asyncio.sleep(.5)
    users = [i for i in turn.get('items',[]) if i.get('type') == 'userMessage']
    intent.update(state=turn['status'] if len(users)==1 else 'unknown',native_status=turn['status'],
        turn_id=turn['id'],output=native_output(turn),
        tool_items=sum(i.get('type') in {'commandExecution','mcpToolCall','dynamicToolCall'}
                       for i in turn.get('items',[])), business_users=len(users))
    write_json(path,case,replace=True)
    if turn['status'] != 'completed' or intent['tool_items'] or len(users) != 1:
        raise ValueError('Owned result is unfinished, uses tools, or merges business inputs')
    print(json.dumps({'case':intent['case'],'status':intent['state'],'output':intent['output']}),flush=True)


async def diagnose_connection(root):
    """Drop only our own client transport, with an empty independent ledger."""
    from wx_clawbot.channels.wechat import Credentials,FIXED_BASE
    from wx_clawbot.managed import EventStream,open_log
    from wx_clawbot.runtime_lifecycle import BridgeRuntime
    from wx_clawbot.runtime_state import RuntimeState
    if (root/'runtime.sqlite3').exists() or (root/'diagnostic-summary.json').exists():
        raise FileExistsError('A fresh diagnostic ledger and report are required')
    project=root/'project';project.mkdir(mode=0o700)
    (project/'AGENTS.md').write_text('# Private connection diagnostic\nNo Agent task may be submitted.\n')
    before=protect();host=HostLifecycle();state=None;job=None;handler=None
    try:
        socket,executable=await asyncio.to_thread(discover_runtime,Path.home()/'.codex')
        inode=(socket.stat().st_dev,socket.stat().st_ino)
        state=await RuntimeState.open(root/'runtime.sqlite3',
            Credentials('aud01-local-bot','aud01-local-owner',FIXED_BASE,'unused-local-token'))
        logger,handler=open_log(root);stream=EventStream(logger)
        def emit(report):
            stream.write(json.dumps(report)+'\n')
        starter=VisibleStarter(LaunchRegistry(root/'launches'),ItermWindowStarter(lifecycle=host))
        runtime=BridgeRuntime((Project('aud01-empty',project),),state,starter,host,socket,
                              executable,Path.home()/'.codex',emit=emit)
        await runtime.initialize();job=asyncio.create_task(runtime.run())
        dropped=False;first=None
        async with asyncio.timeout(30):
            while True:
                if job.done():job.result();raise RuntimeError('Diagnostic runtime ended unexpectedly')
                if runtime.native_state=='ready' and runtime.controller.native_ready:
                    stream.write(json.dumps({'status':'capabilities',**runtime.report()})+'\n')
                    if not dropped:
                        first=runtime.controller.catalog.agent
                        dropped=True
                        await first.rpc.transport.close()
                    elif runtime.native_generation>=2 and runtime.controller.catalog.agent is not first:
                        break
                await asyncio.sleep(.05)
        events=[json.loads(line) for line in (root/'logs/bridge.jsonl').read_text().splitlines()]
        failures=[e for e in events if e['event']=='native_unavailable']
        recovered=any(e['event']=='capabilities' and e.get('native',{}).get('state')=='ready'
                      for e in events[events.index(failures[0])+1:]) if failures else False
        summary={'status':'passed','native_failure_logged':bool(failures),'recovery_logged':recovered,
                 'failure_types':[e.get('error_types',[e['error_type']]) for e in failures],
                 'native_generations':runtime.native_generation,'empty_ledger':not await state.tasks(),
                 'daemon_socket_unchanged':inode==(socket.stat().st_dev,socket.stat().st_ino),
                 'configuration_preserved':before==protect(),'native_submissions':0,'wechat_sends':0,
                 'terminal_creations':len(list((root/'launches').glob('*.json')))}
        if not(failures and recovered and summary['empty_ledger'] and summary['daemon_socket_unchanged']
               and summary['configuration_preserved'] and summary['terminal_creations']==0):
            raise ValueError('Real connection diagnostic did not satisfy its invariants')
        write_json(root/'diagnostic-summary.json',summary);print(json.dumps(summary))
    finally:
        if job:
            job.cancel();await asyncio.gather(job,return_exceptions=True)
        if state:await state.close()
        await host.close()
        if handler:handler.close()


async def main(args):
    workspace = Path(__file__).resolve().parents[2]
    root = args.case_dir.absolute()
    if not root.resolve().is_relative_to((workspace / '.tmp').resolve()):
        raise ValueError('Owned evidence must stay in this candidate .tmp')
    if args.action == 'plan':
        print(json.dumps({'status': 'rules_native_plan', 'owned_terminals': 1,
                          'wechat_sends': 0, 'production_writes': 0}))
        return
    if not args.confirm_dedicated:
        raise ValueError('Explicit dedicated-fixture confirmation required')
    if args.action != 'report':
        verify_active()  # Reject a mismatched parent before any host request or state creation.
    private_directory(root)
    if args.action == 'diagnostics':
        await diagnose_connection(root)
        return
    path = root / 'case.json'
    if args.action == 'prepare' and path.exists():
        raise FileExistsError('An existing launch intent cannot be replayed')
    case = None if args.action == 'prepare' else read_json(path)
    if args.action == 'report':
        print(json.dumps({'phase': case['phase'], 'results': len(case['results']),
                          'configuration_preserved': case['protected'] == protect()}))
        return
    if case is not None:
        expected = 'ready' if args.action == 'run' else 'tested'
        if case['phase'] != expected:
            raise ValueError('Saved experiment phase forbids this action; inspect its existing intent')
        if args.action == 'boundaries' and case.get('boundaries_completed'):
            raise ValueError('Boundary experiment is not replayable')
    host, native = HostLifecycle(), None
    try:
        await host.ensure()
        host.verified(host.generation)
        socket, executable = await asyncio.to_thread(discover_runtime, Path.home() / '.codex')
        native = await CodexConnection.connect(socket)
        if native.server_version != '0.166.0':
            raise ValueError('This rule experiment requires the reviewed 0.166.0 runtime')
        directory = ItermDirectory(lifecycle=host)
        registry = DiagnosticRegistry(root / 'launches')
        if args.action == 'prepare':
            fixture = root / 'project'
            fixture.mkdir(mode=0o700)
            (fixture / 'AGENTS.md').write_text(rules('AUD01_RULE_A'))
            project = Project('aud01-fixture', fixture)
            launch_id = uuid.uuid4().hex
            case = {'phase': 'launch_intent', 'launch_id': launch_id, 'cwd': str(fixture),
                    'protected': protect(), 'runtime_identity': list(native.runtime_identity),
                    'version': native.server_version, 'results': []}
            write_json(path, case)
            starter = VisibleStarter(registry, ItermWindowStarter(lifecycle=host))
            await starter.start(launch_id, project, fixture, executable, Path.home() / '.codex', 'AUD01-rules-owned')
            record = registry.load(launch_id)
            case.update({k: record[k] for k in ('window_id', 'tab_id', 'terminal_id')})
            write_json(path, case, replace=True)
            async with asyncio.timeout(180):
                while True:
                    try:
                        binding = await reconcile_launch(registry, launch_id, directory, native)
                        break
                    except LaunchPending:
                        if (registry.root / (launch_id + '.startup-error.txt')).exists():
                            raise LaunchError('Owned launcher failed; inspect its private startup error before retry')
                        await asyncio.sleep(.5)
            case.update(phase='ready', binding=json.loads(json.dumps(asdict(binding), default=str)))
            write_json(path, case, replace=True)
            if case['protected'] != protect():
                raise ValueError('Protected configuration changed during preparation')
            print(json.dumps({'status': 'owned_fixture_ready', 'version': native.server_version}))
            return
        if case['protected'] != protect() or case['runtime_identity'] != list(native.runtime_identity):
            raise ValueError('Protected configuration or native generation changed')
        if case['phase'] not in {'ready', 'running', 'tested'}:
            raise ValueError('Owned case is not ready for inspection')
        binding = await reconcile_launch(registry, case['launch_id'], directory, native)
        saved = case['binding']
        if (binding.thread_id != saved['thread_id'] or binding.native_session_id != saved['native_session_id']
                or list(binding.endpoint.process.started) != saved['endpoint']['process']['started']
                or binding.endpoint.process.pid != saved['endpoint']['process']['pid']):
            raise ValueError('Owned process or exact native identity changed')
        queue = NativeQueue(native, binding.thread_id, binding.project)
        if args.action == 'run':
            if case['phase'] != 'ready':
                raise ValueError('Experiment intent is not replayable; inspect its saved results')
            case['phase'] = 'running'
            write_json(path, case, replace=True)
            await native.observe_loaded(binding.thread_id, binding.project)
            for label, filename, token in [('baseline', 'AGENTS.md', 'AUD01_RULE_A'),
                                           ('changed', 'AGENTS.md', 'AUD01_RULE_B'),
                                           ('override_added', 'AGENTS.override.md', 'AUD01_RULE_C')]:
                await verify_binding(binding, directory, native)
                if await queue.list():
                    raise ValueError('Owned queue is not empty')
                (binding.project / filename).write_text(rules(token))
                client = 'aud01-' + uuid.uuid4().hex
                intent = {'case': label, 'client': client, 'file_sha256':
                          hashlib.sha256((binding.project / filename).read_bytes()).hexdigest(), 'state': 'intent'}
                case['results'].append(intent)
                write_json(path, case, replace=True)
                receipt = await queue.add('Reply only with the current AUD01 project rule marker. Do not use tools.', client)
                intent.update(state='queued', queue_id=receipt['id'])
                write_json(path, case, replace=True)
                await record_result(native,binding.thread_id,case,intent,path)
            case['phase'] = 'tested'
            write_json(path, case, replace=True)
        elif args.action == 'boundaries':
            # This invocation is a fresh bridge connection to the same verified TUI.
            case.update(phase='boundaries_running',reconnected_same_binding=True)
            write_json(path,case,replace=True)
            await native.observe_loaded(binding.thread_id,binding.project)
            agents,override = binding.project/'AGENTS.md',binding.project/'AGENTS.override.md'
            if agents.read_text()!=rules('AUD01_RULE_B') or override.read_text()!=rules('AUD01_RULE_C'):
                raise ValueError('Owned rule files changed outside the registered experiment')
            for label in ('same_mtime','override_removed','project_rule_removed','unreadable_rule'):
                await verify_binding(binding,directory,native)
                if await queue.list():raise ValueError('Owned queue is not empty')
                evidence={}
                if label=='same_mtime':
                    before=agents.stat();agents.write_text(rules('AUD01_RULE_D'))
                    os.utime(agents,ns=(before.st_atime_ns,before.st_mtime_ns))
                    evidence={'same_size':agents.stat().st_size==before.st_size,
                              'same_mtime_ns':agents.stat().st_mtime_ns==before.st_mtime_ns}
                elif label=='override_removed':override.unlink()
                elif label=='project_rule_removed':agents.unlink()
                else:agents.write_text(rules('AUD01_RULE_E'));agents.chmod(0)
                intent={'case':label,'client':'aud01-'+uuid.uuid4().hex,'state':'intent','evidence':evidence}
                case['results'].append(intent);write_json(path,case,replace=True)
                try:
                    receipt=await queue.add('Reply only with the current AUD01 project rule marker. Do not use tools.',intent['client'])
                    intent.update(state='queued',queue_id=receipt['id']);write_json(path,case,replace=True)
                    await record_result(native,binding.thread_id,case,intent,path)
                finally:
                    if label=='unreadable_rule':agents.chmod(0o600)
            # Observe a real second input waiting behind an active original turn.
            await verify_binding(binding,directory,native)
            first={'case':'queue_blocker','client':'aud01-'+uuid.uuid4().hex,'state':'intent'}
            case['results'].append(first);write_json(path,case,replace=True)
            receipt=await queue.add('Reply only with the current AUD01 project rule marker. Do not use tools.',first['client'])
            first.update(state='queued',queue_id=receipt['id']);write_json(path,case,replace=True)
            async with asyncio.timeout(10):
                while True:
                    page=await native.read_turns(binding.thread_id,limit=20)
                    if page.get('nextCursor'):raise ValueError('Owned history exceeds the experiment bound')
                    if any(t['status']=='inProgress' and any(i.get('type')=='userMessage' and
                        i.get('clientId')==first['client'] for i in t.get('items',[])) for t in page['data']):break
                    await asyncio.sleep(.02)
            second={'case':'queued_file_change','client':'aud01-'+uuid.uuid4().hex,'state':'intent'}
            case['results'].append(second);write_json(path,case,replace=True)
            receipt=await queue.add('Reply only with the current AUD01 project rule marker. Do not use tools.',second['client'])
            second.update(state='queued',queue_id=receipt['id']);write_json(path,case,replace=True)
            before=any(i['id']==receipt['id'] for i in await queue.list())
            agents.write_text(rules('AUD01_RULE_F'))
            changed_at=time.time()
            after=any(i['id']==receipt['id'] for i in await queue.list())
            second['evidence']={'queued_before_change':before,'queued_after_change':after,
                                'changed_at':changed_at}
            write_json(path,case,replace=True)
            await record_result(native,binding.thread_id,case,first,path)
            await record_result(native,binding.thread_id,case,second,path)
            case.update(phase='tested',boundaries_completed=True)
            write_json(path,case,replace=True)
        elif args.action == 'cleanup':
            if case['phase'] != 'tested':
                raise ValueError('Only a tested owned case can be closed automatically')
            await verify_binding(binding, directory, native)
            if (await native.inspect(binding.thread_id))['status']['type'] != 'idle' or await queue.list():
                raise ValueError('Owned task or queue has not ended')
            import iterm2
            app = await iterm2.async_get_app(host.connection)
            terminal = app.get_session_by_id(binding.endpoint.terminal_id)
            if terminal is None or await inspect_terminal(terminal) != binding.endpoint:
                raise ValueError('Owned terminal identity changed before cleanup')
            case['phase'] = 'close_intent'
            write_json(path, case, replace=True)
            await terminal.async_close(force=True)
            case['phase'] = 'cleaned'
            write_json(path, case, replace=True)
            print(json.dumps({'status': 'owned_fixture_cleaned', 'owned_terminals_closed': 1}))
        if case['protected'] != protect():
            raise ValueError('Protected configuration changed during experiment')
    finally:
        if native:
            await native.close()
        await host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'prepare', 'run', 'boundaries', 'diagnostics', 'report', 'cleanup'))
    parser.add_argument('--case-dir', required=True, type=Path)
    parser.add_argument('--confirm-dedicated', action='store_true')
    asyncio.run(main(parser.parse_args()))
