import sqlite3
from contextlib import closing
from unittest.mock import patch

from test_runtime_state import RuntimeFixture
from wx_clawbot import schema
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.runtime_state import RuntimeState


class PerformanceSchemaTests(RuntimeFixture):
    async def prepare_v3(self):
        task = await self.admit()
        await self.state.queue_reply('historic','frozen source\n')
        await self.state.close()
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            for statement in schema.PERFORMANCE_UPGRADE:
                db.execute('DROP INDEX '+statement.split()[2])
            db.execute('PRAGMA user_version=3')
            db.commit()
        return task

    def rows(self, path=None):
        with closing(sqlite3.connect(path or self.root/'runtime.sqlite3')) as db:
            names=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {name:db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall() for name in names}

    async def test_v3_upgrade_preserves_every_business_row_and_backup(self):
        await self.prepare_v3()
        before = self.rows()
        result=schema.upgrade(self.root,self.credentials)
        self.assertEqual((result['from_version'],result['to_version']),(3,4))
        self.assertEqual(self.rows(),before)
        self.assertEqual(self.rows(self.root/result['backup']),before)
        self.assertEqual(schema.upgrade(self.root,self.credentials)['status'],'current')
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            self.assertEqual(schema.validate(db,self.credentials),4)

    async def test_v3_failure_after_indexes_rolls_back_data_version_and_indexes(self):
        await self.prepare_v3()
        before = self.rows()
        original=schema.apply_steps
        def fail(db,credentials):
            original(db,credentials)
            raise sqlite3.OperationalError('synthetic after-DDL failure')
        with patch.object(schema,'apply_steps',side_effect=fail), self.assertRaises(sqlite3.OperationalError):
            schema.upgrade(self.root,self.credentials)
        self.assertEqual(self.rows(),before)
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            self.assertEqual(schema.validate(db,self.credentials),3)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='reply_task_kind'").fetchone())

    async def test_runtime_never_opens_v3_as_v4_and_missing_index_is_not_accepted(self):
        await self.prepare_v3()
        before=self.rows()
        with self.assertRaises(schema.UpgradeRequired):
            await RuntimeState.open(self.root/'runtime.sqlite3',self.credentials)
        self.assertEqual(self.rows(),before)
        schema.upgrade(self.root,self.credentials)
        with closing(sqlite3.connect(self.root/'runtime.sqlite3')) as db:
            db.execute('DROP INDEX reply_task_kind')
            with self.assertRaises(ProtocolError):
                schema.validate(db,self.credentials)
