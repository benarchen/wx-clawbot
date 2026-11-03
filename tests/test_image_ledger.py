import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_runtime_state import RuntimeFixture
from test_retention import NOW
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.private import private_directory
from wx_clawbot.image_files import image_path, verify_image_file, write_image_file
from wx_clawbot.retention import maintain


class ImageLedgerTests(RuntimeFixture):
    async def image(self, *, state='pending'):
        task = await self.admit()
        now = NOW - 14 * 86400
        await self.state._call(lambda: self.state.db.execute("""INSERT INTO attachments
            (id,message_id,item_index,task_id,media,state,created_at,updated_at)
            VALUES('image-fixture','1',0,?,'{"aeskey":"private-test-key"}',?,?,?)""", (task['id'], state, now, now)))
        return task

    async def prepared(self):
        task = await self.image()
        data = b'fixture-file-for-lifecycle-test'
        filename = 'a' * 32 + '.png'
        digest = hashlib.sha256(data).hexdigest()
        await self.state.prepare_attachment_file('image-fixture', filename=filename, sha256=digest,
                                                byte_size=len(data), format='PNG', width=2, height=2)
        return task, filename, data, digest

    async def test_preparation_is_durable_before_file_and_ready_requires_exact_file(self):
        task, filename, data, digest = await self.prepared()
        row = (await self.state.attachments(task_id=task['id']))[0]
        self.assertEqual((row['state'], row['filename']), ('preparing', filename))
        with self.assertRaises((ProtocolError, FileNotFoundError)):
            await self.state.finish_attachment('image-fixture')
        path = write_image_file(self.root, filename, data, digest)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        await self.state.finish_attachment('image-fixture')
        row = (await self.state.attachments(task_id=task['id']))[0]
        self.assertEqual((row['state'], row['media']), ('ready', '{}'))
        self.assertEqual(verify_image_file(self.root, filename, digest, len(data)), path)

    async def test_bad_key_material_is_discarded_on_public_failure(self):
        task = await self.image()
        await self.state.finish_attachment('image-fixture', error_code='invalid_image')
        row = (await self.state.attachments(task_id=task['id']))[0]
        self.assertEqual((row['state'], row['media'], row['error_code']), ('failed', '{}', 'invalid_image'))
        with self.assertRaises(ValueError):
            await self.state.finish_attachment('image-fixture', error_code='token=secret')

    async def test_prepared_identity_cannot_be_retargeted_and_bad_paths_refuse(self):
        await self.prepared()
        with self.assertRaises(ProtocolError):
            await self.state.prepare_attachment_file('image-fixture', filename='b'*32+'.png',sha256='0'*64,
                                                    byte_size=1,format='PNG',width=1,height=1)
        for name in ('../victim.png', '/tmp/victim.png', 'not-generated.png'):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                image_path(self.root, name)

    async def test_file_mutation_and_partial_file_require_reconciliation(self):
        _, filename, data, digest = await self.prepared()
        directory = private_directory(self.root / 'attachments')
        partial = directory / (filename + '.part')
        partial.write_bytes(b'incomplete')
        partial.chmod(0o600)
        with self.assertRaises(ProtocolError):
            write_image_file(self.root, filename, data, digest)
        self.assertFalse((directory / filename).exists())
        self.assertEqual(partial.read_bytes(), b'incomplete')

    async def test_unknown_task_and_unknown_delivery_keep_aged_files(self):
        task, filename, data, digest = await self.prepared()
        path = write_image_file(self.root, filename, data, digest)
        await self.state.finish_attachment('image-fixture')
        await self.state.task_update(task['id'], 'unknown')
        await self.state.handled('1')
        await self.state._call(lambda: self.state.db.execute('UPDATE attachments SET updated_at=?', (NOW-60*86400,)))
        await self.state.close()
        result = maintain(self.root, self.credentials, apply=True, now=NOW)
        self.assertEqual(result['changed_rows']['attachment_bodies'], 0)
        self.assertTrue(path.exists())

    async def test_settled_attachment_cleanup_is_explicit_and_keeps_dedup_record(self):
        task, filename, data, digest = await self.prepared()
        path = write_image_file(self.root, filename, data, digest)
        await self.state.finish_attachment('image-fixture')
        await self.state.task_finish(task['id'], 'completed', 'result')
        reply = await self.state.claim_reply()
        await self.state.finish_reply(reply['id'], 'accepted', 7)
        await self.state.handled('1')
        await self.state._call(lambda: self.state.db.execute('UPDATE attachments SET updated_at=?', (NOW-14*86400,)))
        await self.state._call(lambda: self.state.db.execute('UPDATE tasks SET updated_at=?', (NOW-14*86400,)))
        await self.state._call(lambda: self.state.db.execute('UPDATE outbox SET created_at=?', (NOW-14*86400,)))
        plan = maintain(self.root, self.credentials, now=NOW)
        self.assertEqual(plan['eligible_rows']['attachment_bodies'], 1)
        self.assertTrue(path.exists())
        await self.state.close()
        maintain(self.root, self.credentials, apply=True, now=NOW)
        self.assertFalse(path.exists())
        await self.restart()
        row = (await self.state.attachments(task_id=task['id']))[0]
        self.assertEqual((row['state'], row['filename']), ('released', None))
        self.assertEqual(await self.state._call(lambda: self.state.db.execute('SELECT count(*) FROM inbox').fetchone()), (1,))

    async def test_database_failure_never_deletes_files_before_commit(self):
        task, filename, data, digest = await self.prepared()
        path = write_image_file(self.root, filename, data, digest)
        await self.state.task_finish(task['id'], 'cancelled', 'cancelled')
        reply = await self.state.claim_reply()
        await self.state.finish_reply(reply['id'], 'accepted', 7)
        await self.state._call(lambda: self.state.db.execute('UPDATE attachments SET updated_at=?', (NOW-14*86400,)))
        await self.state._call(lambda: self.state.db.execute("CREATE TRIGGER reject_release BEFORE UPDATE ON attachments BEGIN SELECT RAISE(ABORT,'injected failure'); END"))
        await self.state.close()
        with self.assertRaises(sqlite3.IntegrityError):
            maintain(self.root, self.credentials, apply=True, now=NOW)
        self.assertTrue(path.exists())

    async def test_released_file_deletion_failure_retains_retryable_reference(self):
        task, filename, data, digest = await self.prepared()
        path = write_image_file(self.root, filename, data, digest)
        await self.state._call(lambda: self.state.db.execute("UPDATE attachments SET state='released'"))
        await self.state.close()
        with patch('wx_clawbot.image_files.remove_released_file', side_effect=OSError('injected disk error')), self.assertRaises(OSError):
            maintain(self.root, self.credentials, apply=True, now=NOW)
        with closing(sqlite3.connect(self.root / 'runtime.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT filename FROM attachments').fetchone(), (filename,))
        self.assertTrue(path.exists())
        self.assertEqual(maintain(self.root, self.credentials, now=NOW)['released_files_pending'], 1)
        maintain(self.root, self.credentials, apply=True, now=NOW)
        self.assertFalse(path.exists())

    async def test_symlink_cannot_delete_another_file_during_explicit_cleanup(self):
        _, filename, data, digest = await self.prepared()
        directory = private_directory(self.root / 'attachments')
        victim = self.root / 'unrelated'
        victim.write_bytes(b'preserve')
        (directory / filename).symlink_to(victim)
        await self.state._call(lambda: self.state.db.execute("UPDATE attachments SET state='released'"))
        await self.state.close()
        with self.assertRaises(ProtocolError):
            maintain(self.root, self.credentials, apply=True, now=NOW)
        self.assertEqual(victim.read_bytes(), b'preserve')
