import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from wx_clawbot import schema
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.private import private_directory
from wx_clawbot.channels.wechat import Credentials


class ImageSchemaTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / '.tmp' / 'image-schema-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = private_directory(Path(self.temp.name))
        self.path = self.root / 'runtime.sqlite3'
        self.path.touch(mode=0o600)
        self.credentials = Credentials('fixture-bot', 'fixture-owner', 'https://ilinkai.weixin.qq.com/', 'fixture-token')
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript((Path(__file__).parent / 'fixtures/runtime-v1.sql').read_text())
            db.execute("INSERT INTO channel VALUES(1,'fixture-bot','fixture-owner','saved-cursor')")
            for statement in schema.UPGRADE:
                db.execute(statement)
            db.execute('PRAGMA user_version=2')
            db.execute("INSERT INTO inbox VALUES('9','old text','context',10,1,1,'handled',0,?)",
                       (hashlib.sha256(b'old text').hexdigest(),))
            db.execute("INSERT INTO routes VALUES(1,'{}',1)")
            db.execute("INSERT INTO tasks VALUES('legacy','9','client','{}','thread','old task','unknown',NULL,NULL,1,1)")
            db.commit()

    def test_v2_plan_is_read_only_and_names_image_changes(self):
        before = self.path.read_bytes()
        plan = schema.inspect(self.root, self.credentials)
        self.assertEqual((plan['from_version'], plan['to_version']), (2, 3))
        self.assertIn('attachments', plan['add_tables'])
        self.assertIn('tasks.input_items', plan['add_columns'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root / 'backups').exists())

    def test_v2_upgrade_preserves_legacy_routes_unknown_and_original_backup(self):
        report = schema.upgrade(self.root, self.credentials)
        self.assertEqual((report['from_version'], report['to_version']), (2, 3))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(schema.validate(db, self.credentials), 3)
            self.assertEqual(db.execute('SELECT state,input,input_items FROM tasks').fetchone(), ('unknown', 'old task', '[]'))
            self.assertEqual(db.execute('SELECT content FROM inbox').fetchone(), ('[]',))
            self.assertEqual(db.execute('SELECT snapshot FROM routes').fetchone(), ('{}',))
            self.assertEqual(db.execute('SELECT count(*) FROM attachments').fetchone(), (0,))
        with closing(sqlite3.connect(self.root / report['backup'])) as db:
            self.assertEqual(schema.validate(db, self.credentials), 2)
            self.assertEqual(db.execute('SELECT state FROM tasks').fetchone(), ('unknown',))

    def test_v2_failure_rolls_back_image_ddl_without_deleting_old_rows(self):
        original = schema.apply_steps
        def failure(db, credentials):
            original(db, credentials)
            raise sqlite3.OperationalError('injected post-DDL failure')
        with patch.object(schema, 'apply_steps', side_effect=failure), self.assertRaises(sqlite3.OperationalError):
            schema.upgrade(self.root, self.credentials)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(schema.validate(db, self.credentials), 2)
            self.assertEqual(db.execute('SELECT state FROM tasks').fetchone(), ('unknown',))

    def test_v2_extra_table_refuses_before_backup(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE other_data(value TEXT)')
        with self.assertRaises(ProtocolError):
            schema.upgrade(self.root, self.credentials)
        self.assertFalse((self.root / 'backups').exists())

    def test_missing_attachment_columns_are_not_accepted_as_v3(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA user_version=3')
            with self.assertRaises(ProtocolError):
                schema.validate(db, self.credentials)
