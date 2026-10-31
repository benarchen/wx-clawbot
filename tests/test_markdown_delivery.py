"""New rendering freezes once; historical delivery is never passed to rendering."""
import asyncio
import hashlib
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_runtime_state import RuntimeFixture
from wx_clawbot.channels.wechat import DeliveryUnknown
from wx_clawbot.delivery import Sender
from wx_clawbot.output import render_segments


class MarkdownDeliveryTests(RuntimeFixture):
    async def test_prepared_command_segment_is_frozen_without_second_render(self):
        await self.admit()
        segment = render_segments('# 标题\n\n```text\nx = 1\n```\n')[0]
        with patch('wx_clawbot.runtime_state.render_segments', side_effect=AssertionError('second render')):
            self.assertTrue(await self.state.queue_reply('prepared', segment))
        self.assertEqual((await self.state.claim_reply())['text'], segment.text)

    async def test_historical_unknown_and_rejected_retries_keep_exact_frozen_body_and_hash(self):
        await self.admit()
        original = '# legacy title\u2028旧回执\n\n    literal raw code\n'
        await self.state._call(lambda: self.state._queue_reply('legacy', original, 2))
        expected_hash = hashlib.sha256(original.encode()).hexdigest()
        before = await self.state.tasks()
        api = SimpleNamespace(send_text=AsyncMock(side_effect=[DeliveryUnknown('uncertain'), {'ret': 0}]))
        with patch('wx_clawbot.runtime_state.render_segments', side_effect=AssertionError('old body re-rendered')):
            await Sender(self.state, api).once()
            await self.restart()
            self.assertFalse(await Sender(self.state, api).once())
            await self.state.retry_reply('legacy', confirm_unknown=True)
            await Sender(self.state, api).once()
        self.assertEqual([call.kwargs['text'] for call in api.send_text.await_args_list], [original, original])
        row = await self.state._call(lambda: self.state.db.execute('SELECT text,body_sha256 FROM outbox WHERE id=?', ('legacy',)).fetchone())
        self.assertEqual(row, (original, expected_hash))
        self.assertEqual(len(await self.state.tasks()), len(before))
        self.assertEqual((await self.state.tasks())[0]['client_id'], before[0]['client_id'])

    async def test_long_reply_freezes_all_segments_in_one_transaction(self):
        source = '开头。\n\n' + '```text\n' + ('  abc\\def  \n\n' * 2000) + '```\n\n结尾。'
        parts = render_segments(source)
        await self.state._call(lambda: self.state.db.execute("""CREATE TRIGGER fail_markdown BEFORE INSERT ON outbox
            WHEN NEW.id='long-part-1' BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END"""))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.state.queue_reply('long', source)
        self.assertEqual(await self.state.delivery_counts(), {})
        await self.state._call(lambda: self.state.db.execute('DROP TRIGGER fail_markdown'))
        self.assertTrue(await self.state.queue_reply('long', source))
        rows = await self.state._call(lambda: self.state.db.execute('SELECT text FROM outbox ORDER BY rowid').fetchall())
        self.assertEqual([row[0] for row in rows], [part.text for part in parts])
        self.assertFalse(await self.state.queue_reply('long', source))

    async def test_code_with_trailing_blank_lines_never_creates_an_empty_payload(self):
        raw = '```text\n' + 'abc\n' * 5000 + '```\n\n'
        self.assertTrue(await self.state.queue_reply('code-tail', raw))
        rows = await self.state._call(lambda: self.state.db.execute('SELECT text FROM outbox ORDER BY rowid').fetchall())
        self.assertTrue(all(row[0].strip() for row in rows))
        self.assertTrue(rows[-1][0].endswith('```\n\n'))

    async def test_render_does_not_hold_database_worker_or_event_loop(self):
        started, release = threading.Event(), threading.Event()
        original = render_segments
        def delayed(text, **kwargs):
            started.set()
            if not release.wait(2):
                raise AssertionError('test release timeout')
            return original(text, **kwargs)
        with patch('wx_clawbot.runtime_state.render_segments', side_effect=delayed):
            worker = asyncio.create_task(self.state.queue_reply('long', 'render text'))
            try:
                await asyncio.wait_for(asyncio.to_thread(started.wait), 1)
                self.assertEqual(await asyncio.wait_for(self.state.delivery_counts(), .5), {})
            finally:
                release.set()
                await worker
