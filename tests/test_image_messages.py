import copy
import sqlite3

from test_runtime_state import RuntimeFixture
from test_wechat_state import message
from wx_clawbot.channels.messages import parse_message, parse_text
from wx_clawbot.channels.http import ProtocolError


def image_message(native_id=1, *, text=None):
    raw = message(native_id)
    image = {'type': 2, 'image_item': {'aeskey': '12' * 16,
             'media': {'encrypt_query_param': 'fixture-query', 'aes_key': 'fixture-encoded-key'}}}
    raw['item_list'] = [image] if text is None else [{'type': 1, 'text_item': {'text': text}}, image]
    return raw


class ImageMessageTests(RuntimeFixture):
    async def test_image_and_caption_keep_order_and_diagnostic_stays_text_only(self):
        raw = image_message(text='/stop this is image text')
        parsed, reason = parse_message(raw, self.credentials)
        self.assertIsNone(reason)
        self.assertEqual(parsed.text, '/stop this is image text')
        self.assertEqual([p['type'] for p in parsed.content], ['text', 'image'])
        self.assertIsNone(parsed.error)
        self.assertEqual(parse_text(raw, self.credentials)[1], 'non_text_message')

    async def test_media_metadata_cursor_and_attachment_commit_atomically(self):
        raw = image_message()
        await self.state._call(lambda: self.state.db.execute("CREATE TRIGGER reject_image BEFORE INSERT ON attachments BEGIN SELECT RAISE(ABORT,'injected failure'); END"))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.accept_batch({'ret': 0, 'msgs': [raw], 'get_updates_buf': 'not-committed'}, phase='runtime')
        self.assertEqual(await self.state.cursor(), '')
        self.assertEqual(await self.state._call(lambda: self.state.db.execute('SELECT count(*) FROM inbox').fetchone()), (0,))

    async def test_task_binding_copies_references_without_secret_keys(self):
        raw = image_message(text='describe this')
        await self.state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
        task = await self.state.task_intent('1', {'thread_id': 'fixture-thread'}, 'describe this')
        saved = await self.state.tasks(task_id=task['id'])
        rows = await self.state.attachments(task_id=task['id'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(saved['input_items'][1], {'type': 'image', 'attachment_id': rows[0]['id']})
        self.assertNotIn('aeskey', str(saved))
        self.assertNotIn('fixture-query', str(saved))

    async def test_task_insert_and_attachment_binding_are_one_transaction(self):
        await self.state.accept_batch({'ret': 0, 'msgs': [image_message()]}, phase='runtime')
        await self.state._call(lambda: self.state.db.execute("CREATE TRIGGER reject_binding BEFORE UPDATE ON attachments BEGIN SELECT RAISE(ABORT,'injected failure'); END"))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.task_intent('1', {'thread_id': 'fixture-thread'}, 'analyze image')
        self.assertEqual(await self.state.tasks(), [])
        self.assertIsNone((await self.state.attachments(message_id='1'))[0]['task_id'])

    async def test_handled_unadmitted_image_clears_keys_but_keeps_duplicate_tombstone(self):
        raw = image_message()
        await self.state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
        await self.state.handled('1')
        row = (await self.state.attachments(message_id='1'))[0]
        self.assertEqual((row['state'], row['media'], row['task_id']), ('failed', '{}', None))
        replay = await self.state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
        self.assertEqual(replay['duplicates'], 1)
        self.assertEqual(await self.state.tasks(), [])

    async def test_handled_admitted_image_keeps_material_needed_for_preparation(self):
        await self.state.accept_batch({'ret': 0, 'msgs': [image_message()]}, phase='runtime')
        task = await self.state.task_intent('1', {'thread_id': 'fixture-thread'}, 'describe image')
        await self.state.handled('1')
        row = (await self.state.attachments(task_id=task['id']))[0]
        self.assertEqual(row['state'], 'pending')
        self.assertIn('fixture-query', row['media'])

    async def test_restart_clears_unadmitted_stale_image_without_replaying_it(self):
        await self.state.accept_batch({'ret': 0, 'msgs': [image_message()]}, phase='runtime')
        await self.restart()
        row = (await self.state.attachments(message_id='1'))[0]
        self.assertEqual((row['state'], row['media']), ('failed', '{}'))
        self.assertEqual(await self.state.tasks(), [])

    async def test_image_digest_detects_changed_media_but_same_image_different_ids_survive(self):
        raw = image_message()
        first = await self.state.accept_batch({'ret': 0, 'msgs': [raw, image_message(2)]}, phase='runtime')
        self.assertEqual(len(first['accepted']), 2)
        replay = await self.state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
        self.assertEqual(replay['duplicates'], 1)
        changed = copy.deepcopy(raw)
        changed['item_list'][0]['image_item']['aeskey'] = '34' * 16
        result = await self.state.accept_batch({'ret': 0, 'msgs': [changed]}, phase='runtime')
        self.assertEqual(result['conflicts'], 1)
        self.assertEqual(len(await self.state.attachments(message_id='1')), 1)

    async def test_foreign_image_creates_no_metadata_or_reply_context(self):
        raw = image_message()
        raw['from_user_id'] = 'stranger'
        result = await self.state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
        self.assertEqual(result['rejected'], {'unknown_sender': 1})
        self.assertEqual(await self.state.attachments(message_id='1'), [])
        self.assertIsNone(await self.state.latest_context())

    async def test_multiple_images_and_unsupported_media_produce_owner_error_without_partial_content(self):
        for native_id, kind in [(1, 2), (2, 3)]:
            raw = image_message(native_id, text='must not execute alone')
            raw['item_list'].append({'type': kind, 'image_item': raw['item_list'][1]['image_item']})
            result = await self.state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
            incoming = result['accepted'][0]
            self.assertIn(incoming.error, {'multiple_images', 'unsupported_media'})
            self.assertEqual((incoming.text, incoming.content), ('', ()))
            self.assertEqual(await self.state.attachments(message_id=str(native_id)), [])

    async def test_invalid_image_field_is_public_error_and_not_a_native_task(self):
        raw = image_message()
        raw['item_list'][0]['image_item']['media']['full_url'] = False
        result = await self.state.accept_batch({'ret': 0, 'msgs': [raw]}, phase='runtime')
        self.assertEqual(result['accepted'][0].error, 'invalid_image')
        self.assertEqual(await self.state.attachments(message_id='1'), [])
