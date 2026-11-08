"""Live local IPC and project mutations against an isolated real bridge ledger."""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from test_project_registry import RegistryFixture
from test_wechat_state import message
from wx_clawbot.channels.private import write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project, load_config
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.hosts.visible import LaunchRegistry
from wx_clawbot.operations import ForegroundInstance
from wx_clawbot.project_control import ProjectServer, project_operation
from wx_clawbot.project_registry import ProjectError, ProjectManager
from wx_clawbot.project_registry import sanitize_routes
from wx_clawbot.routing import Target
from wx_clawbot.runtime_lifecycle import BridgeRuntime
from wx_clawbot.runtime_state import RuntimeState


class ProjectRuntimeTests(RegistryFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_registry(); self.initialize()
        loop=asyncio.get_running_loop();prior=loop.get_exception_handler();self.loop_errors=[]
        loop.set_exception_handler(lambda current,context:self.loop_errors.append(context))
        async def verify_no_unhandled_callbacks():
            await asyncio.sleep(0)
            loop.set_exception_handler(prior)
            self.assertFalse(self.loop_errors,[type(c.get('exception')).__name__ for c in self.loop_errors])
        self.addAsyncCleanup(verify_no_unhandled_callbacks)
        self.credentials=Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','fixture-token')
        self.state=await RuntimeState.open(self.private/'runtime.sqlite3',self.credentials)
        self.addAsyncCleanup(self.state.close)
        backend=SimpleNamespace(identity=AsyncMock(return_value=None),connect=AsyncMock(),launch=AsyncMock(),probe=AsyncMock(),wait_ready=AsyncMock())
        self.host=HostLifecycle(backend);self.addAsyncCleanup(self.host.close)
        self.starter=SimpleNamespace(registry=LaunchRegistry(self.private/'launches'),start=AsyncMock())
        self.runtime=BridgeRuntime(self.store.config.projects,self.state,self.starter,self.host,None,None,self.base)
        self.manager=ProjectManager(self.store,self.runtime);self.runtime.project_manager=self.manager
        await self.runtime.initialize()
        self.counter=0

    async def receive(self,text):
        self.counter+=1
        result=await self.state.accept_batch({'ret':0,'msgs':[message(self.counter,text=text)]},phase='runtime')
        return result['accepted'][0]

    async def command(self,text):
        await self.runtime.prepare(await self.receive(text))

    async def server(self):
        self.instance=ForegroundInstance(self.private);self.addCleanup(self.instance.close)
        self.control=ProjectServer(self.manager,self.instance);await self.control.start()
        self.addAsyncCleanup(self.control.close)
        return self.control

    async def test_add_and_remove_install_all_snapshots_without_restarting(self):
        controller=self.runtime.controller
        await self.manager.execute('remove',name='two',request='remove-two')
        self.assertEqual(set(controller.routes.projects),{'one'})
        self.assertEqual(set(controller.catalog.projects),{'one'})
        self.assertNotIn(self.b,controller.catalog.directories)
        self.assertEqual([p.alias for p in self.runtime.projects],['one'])
        await self.manager.execute('add',name='two',request='add-two')
        self.assertEqual(set(controller.routes.projects),{'one','two'})
        self.assertEqual(set(self.runtime.offline_controller().routes.projects),{'one','two'})
        self.assertIs(self.runtime.controller,controller)
        self.host.backend.launch.assert_not_awaited()

    async def test_selected_or_observed_project_cannot_be_removed(self):
        routes=self.runtime.controller.routes
        for field in ('target','observer'):
            with self.subTest(field=field):
                setattr(routes,field,Target('fixture','one',self.a))
                with self.assertRaisesRegex(ProjectError,'不能取消'):
                    await self.manager.execute('remove',name='one',request='remove-'+field)
                setattr(routes,field,None)
        self.assertEqual(len(self.store.config.projects),2)

    async def test_durable_selection_blocks_remove_while_native_is_offline(self):
        await self.state.save_routes({'target':{'project_alias':'one'},'observer':None})
        with self.assertRaisesRegex(ProjectError,'输入目标'):
            await self.manager.execute('remove',name='one',request='offline-target')

    async def test_incoming_selection_reservation_blocks_remove_before_execution(self):
        controller=self.runtime.controller
        pending=controller.prepare(await self.receive('/cd one'))
        try:
            with self.assertRaisesRegex(ProjectError,'意图'):
                await self.manager.execute('remove',name='one',request='reserved-remove')
        finally:
            await pending
        self.assertFalse(controller.project_reservations)

    async def test_unstarted_dispatch_is_reserved_and_old_prepare_cannot_cross_change(self):
        controller=self.runtime.controller;controller.native_ready=True
        controller.routes.target=Target('one-session','one',self.a)
        controller.engine=SimpleNamespace(submit=AsyncMock())
        prepared=controller.prepare(await self.receive('task for one'))
        controller.routes.target=None
        with self.assertRaisesRegex(ProjectError,'意图'):
            await self.manager.execute('remove',name='one',request='before-submit')
        await self.manager.execute('remove',name='two',request='change-other-project')
        await prepared
        controller.engine.submit.assert_not_awaited()
        self.assertFalse(controller.project_reservations)

    async def test_active_task_and_unknown_occupancy_block_but_released_unknown_does_not(self):
        incoming=await self.receive('task')
        record={'thread_id':'fixture-thread','session_id':'fixture-session','project_alias':'one','cwd':str(self.a)}
        task=await self.state.task_intent(incoming.message_id,record,'task')
        for state in ('prepared','received','queued','running','waiting_interaction','unknown'):
            with self.subTest(state=state):
                await self.state._call(lambda state=state:self.state.db.execute('UPDATE tasks SET state=? WHERE id=?',(state,task['id'])))
                with self.assertRaisesRegex(ProjectError,'任务或占用'):
                    await self.manager.execute('remove',name='one',request='blocked-'+state)
        # Construct a historical released fixture, without claiming production release evidence.
        await self.state._call(lambda:self.state.db.execute("UPDATE task_occupancy SET state='released' WHERE task_id=?",(task['id'],)))
        result=await self.manager.execute('remove',name='one',request='historical-unknown')
        self.assertEqual(result['status'],'committed')
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'],'unknown')

    async def test_launch_intent_blocks_remove_without_launching(self):
        write_json(self.private/'launches'/('a'*32+'.json'),{'project_alias':'one','phase':'unknown'})
        with self.assertRaisesRegex(ProjectError,'可见创建'):
            await self.manager.execute('remove',name='one',request='launch-blocked')
        self.starter.start.assert_not_awaited()

    async def test_new_registration_preserves_other_target_and_observer(self):
        routes=self.runtime.controller.routes; target=Target('selected-one','one',self.a)
        routes.target=routes.observer=target;routes.project=Project('one',self.a);routes.cwd=self.a
        third=self.workspace/'three';third.mkdir()
        await self.manager.execute('add',name='three',request='add-three')
        self.assertEqual(routes.target,target);self.assertEqual(routes.observer,target)
        self.assertEqual(routes.cwd,self.a)

    async def test_remove_invalidates_list_and_clears_only_removed_current_directory(self):
        routes=self.runtime.controller.routes
        routes.project=Project('one',self.a);routes.cwd=self.a; routes.snapshot(())
        await self.manager.execute('remove',name='one',request='clear-cwd')
        self.assertIsNone(routes.list);self.assertIsNone(routes.cwd);self.assertIsNone(routes.project)
        self.assertTrue(self.a.exists())

    async def test_zero_projects_keeps_management_and_offline_rebuild_usable(self):
        for name in ('one','two'):
            await self.manager.execute('remove',name=name,request='empty-'+name)
        self.assertEqual(self.runtime.projects,())
        self.assertEqual(self.runtime.offline_controller().routes.projects,{})
        await self.command('/project check');await self.command('/projects')
        count=await self.state._call(lambda:self.state.db.execute("SELECT count(*) FROM outbox WHERE state='pending'").fetchone()[0])
        self.assertGreater(count,0)
        await self.manager.execute('add',name='one',request='re-add-one')
        self.assertEqual(set(self.runtime.offline_controller().routes.projects),{'one'})

    async def test_wechat_project_parser_applies_immediately_and_queries_are_pure(self):
        await self.command('/project remove two')
        self.assertEqual(set(self.runtime.controller.routes.projects),{'one'})
        before=self.config.read_bytes()
        for command in ('/project','/project list','/project check','/projects'):
            await self.command(command)
        self.assertEqual(self.config.read_bytes(),before)
        self.starter.start.assert_not_awaited();self.host.backend.launch.assert_not_awaited()
        await self.command('/project add two')
        self.assertEqual(set(self.runtime.controller.routes.projects),{'one','two'})

    async def test_real_socket_cli_and_wechat_edits_share_live_registry(self):
        await self.server()
        result=await project_operation(self.config,self.private,'remove',name='two',request='ipc-remove')
        self.assertEqual(result['status'],'committed')
        await self.command('/project add two')
        result=await project_operation(self.config,self.private,'list')
        self.assertEqual({p['alias'] for p in result['projects']},{'one','two'})
        self.assertEqual(load_config(self.config).projects,self.runtime.projects)
        self.assertEqual(os.stat(self.control.path).st_mode & 0o777,0o600)

    async def test_live_init_uses_workspace_argument_without_colliding_with_private_state_root(self):
        await self.server()
        target=Target('fixture-selected','one',self.a);self.runtime.controller.routes.target=target
        preview=await project_operation(self.config,self.private,'init',root=str(self.workspace),request='live-preview')
        self.assertEqual(preview['status'],'preview')
        result=await project_operation(self.config,self.private,'init',root=str(self.workspace),apply=True,
                                       confirm=preview['confirm'],request='live-init-apply')
        self.assertEqual(result['status'],'committed')
        self.assertEqual(self.runtime.controller.routes.target,target)
        self.assertEqual(load_config(self.config).workspace_root,self.workspace)

    async def test_ipc_wrong_generation_config_and_unbounded_fields_rejected(self):
        await self.server(); before=self.config.read_bytes()
        for operation in ({'generation':'old','config':str(self.config),'operation':'remove','arguments':{'name':'one','request':'bad-generation'}},
                          {'generation':self.instance.record['generation'],'config':str(self.config)+'wrong','operation':'remove','arguments':{'name':'one'}},
                          {'generation':self.instance.record['generation'],'config':str(self.config),'operation':'remove','arguments':{'shell':'rm -rf'}}):
            reader,writer=await asyncio.open_unix_connection(self.control.path)
            writer.write(json.dumps(operation).encode()+b'\n');await writer.drain()
            result=json.loads(await reader.readline());writer.close();await writer.wait_closed()
            self.assertFalse(result['ok'])
        self.assertEqual(self.config.read_bytes(),before)

    async def test_concurrent_ipc_and_wechat_edits_have_no_lost_update(self):
        await self.server()
        await asyncio.gather(project_operation(self.config,self.private,'remove',name='one',request='ipc-one'),self.command('/project remove two'))
        self.assertEqual(load_config(self.config).projects,())
        self.assertEqual(self.runtime.projects,())

    async def test_real_cli_process_changes_active_instance_without_direct_file_fallback(self):
        import sys
        await self.server()
        proc=await asyncio.create_subprocess_exec(sys.executable,'-I','-m','wx_clawbot','project','remove','two',
            '--config',str(self.config),'--state-dir',str(self.private),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await asyncio.wait_for(proc.communicate(),5)
        self.assertEqual(proc.returncode,0,stderr.decode());self.assertEqual(json.loads(stdout)['status'],'committed')
        self.assertEqual(set(self.runtime.controller.routes.projects),{'one'})

    async def test_busy_unverified_or_old_version_instance_never_falls_back_to_file_write(self):
        raw=self.config.read_bytes()
        with self.assertRaises(ProjectError):
            await project_operation(self.config,self.private,'remove',name='one')
        self.instance=ForegroundInstance(self.private);self.addCleanup(self.instance.close)
        with self.assertRaises(ProjectError):
            await project_operation(self.config,self.private,'remove',name='one')
        self.assertEqual(self.config.read_bytes(),raw)

    async def test_precommit_fault_preserves_runtime_and_allows_next_valid_edit(self):
        with patch('wx_clawbot.project_registry.os.replace',side_effect=OSError('fault')):
            with self.assertRaises(OSError):
                await self.manager.execute('remove',name='two',request='failed-write')
        self.assertFalse(self.manager.failed)
        self.assertEqual(set(self.runtime.controller.routes.projects),{'one','two'})
        await self.manager.execute('remove',name='two',request='valid-next')
        self.assertEqual(set(self.runtime.controller.routes.projects),{'one'})

    async def test_postcommit_install_fault_disables_new_dispatch_without_rollback(self):
        self.runtime.controller.native_ready=True
        with patch.object(self.manager,'install',side_effect=RuntimeError('install failure')):
            with self.assertRaises(RuntimeError):
                await self.manager.execute('remove',name='two',request='committed-fault')
        self.assertTrue(self.manager.failed);self.assertFalse(self.runtime.controller.native_ready)
        self.assertEqual({p.alias for p in load_config(self.config).projects},{'one'})
        with self.assertRaises(ProjectError):
            await self.manager.execute('add',name='two',request='blocked-after-commit')

    async def test_request_replay_from_ipc_is_not_a_second_write(self):
        await self.server()
        args=dict(name='two',request='replayed-operation')
        first=await project_operation(self.config,self.private,'remove',**args)
        raw=self.config.read_bytes()
        again=await project_operation(self.config,self.private,'remove',**args)
        self.assertEqual(again['status'],'already_committed');self.assertEqual(again['revision'],first['revision'])
        self.assertEqual(self.config.read_bytes(),raw)

    async def test_disconnect_after_sending_mutation_keeps_committed_receipt_without_replay(self):
        await self.server()
        payload={'generation':self.instance.record['generation'],'config':str(self.config),'operation':'remove',
                 'arguments':{'name':'two','request':'lost-success-reply'}}
        _,writer=await asyncio.open_unix_connection(self.control.path)
        writer.write(json.dumps(payload).encode()+b'\n');await writer.drain()
        writer.close();await writer.wait_closed()  # The caller never reads a success response.
        async with asyncio.timeout(5):
            while self.store.config.revision<2:await asyncio.sleep(.01)
        self.assertEqual({p.alias for p in load_config(self.config).projects},{'one'})
        before=self.config.read_bytes()
        repeated=await project_operation(self.config,self.private,'remove',name='two',request='lost-success-reply')
        self.assertEqual(repeated['status'],'already_committed')
        self.assertEqual(self.config.read_bytes(),before)
        record=await project_operation(self.config,self.private,'check',request='lost-success-reply')
        self.assertEqual(record['request']['revision'],2)

    async def test_removed_then_readded_alias_never_restores_old_managed_authority(self):
        stale={'version':2,'revision':1,'mode':'unbound','project':'one','cwd':str(self.a),
               'target':None,'observer':None,'last_managed':[{'project_alias':'one','thread_id':'old-thread'},
                                                           {'project_alias':'two','thread_id':'other-thread'}]}
        await self.state.save_routes(stale)
        await self.manager.execute('remove',name='one',request='revoke-one')
        await self.manager.execute('add',name='one',request='register-one')
        saved=await self.state.load_routes()
        self.assertEqual(saved['last_managed'],[{'project_alias':'two','thread_id':'other-thread'}])
        # Simulate the exact crash window: config committed, route row still old.
        recovered=sanitize_routes(stale,self.store.config)
        self.assertEqual(recovered['last_managed'],[{'project_alias':'two','thread_id':'other-thread'}])
        self.assertIsNone(recovered['cwd'])

    async def test_registry_update_preserves_offline_durable_target_of_other_project(self):
        chosen={'project_alias':'one','thread_id':'old-one','cwd':str(self.a)}
        saved={'version':2,'revision':2,'mode':'focused','target':chosen,'observer':chosen,
               'project':'one','cwd':str(self.a),'last_managed':[]}
        await self.state.save_routes(saved)
        self.assertIsNone(self.runtime.controller.routes.target)
        await self.manager.execute('remove',name='two',request='keep-offline-one')
        actual=await self.state.load_routes()
        self.assertEqual(actual['target'],chosen);self.assertEqual(actual['observer'],chosen)

    async def test_unfinished_interaction_blocks_remove_without_active_task(self):
        import time
        now=time.time()
        row=('fixture-request','fixture-native','fixture-gen','fixture-thread','fixture-turn','method','{}',
             json.dumps({'project_alias':'one'}),now+60,'pending',now,now)
        await self.state._call(lambda:self.state.db.execute('INSERT INTO interactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',row))
        with self.assertRaisesRegex(ProjectError,'交互'):
            await self.manager.execute('remove',name='one',request='interaction-blocked')
        await self.state._call(lambda:self.state.db.execute("UPDATE interactions SET state='resolved'"))
        await self.manager.execute('remove',name='one',request='interaction-closed')

    async def test_socket_must_belong_to_exact_verified_process(self):
        await self.server(); before=self.config.read_bytes()
        with patch('wx_clawbot.project_control.peer_pid',return_value=-1):
            with self.assertRaisesRegex(ProjectError,'准确桥接'):
                await project_operation(self.config,self.private,'remove',name='one',request='wrong-peer')
        self.assertEqual(self.config.read_bytes(),before)

    async def test_persistent_install_fault_notifies_supervisor_and_readonly_check_remains(self):
        with patch.object(self.manager,'install',side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                await self.manager.execute('remove',name='two',request='fatal-install')
        self.assertTrue(self.manager.failure.is_set())
        with self.assertRaises(ProjectError):
            await self.manager.watch_failure()
        check=await self.manager.execute('check',request='fatal-install')
        self.assertEqual(check['request']['revision'],2)

    async def test_recoverable_post_replace_fault_converges_but_does_not_report_success(self):
        original=self.manager.install
        count=0
        def once(config):
            nonlocal count
            count+=1
            if count==1:raise RuntimeError('one install fault')
            original(config)
        with patch.object(self.manager,'install',side_effect=once):
            with self.assertRaises(RuntimeError):
                await self.manager.execute('remove',name='two',request='recoverable')
        self.assertFalse(self.manager.failed)
        self.assertEqual(set(self.runtime.controller.routes.projects),{'one'})
        self.assertEqual((await self.manager.execute('check',request='recoverable'))['request']['revision'],2)

    async def test_receive_during_remove_commit_window_cannot_submit_to_removed_project(self):
        controller=self.runtime.controller;controller.native_ready=True
        controller.routes.target=Target('one-session','one',self.a)
        controller.engine=SimpleNamespace(submit=AsyncMock())
        # Remove the input reference to test a genuinely overlapping one-shot send.
        controller.routes.target=None
        controller.routes.snapshot((Target('one-session','one',self.a),))
        original=self.manager.blockers; paused=asyncio.Event(); resume=asyncio.Event()
        async def delayed(alias):
            result=await original(alias);paused.set();await resume.wait();return result
        with patch.object(self.manager,'blockers',side_effect=delayed):
            removal=asyncio.create_task(self.manager.execute('remove',name='one',request='remove-first'))
            await paused.wait()
            work=controller.prepare(await self.receive('/send 1 fixture-task'))
            resume.set();await removal;await work
        controller.engine.submit.assert_not_awaited()
        self.assertNotIn('one',controller.routes.projects)

    async def test_wrong_peer_uid_and_oversized_request_are_rejected_without_write(self):
        await self.server();before=self.config.read_bytes()
        value={'generation':self.instance.record['generation'],'config':str(self.config),
               'operation':'remove','arguments':{'name':'one','request':'foreign-user'}}
        with patch('wx_clawbot.project_control.peer_uid',return_value=os.getuid()+1):
            reader,writer=await asyncio.open_unix_connection(self.control.path)
            writer.write(json.dumps(value).encode()+b'\n');await writer.drain()
            response=json.loads(await reader.readline());writer.close();await writer.wait_closed()
            self.assertFalse(response['ok'])
        reader,writer=await asyncio.open_unix_connection(self.control.path)
        writer.write(b'x'*65537+b'\n');await writer.drain()
        response=json.loads(await reader.readline());writer.close();await writer.wait_closed()
        self.assertFalse(response['ok']);self.assertEqual(self.config.read_bytes(),before)

    async def test_open_async_question_blocks_remove_until_closed(self):
        import time
        now=time.time()
        values={'public_id':'q-fixture','source':'fixture','thread_id':'thread-fixture','turn_id':'turn-fixture',
                'item_id':'item-fixture','revision':1,'questions':'[]','question_sha256':'fixture',
                'target':json.dumps({'project_alias':'one'}),'task_id':None,'generation':'fixture','state':'pending',
                'reason':'fixture','expires_at':now+60,'answer_client':None,'answer_text':None,'answer_sha256':None,
                'created_at':now,'updated_at':now,'closed_at':None}
        sql='INSERT INTO async_questions('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')'
        await self.state._call(lambda:self.state.db.execute(sql,tuple(values.values())))
        with self.assertRaisesRegex(ProjectError,'追问'):
            await self.manager.execute('remove',name='one',request='async-blocked')
        await self.state._call(lambda:self.state.db.execute("UPDATE async_questions SET closed_at=?",(now,)))
        await self.manager.execute('remove',name='one',request='async-closed')

    async def test_parent_fsync_failure_after_replace_has_committed_receipt_and_converged_runtime(self):
        original=os.fsync;count=0
        def disk_fault(fd):
            nonlocal count
            count+=1
            if count==3:raise OSError('parent directory sync fault')
            original(fd)
        with patch('wx_clawbot.project_registry.os.fsync',side_effect=disk_fault):
            with self.assertRaises(OSError):
                await self.manager.execute('remove',name='two',request='sync-unknown')
        self.assertGreaterEqual(count,3)
        self.assertFalse(self.manager.failed)
        self.assertEqual(set(self.runtime.controller.routes.projects),{'one'})
        self.assertEqual((await self.manager.execute('check',request='sync-unknown'))['request']['revision'],2)

    async def test_wrong_socket_permissions_fail_without_fallback_write(self):
        await self.server();before=self.config.read_bytes()
        self.control.path.chmod(0o644)
        try:
            with self.assertRaises(ProjectError):
                await project_operation(self.config,self.private,'remove',name='one')
        finally:self.control.path.chmod(0o600)
        self.assertEqual(self.config.read_bytes(),before)

    async def test_expected_disconnect_during_close_does_not_escape_server_callback(self):
        from unittest.mock import Mock
        await self.server();before=self.config.read_bytes()
        writer=SimpleNamespace(write=Mock(),drain=AsyncMock(),close=Mock(),
                               wait_closed=AsyncMock(side_effect=BrokenPipeError('client already closed')))
        with patch.object(self.control,'response',new=AsyncMock(return_value={'ok':False,'error':'fixture request rejected'})):
            await self.control.accept(SimpleNamespace(),writer)
        writer.close.assert_called_once()
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual((await project_operation(self.config,self.private,'list'))['status'],'ok')

    async def test_ipc_connection_capacity_rejects_excess_and_recovers_after_disconnect(self):
        await self.server();before=self.config.read_bytes();connections=[]
        try:
            for _ in range(17):
                connections.append(await asyncio.open_unix_connection(self.control.path))
                await asyncio.sleep(0)
            reads=[asyncio.create_task(reader.read(1)) for reader,_ in connections]
            try:
                done,_=await asyncio.wait(reads,timeout=2,return_when=asyncio.FIRST_COMPLETED)
                self.assertTrue(done)
                self.assertTrue(all(task.result()==b'' for task in done))
            finally:
                for task in reads:
                    if not task.done():task.cancel()
                await asyncio.gather(*reads,return_exceptions=True)
            self.assertLessEqual(len(self.control.jobs),16)
        finally:
            for _,writer in connections:writer.close()
            for _,writer in connections:
                try:await writer.wait_closed()
                except (ConnectionError,OSError):pass
            for _ in range(20):
                if not self.control.jobs:break
                await asyncio.sleep(.01)
        self.assertFalse(self.control.jobs)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual((await project_operation(self.config,self.private,'list'))['status'],'ok')
