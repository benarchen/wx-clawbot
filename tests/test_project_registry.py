"""Project registration boundaries with real directories, files and faults."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from wx_clawbot.commands import CommandError, parse_command, parse_project
from wx_clawbot.config import ConfigError, Project, load_config, load_projects
from wx_clawbot.project_registry import ProjectError, ProjectStore, describe
from wx_clawbot.project_control import project_operation


class RegistryFixture:
    def setup_registry(self):
        parent = Path(__file__).resolve().parents[1] / '.tmp/prj01-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.workspace = self.base / 'workspace'; self.workspace.mkdir()
        self.private = self.base / 'private'; self.private.mkdir(mode=0o700)
        self.config = self.private / 'config.json'
        self.a = self.workspace / 'one'; self.a.mkdir()
        self.b = self.workspace / 'two'; self.b.mkdir()
        self.store = ProjectStore(self.config, self.private)
        self.seq = 0

    def change(self, action, **kwargs):
        self.seq += 1
        result, payload = self.store.plan(action, request='fixture-' + str(self.seq), **kwargs)
        if payload is not None:
            self.store.commit(payload)
        return result

    def initialize(self):
        preview = self.store.preview(str(self.workspace))
        return self.change('init', root=str(self.workspace), apply=True, confirm=preview['confirm'])


class RegistryTests(RegistryFixture, unittest.TestCase):
    def setUp(self):
        self.setup_registry()

    def test_preview_is_one_level_includes_non_git_and_does_not_read_contents(self):
        nested = self.a / 'nested'; nested.mkdir(); (nested / 'private.txt').write_text('PRIVATE')
        (self.workspace / '.hidden').mkdir()
        with patch.object(Path, 'read_text', side_effect=AssertionError('No project content reads')):
            result = self.store.preview(str(self.workspace))
        self.assertEqual({v['alias'] for v in result['added']}, {'one', 'two'})
        self.assertIn('.hidden', {v['name'] for v in result['skipped']})
        self.assertNotIn('nested', str(result))
        self.assertFalse(self.config.exists())

    def test_init_confirmation_creates_registry_and_exact_recent_receipt(self):
        result = self.initialize()
        current = load_config(self.config)
        self.assertEqual(current.workspace_root, self.workspace)
        self.assertEqual(current.revision, 1)
        self.assertEqual(current.operations[0]['id'], result['request_id'])
        self.assertEqual(os.stat(self.config).st_mode & 0o777, 0o600)

    def test_init_confirmation_is_invalid_after_directory_add(self):
        preview = self.store.preview(str(self.workspace)); (self.workspace / 'new').mkdir()
        with self.assertRaisesRegex(ProjectError, '变化'):
            self.change('init', root=str(self.workspace), apply=True, confirm=preview['confirm'])
        self.assertFalse(self.config.exists())

    def test_init_confirmation_is_invalid_after_inode_replacement(self):
        preview = self.store.preview(str(self.workspace))
        self.a.rename(self.workspace / 'moved'); self.a.mkdir()
        with self.assertRaises(ProjectError):
            self.change('init', root=str(self.workspace), apply=True, confirm=preview['confirm'])

    def test_expired_or_invalid_confirmation_and_root_change_rejected(self):
        for token in ('', 'bad', '0-deadbeef', str(int(time.time()) + 1000) + '-abc'):
            with self.subTest(token=token), self.assertRaises(ProjectError):
                self.change('init', root=str(self.workspace), apply=True, confirm=token)
        self.initialize()
        with self.assertRaises(ProjectError):
            self.store.preview(str(self.base))

    def test_duplicate_same_registration_is_noop_and_conflicts_do_not_replace(self):
        self.initialize(); raw = self.config.read_bytes()
        self.assertEqual(self.change('add', name='one')['status'], 'already_registered')
        self.assertEqual(self.config.read_bytes(), raw)
        for name, alias in [('one', 'another'), ('two', 'one')]:
            with self.subTest(name=name), self.assertRaises(ProjectError):
                self.change('add', name=name, alias=alias)
        self.assertEqual(self.config.read_bytes(), raw)

    def test_remove_is_association_only_and_restart_does_not_rescan(self):
        self.initialize(); self.change('remove', name='one')
        self.assertTrue(self.a.is_dir())
        reloaded = ProjectStore(self.config, self.private)
        self.assertEqual([p.alias for p in reloaded.config.projects], ['two'])
        self.assertEqual([p['alias'] for p in reloaded.plan('list')[0]['projects']], ['two'])
        self.assertEqual(self.change('remove', name='one')['status'], 'not_registered')
        self.change('add', name='one')
        self.assertEqual({p.alias for p in self.store.config.projects}, {'one', 'two'})

    def test_zero_projects_roundtrip_then_add(self):
        self.initialize(); self.change('remove', name='one'); self.change('remove', name='two')
        self.assertEqual(load_projects(self.config), ())
        self.assertIn('暂无', describe(self.store.plan('list')[0]))
        self.change('add', name='two')
        self.assertEqual(load_projects(self.config), (Project('two', self.b),))

    def test_alias_override_for_unicode_spaces_and_shell_like_directory_names(self):
        self.initialize()
        for i, name in enumerate(('中文', 'sample app', '$(touch NEVER)', 'semi;colon')):
            (self.workspace / name).mkdir()
            with self.assertRaises(ProjectError):
                self.change('add', name=name)
            self.change('add', name=name, alias='safe-' + str(i))
        self.assertFalse((self.workspace / 'NEVER').exists())

    def test_forbidden_directory_excluded_before_stat_and_no_alias_link_bypass(self):
        hidden = self.workspace / 'openclaw-local'; hidden.mkdir(); (hidden / 'private').write_text('DO_NOT_READ')
        (self.workspace / 'alias-link').symlink_to(hidden, target_is_directory=True)
        original = os.stat
        def guarded(path, *args, **kwargs):
            if 'openclaw-local' in Path(path).parts:
                raise AssertionError('Forbidden metadata traversal')
            return original(path, *args, **kwargs)
        with patch('os.stat', side_effect=guarded):
            preview = self.store.preview(str(self.workspace))
        self.assertNotIn('openclaw-local', [v['alias'] for v in preview['added']])
        self.initialize()
        for name in ('openclaw-local', 'alias-link'):
            with self.assertRaises(ProjectError):
                self.change('add', name=name)

    def test_forbidden_case_variant_is_excluded_before_directory_metadata(self):
        from contextlib import contextmanager
        name='OPENCLAW-LOCAL'
        (self.workspace/name).mkdir()
        original_scan=os.scandir
        class Entry:
            def __init__(self,entry):
                self.entry=entry;self.name=entry.name
            def stat(self,**kwargs):
                if self.name.casefold()=='openclaw-local':
                    raise AssertionError('Forbidden case variant must be excluded before stat')
                return self.entry.stat(**kwargs)
        @contextmanager
        def guarded(path):
            with original_scan(path) as rows:
                yield (Entry(entry) for entry in rows)
        with patch('wx_clawbot.project_registry.os.scandir',side_effect=guarded):
            preview=self.store.preview(str(self.workspace))
        self.assertNotIn(name,{row['alias'] for row in preview['added']})
        self.initialize()
        with self.assertRaises(ProjectError):
            self.change('add',name=name,alias='case-variant')

    def test_external_nested_broken_and_duplicate_links_are_not_registered(self):
        outside = self.base / 'outside'; outside.mkdir()
        nested = self.a / 'nested'; nested.mkdir()
        for name, target in [('escape', outside), ('deep', nested), ('broken', self.base/'absent'), ('alias-one', self.a)]:
            (self.workspace / name).symlink_to(target, target_is_directory=True)
        preview = self.store.preview(str(self.workspace))
        roots = [v['root'] for v in preview['projects']]
        self.assertEqual(len(set(roots)), 2)
        self.initialize()
        for name in ('escape', 'deep', 'broken', '../outside', str(outside), '.', '..'):
            with self.subTest(name=name), self.assertRaises(ProjectError):
                self.change('add', name=name)

    def test_scan_bound_rejects_incomplete_preview(self):
        for i in range(1023):
            (self.workspace / ('item-' + str(i))).touch()
        with self.assertRaisesRegex(ProjectError, '1024'):
            self.store.preview(str(self.workspace))
        self.assertFalse(self.config.exists())

    def test_configuration_size_and_project_capacity_reject_without_partial_commit(self):
        self.config.write_bytes(b' '*65537)
        with self.assertRaises(ConfigError):load_config(self.config)
        self.config.unlink()  # Owned malformed fixture; never a user's configuration.
        self.initialize();before=self.config.read_bytes()
        for i in range(255):(self.workspace/('project-'+str(i))).mkdir()
        with self.assertRaisesRegex(ProjectError,'256'):self.store.preview(str(self.workspace))
        self.assertEqual(self.config.read_bytes(),before)

    def test_scan_missing_file_permission_and_vanished_entry_fail_without_write(self):
        from contextlib import contextmanager
        self.initialize();before=self.config.read_bytes()
        plain=self.base/'plain-file';plain.write_text('fixture')
        for root in (self.base/'missing',plain):
            with self.subTest(root=root),self.assertRaises(ProjectError):
                self.store.preview(str(root))
        with patch('wx_clawbot.project_registry.os.scandir',side_effect=PermissionError('fixture denied')):
            with self.assertRaises(ProjectError):self.store.preview(str(self.workspace))
        class Vanished:
            name='vanished'
            def stat(self,**kwargs):raise FileNotFoundError('entry disappeared')
        @contextmanager
        def vanished(_):yield iter((Vanished(),))
        with patch('wx_clawbot.project_registry.os.scandir',side_effect=vanished):
            with self.assertRaises(ProjectError):self.store.preview(str(self.workspace))
        self.assertEqual(self.config.read_bytes(),before)

    def test_disk_full_before_replace_keeps_original_registry_readable(self):
        import errno
        self.initialize();before=self.config.read_bytes()
        with patch('wx_clawbot.project_registry.os.fsync',side_effect=OSError(errno.ENOSPC,'fixture full')):
            with self.assertRaises(OSError):self.change('remove',name='one')
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(len(ProjectStore(self.config,self.private).config.projects),2)

    def test_legacy_config_not_rewritten_and_init_preserves_external_alias(self):
        outside = self.base / 'legacy'; outside.mkdir()
        self.config.write_text(json.dumps({'projects':[{'alias':'legacy-name','root':str(outside)}]})); self.config.chmod(0o600)
        self.store = ProjectStore(self.config, self.private); raw = self.config.read_bytes()
        self.assertEqual(self.store.plan('list')[0]['projects'][0]['alias'], 'legacy-name')
        self.assertEqual(self.config.read_bytes(), raw)
        with self.assertRaisesRegex(ProjectError, '初始化'):
            self.change('add', name='one')
        self.initialize()
        self.assertIn(Project('legacy-name', outside), self.store.config.projects)
        backups = list((self.private / 'project-backups').glob('*.json'))
        self.assertEqual(len(backups),1); self.assertEqual(backups[0].read_bytes(),raw)

    def test_missing_registered_directory_is_diagnosable_in_new_format(self):
        self.initialize(); self.a.rename(self.workspace / 'moved')
        self.assertEqual(len(load_projects(self.config)),2)
        result,_=self.store.plan('check')
        self.assertIn('one', str(result['problems']))
        self.assertFalse(next(r for r in result['projects'] if r['alias']=='one')['available'])

    def test_external_edit_is_detected_without_overwriting(self):
        self.initialize(); original=json.loads(self.config.read_text()); original['revision']+=1
        self.config.write_text(json.dumps(original)); raw=self.config.read_bytes()
        with self.assertRaisesRegex(ProjectError,'外部修改'):
            self.change('remove',name='one')
        self.assertEqual(self.config.read_bytes(),raw)

    def test_failed_replace_preserves_original_and_cleans_owned_temp(self):
        self.initialize(); raw=self.config.read_bytes()
        with patch('wx_clawbot.project_registry.os.replace',side_effect=OSError('disk fault')):
            with self.assertRaises(OSError):
                self.change('remove',name='one')
        self.assertEqual(self.config.read_bytes(),raw)
        self.assertEqual(list(self.private.glob('.projects-*')),[])

    def test_failed_backup_preserves_original(self):
        self.initialize(); raw=self.config.read_bytes()
        with patch('wx_clawbot.project_registry.private_directory', side_effect=OSError('backup fault')):
            with self.assertRaises(OSError):
                self.change('remove',name='one')
        self.assertEqual(self.config.read_bytes(),raw)

    def test_same_request_replay_cannot_remove_readded_project(self):
        self.initialize()
        result,payload=self.store.plan('remove',name='one',request='same-request');self.store.commit(payload)
        self.change('add',name='one')
        replay,payload=self.store.plan('remove',name='one',request='same-request')
        self.assertEqual(replay['status'],'already_committed'); self.assertIsNone(payload)
        self.assertIn(Project('one',self.a),self.store.config.projects)
        with self.assertRaises(ProjectError):
            self.store.plan('remove',name='two',request='same-request')
        self.assertEqual(self.store.plan('check',request='same-request')[0]['request']['revision'],result['revision'])

    def test_duplicate_json_keys_and_unknown_config_fields_are_rejected(self):
        for raw in ('{"projects":[],"projects":[]}', '{"projects":[],"credentials":"PRIVATE"}'):
            self.config.write_text(raw)
            with self.assertRaises(ConfigError): load_config(self.config)

    def test_symlink_config_or_forbidden_config_location_rejected(self):
        other=self.private/'other.json';other.write_text('{"projects":[]}');self.config.symlink_to(other)
        with self.assertRaises(ProjectError): ProjectStore(self.config,self.private)
        with self.assertRaises(ProjectError): ProjectStore(self.base/'openclaw-local/config.json',self.private)

    def test_parser_space_subcommands_compatibility_and_literal_arguments(self):
        self.assertEqual(parse_project('add "sample app" --alias sample-app'),{'action':'add','name':'sample app','alias':'sample-app'})
        self.assertEqual(parse_command('/project').name,'project')
        self.assertEqual(parse_command('/projects').name,'projects')
        for text in ('init --root /tmp', 'add', 'remove', 'unknown', 'list extra', 'add a --alias b extra', 'add "bad'):
            with self.subTest(text=text),self.assertRaises(CommandError): parse_project(text)


class OfflineProjectTests(RegistryFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_registry(); self.initialize()

    async def test_stopped_cli_operations_read_and_write_same_registry(self):
        await project_operation(self.config,self.private,'remove',name='one')
        await project_operation(self.config,self.private,'add',name='one')
        result=await project_operation(self.config,self.private,'list')
        self.assertEqual({p['alias'] for p in result['projects']},{'one','two'})

    async def test_real_cli_init_preview_and_apply_keep_workspace_and_state_root_distinct(self):
        import sys
        private=self.base/'new-private'
        arguments=[sys.executable,'-I','-m','wx_clawbot','project','init','--root',str(self.workspace),
                   '--state-dir',str(private),'--config',str(private/'config.json')]
        async def command(extra=()):
            child=await asyncio.create_subprocess_exec(*arguments,*extra,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            stdout,stderr=await asyncio.wait_for(child.communicate(),5)
            self.assertEqual(child.returncode,0,stderr.decode());return json.loads(stdout)
        preview=await command();self.assertEqual(preview['status'],'preview')
        self.assertFalse((private/'config.json').exists())
        committed=await command(('--apply','--confirm',preview['confirm']))
        self.assertEqual(committed['status'],'committed')
        result=load_config(private/'config.json')
        self.assertEqual(result.workspace_root,self.workspace)
        self.assertEqual({p.alias for p in result.projects},{'one','two'})

    async def test_stopped_two_process_safe_edits_do_not_lose_updates(self):
        # Real processes share the same edit and consumer locks. A conflict may reject,
        # but must never overwrite a successful independent removal.
        import sys
        commands=[]
        for name in ('one','two'):
            commands.append(await asyncio.create_subprocess_exec(sys.executable,'-I','-m','wx_clawbot','project','remove',name,
                '--config',str(self.config),'--state-dir',str(self.private),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE))
        values=[]
        for proc in commands:
            stdout,stderr=await proc.communicate();self.assertFalse(stderr);values.append(json.loads(stdout))
        removed={name for name,result in zip(('one','two'),values) if result.get('status')=='committed'}
        self.assertTrue(removed)
        remaining={p.alias for p in load_projects(self.config)}
        self.assertEqual(remaining,{'one','two'}-removed)

    async def test_process_exit_after_config_commit_preserves_revocation_on_readd_and_restore(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from wx_clawbot.channels.wechat import Credentials
        from wx_clawbot.controller import target_record
        from wx_clawbot.routing import Target
        from wx_clawbot.runtime_state import RuntimeState
        from wx_clawbot.runtime_lifecycle import BridgeRuntime
        from wx_clawbot.project_registry import ProjectManager
        from wx_clawbot.hosts.lifecycle import HostLifecycle
        from wx_clawbot.hosts.visible import LaunchRegistry
        credentials=Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','fixture-token')
        session=SimpleNamespace(target=Target('fixture-two','two',self.b,'managed'),
            binding=SimpleNamespace(thread_id='fixture-thread-two',runtime_identity=(1,2),native_session_id='fixture-native-two'))
        state=await RuntimeState.open(self.private/'runtime.sqlite3',credentials)
        original={'version':2,'revision':1,'registry_revision':1,'mode':'unbound','project':'two','cwd':str(self.b),
                  'target':None,'observer':None,'last_managed':[target_record(session)],'unrestored_selection':None}
        await state.save_routes(original);await state.close()
        code='''import asyncio,os,sys
from pathlib import Path
from wx_clawbot.project_registry import ProjectStore
from wx_clawbot.project_control import project_operation
commit=ProjectStore.commit
def crash(self,payload):
    commit(self,payload)
    os._exit(73)
ProjectStore.commit=crash
asyncio.run(project_operation(Path(sys.argv[1]),Path(sys.argv[2]),'remove',name='two',request='crash-after-commit'))
'''
        child=await asyncio.create_subprocess_exec(sys.executable,'-I','-c',code,str(self.config),str(self.private),
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await asyncio.wait_for(child.communicate(),5)
        self.assertEqual(child.returncode,73,stderr.decode());self.assertEqual(stdout,b'')
        self.assertEqual({p.alias for p in load_projects(self.config)},{'one'})
        await project_operation(self.config,self.private,'add',name='two',request='after-crash-readd')
        state=await RuntimeState.open(self.private/'runtime.sqlite3',credentials);self.addAsyncCleanup(state.close)
        self.assertEqual(await state.load_routes(),original)  # Reproduce the actual stale-row crash window.
        host=HostLifecycle(SimpleNamespace());self.addAsyncCleanup(host.close)
        starter=SimpleNamespace(registry=LaunchRegistry(self.private/'launches'),start=AsyncMock())
        store=ProjectStore(self.config,self.private)
        runtime=BridgeRuntime(store.config.projects,state,starter,host,None,None,self.base)
        manager=ProjectManager(store,runtime);runtime.project_manager=manager
        await runtime.initialize();self.assertIsNone(runtime.controller.routes.cwd)
        controller=runtime.controller;controller.native_ready=True
        controller.catalog.sessions={session.target.session_id:session}
        controller.catalog.require=AsyncMock(return_value=session)
        controller._refresh=AsyncMock(return_value=(session,))
        await controller.restore()
        self.assertEqual(controller.last_managed,{})
        self.assertIsNone(controller.routes.target)
        self.assertEqual((await manager.execute('check',request='crash-after-commit'))['request']['revision'],2)

    async def test_startup_lock_then_unverified_consumer_never_allows_direct_file_fallback(self):
        import sys
        from wx_clawbot.channels.http import ProtocolError
        before=self.config.read_bytes()
        code='''import sys
from pathlib import Path
from wx_clawbot.channels.private import private_lease
from wx_clawbot.operations import ForegroundInstance
root=Path(sys.argv[1])
with private_lease(root/'project-edit.lock'):
    print('startup_locked',flush=True)
    sys.stdin.readline()
    with private_lease(root/'channel-consumer.lock'):
        instance=ForegroundInstance(root)
        print('consumer_locked',flush=True)
        sys.stdin.readline()
        instance.close()
'''
        child=await asyncio.create_subprocess_exec(sys.executable,'-I','-c',code,str(self.private),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            self.assertEqual(await asyncio.wait_for(child.stdout.readline(),5),b'startup_locked\n')
            with self.assertRaises((ProjectError,ProtocolError)):
                await project_operation(self.config,self.private,'remove',name='one',request='during-startup')
            self.assertEqual(self.config.read_bytes(),before)
            child.stdin.write(b'continue\n');await child.stdin.drain()
            self.assertEqual(await asyncio.wait_for(child.stdout.readline(),5),b'consumer_locked\n')
            with self.assertRaises(ProjectError):
                await project_operation(self.config,self.private,'remove',name='one',request='unverified-started')
            self.assertEqual(self.config.read_bytes(),before)
        finally:
            child.stdin.close()
            await asyncio.wait_for(child.wait(),5)
        self.assertEqual(child.returncode,0,(await child.stderr.read()).decode())
        await project_operation(self.config,self.private,'remove',name='one',request='after-normal-exit')
        self.assertEqual({p.alias for p in load_projects(self.config)},{'two'})
