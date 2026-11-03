import json
import io
import sqlite3
from contextlib import closing
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_runtime_state import RuntimeFixture
from wx_clawbot import admission_ops, schema
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.private import write_json
from wx_clawbot.cli import main


class AdmissionOperatorTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        write_json(self.root/'credentials.json',{'version':1,'owner_confirmed':True,'credentials':asdict(self.credentials)})
        await self.state.accept_batch({'ret':0,'msgs':[]},phase='runtime')
        self.task=await self.admit()
        await self.state._call(lambda:self.state.db.execute('UPDATE tasks SET target=? WHERE id=?',
            (json.dumps({'cwd':str(self.root),'thread_id':'fixture-thread','session_id':'fixture-session'}),self.task['id'])))
        await self.state.task_update(self.task['id'],'unknown',turn_id='fixture-turn',queue_id='fixture-queue')
        async def request(method,params):
            if method=='thread/queue/list':return {'data':[],'nextCursor':None}
            if method=='thread/turns/list':return {'data':[{'id':'fixture-turn','status':'completed','items':[
                {'type':'userMessage','clientId':self.task['client_id']}]}],'nextCursor':None}
            raise AssertionError(method)
        self.native=SimpleNamespace(inspect=AsyncMock(return_value={'id':'fixture-thread','cwd':str(self.root),'status':{'type':'idle'}}),
            rpc=SimpleNamespace(request=AsyncMock(side_effect=request)),close=AsyncMock())

    async def test_report_and_release_default_are_readonly_without_native(self):
        before=await self.state._call(lambda:list(self.state.db.iterdump()))
        with patch.object(admission_ops.CodexConnection,'connect',new=AsyncMock()) as connect:
            report=admission_ops.report(self.root,self.task['id'])
            self.assertFalse((await admission_ops.release(self.root,self.task['id']))['applied'])
            connect.assert_not_awaited()
        self.assertFalse(report['applied'])
        self.assertEqual(await self.state._call(lambda:list(self.state.db.iterdump())),before)
        for private in (self.credentials.token,self.credentials.owner_id,str(self.root),self.task['client_id']):
            self.assertNotIn(private,json.dumps(report))

    async def test_running_consumer_refuses_apply_before_native_connection(self):
        report=admission_ops.report(self.root,self.task['id'])
        with patch.object(admission_ops.CodexConnection,'connect',new=AsyncMock()) as connect:
            with self.assertRaises(ProtocolError):
                await admission_ops.release(self.root,self.task['id'],apply=True,confirm_report=report['confirm_report'],reason='fixture',socket=self.root/'socket')
            connect.assert_not_awaited()

    async def test_invalid_id_and_missing_apply_confirmation_never_connect_or_write(self):
        before=await self.state._call(lambda:list(self.state.db.iterdump()))
        with patch.object(admission_ops.CodexConnection,'connect',new=AsyncMock()) as connect:
            for identity in ('../wrong','', 't-'+('0'*32)):
                with self.subTest(identity=identity),self.assertRaises((ValueError,ProtocolError)):
                    admission_ops.report(self.root,identity)
            digest=admission_ops.report(self.root,self.task['id'])['confirm_report']
            for token,reason in ((None,'fixture'),(digest,None),(digest,' '),(digest,'x'*513)):
                with self.subTest(reason=reason),self.assertRaises(ValueError):
                    await admission_ops.release(self.root,self.task['id'],apply=True,confirm_report=token,reason=reason)
            connect.assert_not_awaited()
        self.assertEqual(await self.state._call(lambda:list(self.state.db.iterdump())),before)

    async def test_wrong_binding_is_not_silently_repaired(self):
        path=self.root/'credentials.json'
        original=json.loads(path.read_text());wrong=json.loads(path.read_text())
        wrong['credentials']['owner_id']='other-fixture-owner'
        write_json(path,wrong,replace=True)
        try:
            with self.assertRaisesRegex(ProtocolError,'binding'):
                admission_ops.report(self.root,self.task['id'])
            self.assertEqual(json.loads(path.read_text()),wrong)
        finally:write_json(path,original,replace=True)

    async def test_cli_documents_explicit_apply_and_rejects_force(self):
        out=io.StringIO()
        with redirect_stdout(out),self.assertRaises(SystemExit) as caught:
            main(['admission-release','--help'])
        self.assertEqual(caught.exception.code,0)
        for flag in ('--apply','--confirm-report','--reason','--task-id'):
            self.assertIn(flag,out.getvalue())
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as caught:
            main(['admission-release','--task-id',self.task['id'],'--state-dir',str(self.root),'--force'])
        self.assertEqual(caught.exception.code,2)

    async def test_verified_apply_is_audited_and_repeat_is_idempotent(self):
        report=admission_ops.report(self.root,self.task['id'])
        await self.state.close()
        with patch.object(admission_ops.CodexConnection,'connect',new=AsyncMock(return_value=self.native)) as connect:
            result=await admission_ops.release(self.root,self.task['id'],apply=True,confirm_report=report['confirm_report'],reason='verified fixture',socket=self.root/'socket')
            self.assertEqual(result['status'],'released')
            again=await admission_ops.release(self.root,self.task['id'],apply=True,confirm_report=report['confirm_report'],reason='verified fixture',socket=self.root/'socket')
            self.assertEqual(again['status'],'already_released')
            connect.assert_awaited_once()
        await self.restart()
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'],'unknown')
        self.assertEqual(await self.state.tasks(active_only=True),[])
        audit=await self.state._call(lambda:list(self.state.db.execute("SELECT evidence FROM occupancy_audit WHERE state='released'")))
        self.assertEqual(len(audit),1)
        self.assertEqual(json.loads(audit[0][0])['operator_report'],report['confirm_report'])

    async def test_stale_digest_and_active_native_refuse_without_releasing(self):
        report=admission_ops.report(self.root,self.task['id'])
        await self.state.task_update(self.task['id'],'unknown')
        await self.state.close()
        with patch.object(admission_ops.CodexConnection,'connect',new=AsyncMock(return_value=self.native)) as connect:
            with self.assertRaisesRegex(ProtocolError,'stale'):
                await admission_ops.release(self.root,self.task['id'],apply=True,confirm_report=report['confirm_report'],reason='fixture',socket=self.root/'socket')
            connect.assert_not_awaited()
            report=admission_ops.report(self.root,self.task['id'])
            self.native.inspect.return_value['status']['type']='active'
            with self.assertRaises(ValueError):
                await admission_ops.release(self.root,self.task['id'],apply=True,confirm_report=report['confirm_report'],reason='fixture',socket=self.root/'socket')
        await self.restart()
        self.assertEqual((await self.state.occupancy_snapshot(task_id=self.task['id']))[0]['occupancy']['state'],'holding')


class OccupancyMigrationTests(RuntimeFixture):
    async def v4(self):
        task=await self.admit()
        await self.state.task_update(task['id'],'unknown',turn_id='old-turn')
        await self.state.queue_reply('frozen','Original frozen result')
        await self.state.close()
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            db.execute('DROP INDEX task_unknown_history')
            for table in ('admission_waits','occupancy_audit','task_occupancy'):
                db.execute('DROP TABLE '+table)
            db.execute('PRAGMA user_version=4')
            db.commit()
        return task

    def rows(self):
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {n:db.execute('SELECT * FROM '+n+' ORDER BY rowid').fetchall() for n in names}

    async def test_v4_upgrade_preserves_old_rows_and_unknown_starts_holding(self):
        task=await self.v4()
        before=self.rows()
        plan=schema.inspect(self.root,self.credentials)
        self.assertEqual(plan['add_tables'],list(schema.V5_COLUMNS))
        self.assertEqual(self.rows(),before)
        report=schema.upgrade(self.root,self.credentials)
        after=self.rows()
        self.assertEqual({k:after[k] for k in before},before)
        self.assertEqual((report['from_version'],report['to_version']),(4,5))
        self.assertEqual(after['task_occupancy'][0][0:3],(task['id'],'holding',0))
        self.assertEqual(schema.upgrade(self.root,self.credentials)['status'],'current')

    async def test_v4_upgrade_failure_rolls_back_and_keeps_usable_backup(self):
        await self.v4()
        before=self.rows()
        original=schema.apply_steps
        def fail(db,credentials):
            original(db,credentials)
            raise sqlite3.OperationalError('fixture post-DDL failure')
        with patch.object(schema,'apply_steps',side_effect=fail),self.assertRaises(sqlite3.OperationalError):
            schema.upgrade(self.root,self.credentials)
        self.assertEqual(self.rows(),before)
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            self.assertEqual(schema.validate(db,self.credentials),4)
        backups=list((self.root/'backups').glob('runtime-v4-*.sqlite3'))
        self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(schema.validate(db,self.credentials),4)

    async def test_missing_or_changed_unknown_history_index_is_rejected(self):
        await self.state.close()
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            db.execute('DROP INDEX task_unknown_history')
            with self.assertRaisesRegex(ProtocolError,'index'):
                schema.validate(db,self.credentials)
            db.execute("CREATE INDEX task_unknown_history ON tasks(id) WHERE state='completed'")
            with self.assertRaisesRegex(ProtocolError,'index'):
                schema.validate(db,self.credentials)
