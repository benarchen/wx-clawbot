import asyncio
import io
import threading
import unittest
from dataclasses import replace
from wx_clawbot.agents.rpc import OutcomeUnknown
from unittest.mock import AsyncMock, patch

from PIL import Image
import test_controller as controller_fixture
from test_image_messages import image_message
from wx_clawbot.channels.media import ImageError, validate_image
from wx_clawbot.routing import RouteError


class ImageControllerTests(unittest.IsolatedAsyncioTestCase):
    incoming = controller_fixture.ControllerTests.incoming
    command = controller_fixture.ControllerTests.command
    select = controller_fixture.ControllerTests.select

    async def asyncSetUp(self):
        await controller_fixture.ControllerTests.asyncSetUp(self)
        self.agent.capabilities = replace(self.agent.capabilities, image_input=True)
        self.addAsyncCleanup(self.engine.close)
        out = io.BytesIO()
        Image.new('RGB', (4, 4), 'red').save(out, format='PNG')
        self.data = out.getvalue()
        self.metadata = validate_image(self.data)

    async def image(self, text=None):
        self.counter += 1
        result = await self.state.accept_batch({'ret': 0, 'msgs': [image_message(self.counter, text=text)]}, phase='runtime')
        return result['accepted'][0]

    async def prepare_done(self):
        await asyncio.wait_for(asyncio.gather(*tuple(self.engine.image_jobs.values())), 2)

    async def test_unfocused_image_never_downloads_or_creates_native_task(self):
        with patch('wx_clawbot.images.download_image') as download:
            with self.assertRaises(RouteError):
                self.controller.prepare(await self.image())
        download.assert_not_called()
        self.assertEqual(await self.state.tasks(), [])
        self.queue.add.assert_not_awaited()

    async def test_unverified_image_runtime_refuses_before_download_or_task_admission(self):
        await self.select()
        self.agent.capabilities = replace(self.agent.capabilities, image_input=False)
        with patch('wx_clawbot.images.download_image') as download:
            await self.controller.prepare(await self.image())
        download.assert_not_called()
        self.assertEqual(await self.state.tasks(), [])
        self.queue.add.assert_not_awaited()

    async def test_image_slash_text_is_one_task_and_never_a_control_command(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image('/stop'))
            await self.prepare_done()
        await self.engine.drain_admission()
        self.queue.add.assert_awaited_once()
        call = self.queue.add.await_args
        self.assertEqual(call.args[0], '/stop')
        self.assertEqual([p['type'] for p in call.kwargs['input_items']], ['text', 'localImage'])
        self.assertEqual((await self.state.tasks())[0]['state'], 'queued')
        self.queue.request_interrupt.assert_not_awaited()

    async def test_slow_image_does_not_block_status_or_other_project_and_same_thread_cannot_overtake(self):
        await self.select()
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        def slow(_):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(2):
                raise ImageError('download_timeout')
            return self.data, self.metadata
        try:
            with patch('wx_clawbot.images.download_image', side_effect=slow):
                await self.controller.prepare(await self.image())
                await asyncio.wait_for(entered.wait(), 1)
                await asyncio.wait_for(self.command('/status'), .5)
                await self.command('same-thread-after-image')
                self.queue.add.assert_not_awaited()
                await self.command('/focus 1')
                await self.command('other-project-can-run')
                self.queue.add.assert_awaited_once()
                self.assertEqual(self.queue.add.await_args.args[0], 'other-project-can-run')
                release.set()
                await self.prepare_done()
            await self.engine.drain_admission()
            calls = self.queue.add.await_args_list
            self.assertEqual(len(calls), 3)
            self.assertIn('input_items', calls[1].kwargs)
            self.assertEqual(calls[2].args[0], 'same-thread-after-image')
            image_task = next(t for t in await self.state.tasks() if t['input_items'])
            self.assertEqual(image_task['target']['project_alias'], 'two')
        finally:
            release.set()

    async def test_cancelled_preparation_cannot_submit_after_worker_returns(self):
        await self.select()
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        def slow(_):
            loop.call_soon_threadsafe(entered.set)
            release.wait(2)
            return self.data, self.metadata
        try:
            with patch('wx_clawbot.images.download_image', side_effect=slow):
                await self.controller.prepare(await self.image())
                await asyncio.wait_for(entered.wait(), 1)
                task = (await self.state.tasks())[0]
                await asyncio.wait_for(self.command('/stop ' + task['id']), .5)
                self.assertEqual((await self.state.tasks(task_id=task['id']))['state'], 'cancelled')
                attachment = (await self.state.attachments(task_id=task['id']))[0]
                self.assertEqual((attachment['state'], attachment['media']), ('failed', '{}'))
                release.set()
                await self.engine.close()
            await self.engine.drain_admission()
            self.queue.add.assert_not_awaited()
            self.assertEqual(self.engine.images.reserved, 0)
        finally:
            release.set()

    async def test_failed_image_never_degrades_to_caption_only_task(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', side_effect=ImageError('invalid_image')):
            await self.controller.prepare(await self.image('must not execute alone'))
            await self.prepare_done()
        await self.engine.drain_admission()
        self.queue.add.assert_not_awaited()
        self.assertEqual((await self.state.tasks())[0]['state'], 'failed')

    async def test_model_image_rejection_preserves_error_without_text_only_retry(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image('describe this'))
            await self.prepare_done()
        await self.engine.drain_admission()
        task = (await self.state.tasks())[0]
        await self.engine.complete('thread-two', {'id': 'image-rejected-turn', 'status': 'failed',
            'error': {'message': 'Model does not support image input'},
            'items': [{'type': 'userMessage', 'clientId': task['client_id']}]})
        reply = await self.state.claim_reply()
        self.assertIn('Model does not support image input', reply['text'])
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'], 'failed')
        self.queue.add.assert_awaited_once()
        self.assertTrue(any(i['type'] == 'localImage' for i in self.queue.add.await_args.kwargs['input_items']))

    async def test_ready_file_change_refuses_before_native_submit(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image())
            await self.prepare_done()
        task = (await self.state.tasks())[0]
        row = (await self.state.attachments(task_id=task['id']))[0]
        (self.state.path.parent / 'attachments' / row['filename']).write_bytes(b'changed')
        await self.engine.drain_admission()
        self.queue.add.assert_not_awaited()
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'], 'failed')

    async def test_prepared_image_reports_repository_admission_wait_once_without_dispatch(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image())
            await self.prepare_done()
        task = (await self.state.tasks())[0]
        with patch('wx_clawbot.execution.conflict', new=AsyncMock(return_value='同仓库旧任务尚待核对')):
            await self.engine.drain_admission()
            await self.engine.drain_admission()
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'], 'received')
        self.queue.add.assert_not_awaited()
        rows = await self.state._call(lambda: list(self.state.db.execute(
            'SELECT text FROM outbox WHERE id=?', (task['id'] + '-waiting',))))
        self.assertEqual(len(rows), 1)
        self.assertIn('同仓库旧任务尚待核对', rows[0][0])
        self.assertIn('尚未进入原生队列', rows[0][0])

    async def test_received_image_restart_keeps_frozen_target_and_prepared_file_without_redownload(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image())
            await self.prepare_done()
        task = (await self.state.tasks())[0]
        await self.engine.close()
        await self.state.close()
        from wx_clawbot.runtime_state import RuntimeState
        self.state = await RuntimeState.open(self.state.path, self.state.credentials)
        self.addAsyncCleanup(self.state.close)
        from wx_clawbot.images import ImagePreparer
        preparer = ImagePreparer(self.state)
        self.addAsyncCleanup(preparer.close)
        recovered = await self.state.tasks(task_id=task['id'])
        self.assertEqual(recovered['state'], 'received')
        self.assertEqual(recovered['target'], task['target'])
        with patch('wx_clawbot.images.download_image') as download:
            await preparer.prepare(recovered)
            content = await preparer.inputs(recovered)
        download.assert_not_called()
        self.assertEqual(content[1]['type'], 'localImage')

    async def test_unknown_submission_restart_cannot_become_received(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image())
            await self.prepare_done()
        task = (await self.state.tasks())[0]
        await self.state.task_update(task['id'], 'dispatching')
        await self.engine.close()
        await self.state.close()
        from wx_clawbot.runtime_state import RuntimeState
        self.state = await RuntimeState.open(self.state.path, self.state.credentials)
        self.addAsyncCleanup(self.state.close)
        self.assertEqual((await self.state.tasks(task_id=task['id']))['state'], 'unknown')

    async def test_capacity_refusal_never_downloads_and_keeps_controls(self):
        await self.select()
        with patch('wx_clawbot.images.MAX_DISK_BYTES', 1), patch('wx_clawbot.images.download_image') as download:
            await self.controller.prepare(await self.image())
            await self.prepare_done()
        download.assert_not_called()
        self.assertEqual((await self.state.tasks())[0]['state'], 'failed')
        self.assertEqual(self.engine.images.reserved, 0)
        await asyncio.wait_for(self.command('/status'), .5)

    async def test_cancel_during_final_image_verification_prevents_queue_add(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image())
            await self.prepare_done()
        original = self.engine.images.inputs
        async def cancel_then_verify(task):
            await self.command('/stop ' + task['id'])
            return await original(task)
        with patch.object(self.engine.images, 'inputs', side_effect=cancel_then_verify):
            await self.engine.drain_admission()
        self.queue.add.assert_not_awaited()
        self.assertEqual((await self.state.tasks())[0]['state'], 'cancelled')

    async def test_unknown_image_queue_receipt_never_replays(self):
        await self.select()
        with patch('wx_clawbot.images.download_image', return_value=(self.data, self.metadata)):
            await self.controller.prepare(await self.image())
            await self.prepare_done()
        self.queue.add.side_effect = OutcomeUnknown('synthetic lost acknowledgement')
        with self.assertRaises(OutcomeUnknown):
            await self.engine.drain_admission()
        self.assertEqual((await self.state.tasks())[0]['state'], 'unknown')
        await self.engine.drain_admission()
        self.queue.add.assert_awaited_once()

    async def test_cancelled_worker_does_not_free_a_third_download_lane_early(self):
        await self.select()
        lock = threading.Lock()
        releases = [threading.Event() for _ in range(3)]
        entered = [asyncio.Event() for _ in range(3)]
        counts = {'started': 0, 'active': 0, 'peak': 0}
        loop = asyncio.get_running_loop()
        def slow(_):
            with lock:
                index = counts['started']
                counts['started'] += 1
                counts['active'] += 1
                counts['peak'] = max(counts['peak'], counts['active'])
            loop.call_soon_threadsafe(entered[index].set)
            try:
                if not releases[index].wait(3):
                    raise ImageError('download_timeout')
                return self.data, self.metadata
            finally:
                with lock:
                    counts['active'] -= 1
        try:
            with patch('wx_clawbot.images.download_image', side_effect=slow):
                first = await self.image()
                await self.controller.prepare(first)
                for _ in range(2):
                    await self.controller.prepare(await self.image())
                await asyncio.wait_for(entered[1].wait(), 1)
                task = next(t for t in await self.state.tasks() if t['source_message_id'] == first.message_id)
                await self.command('/stop ' + task['id'])
                await asyncio.sleep(.02)
                self.assertFalse(entered[2].is_set())
                self.assertEqual(counts['started'], 2)
                releases[0].set()
                await asyncio.wait_for(entered[2].wait(), 1)
                for release in releases:
                    release.set()
                await self.prepare_done()
                self.assertLessEqual(counts['peak'], 2)
                self.assertEqual(self.engine.images.reserved, 0)
        finally:
            for release in releases:
                release.set()
