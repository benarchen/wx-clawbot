"""Performance regressions assert ordering and bounded work, not just elapsed time."""
import asyncio
import json
import unittest
import threading
from unittest.mock import AsyncMock
from types import SimpleNamespace

import test_controller as fixtures
from wx_clawbot.agents.rpc import JsonRpc
from wx_clawbot.interactions import QUESTION
from wx_clawbot.delivery import Sender


class Peer:
    def __init__(self):
        self.messages = asyncio.Queue()

    async def recv(self):
        return await self.messages.get()

    async def send(self, raw):
        pass

    async def close(self):
        pass

    async def emit(self, method, params, identity=None):
        value = {'method': method, 'params': params}
        if identity is not None:
            value['id'] = identity
        await self.messages.put(json.dumps(value))


class PerformanceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ControllerTests.asyncSetUp
    incoming = fixtures.ControllerTests.incoming
    command = fixtures.ControllerTests.command
    select = fixtures.ControllerTests.select

    async def test_result_wait_does_not_delay_other_thread_question(self):
        await self.select()
        await self.command('/attach 1')
        await self.command('synthetic result')
        task = (await self.state.tasks())[0]
        peer = Peer()
        rpc = JsonRpc(peer)
        self.agent.rpc = rpc
        entered, release, question_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        finish = self.state.task_finish
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await finish(*args, **kwargs)
        self.state.task_finish = delayed
        self.engine.read_turn = AsyncMock(return_value={'id': 'turn-result', 'status': 'completed',
            'items': [{'type': 'userMessage', 'clientId': task['client_id']}, {'type': 'agentMessage', 'text': 'result'}]})
        event = self.engine.event
        async def traced(value):
            await event(value)
            if value['method'] == QUESTION:
                question_done.set()
        self.engine.event = traced
        runner = asyncio.create_task(self.engine.run())
        try:
            await peer.emit('turn/completed', {'threadId': 'thread-two', 'turn': {'id': 'turn-result'}})
            await asyncio.wait_for(entered.wait(), 1)
            await peer.emit(QUESTION, {'threadId': 'thread-one', 'turnId': 'turn-question', 'itemId': 'question',
                'questions': [{'id': 'choice', 'question': 'synthetic choice', 'options': [{'label': 'A'}, {'label': 'B'}]}]}, 'question-1')
            await asyncio.wait_for(question_done.wait(), .5)
            self.assertFalse(release.is_set())
            self.assertTrue(await self.state.interaction_rows())
        finally:
            release.set()
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
            await self.engine.close()
            await rpc.close()

    async def test_unused_deltas_cannot_fill_the_native_event_queue(self):
        peer = Peer()
        rpc = JsonRpc(peer)
        try:
            for i in range(10000):
                await peer.emit('item/agentMessage/delta', {'threadId': 'synthetic', 'delta': 'x'})
                if i % 100 == 0:
                    await asyncio.sleep(0)
            await asyncio.sleep(.01)
            self.assertIsNone(rpc.failure)
            self.assertEqual(rpc.events.qsize(), 0)
        finally:
            await rpc.close()

    async def test_request_with_delta_method_and_unknown_notification_are_retained(self):
        peer = Peer()
        rpc = JsonRpc(peer)
        try:
            await peer.emit('item/agentMessage/delta', {'threadId': 'a'}, 'real-request')
            await peer.emit('unknown/notification', {'threadId': 'a'})
            self.assertEqual((await rpc.next_event())['id'], 'real-request')
            self.assertEqual((await rpc.next_event())['method'], 'unknown/notification')
            self.assertIsNone(rpc.failure)
        finally:
            await rpc.close()

    async def test_sender_waits_without_read_wakeups_and_commits_wake_it(self):
        await self.incoming('/help')
        claims = []
        claim = self.state.claim_reply
        async def counted():
            claims.append(1)
            return await claim()
        self.state.claim_reply = counted
        sent = asyncio.Event()
        async def send(*args, **kwargs):
            sent.set()
            return {'ret': 0}
        runner = asyncio.create_task(Sender(self.state, SimpleNamespace(send_text=send)).run())
        try:
            await asyncio.sleep(.03)
            await self.state.delivery_counts()
            await self.state.tasks()
            await asyncio.sleep(.03)
            self.assertEqual(len(claims), 1)
            await self.state.queue_reply('new-result', 'new result')
            await asyncio.wait_for(sent.wait(), .5)
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    async def test_sender_cannot_miss_commit_between_empty_query_and_wait(self):
        await self.incoming('/help')
        claim = self.state.claim_reply
        calls = 0
        async def race():
            nonlocal calls
            calls += 1
            value = await claim()
            if calls == 1:
                self.assertIsNone(value)
                await self.state.queue_reply('race-result', 'raced result')
            return value
        self.state.claim_reply = race
        sent = asyncio.Event()
        async def send(*args, **kwargs):
            sent.set()
            return {'ret': 0}
        runner = asyncio.create_task(Sender(self.state, SimpleNamespace(send_text=send)).run())
        try:
            await asyncio.wait_for(sent.wait(), .5)
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    async def test_slow_unsubscribe_does_not_block_another_thread_event_retention(self):
        await self.select()
        await self.command('/attach 1')
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            entered.set()
            await release.wait()
        self.agent.unsubscribe.side_effect = slow
        a,b = self.sessions
        job = asyncio.create_task(self.controller.subscriptions.release(b.target,'route'))
        try:
            await asyncio.wait_for(entered.wait(), .5)
            result = await asyncio.wait_for(self.controller.subscriptions.retain_event(
                a.target,'thread-one','interaction-r-synthetic'),.5)
            self.assertEqual(result.target,a.target)
            self.assertFalse(job.done())
        finally:
            release.set()
            await job

    async def test_cancelled_caller_still_wakes_sender_after_actual_commit(self):
        entered,release=threading.Event(),threading.Event()
        def commit():
            entered.set()
            if not release.wait(2):raise AssertionError('worker release timeout')
            return self.state._queue_reply('late-commit','synthetic',0)
        self.state.reply_changed.clear()
        job=asyncio.create_task(self.state._call(commit,wake=True))
        await asyncio.wait_for(asyncio.to_thread(entered.wait),.5)
        job.cancel()
        with self.assertRaises(asyncio.CancelledError):await job
        release.set()
        await asyncio.wait_for(self.state.reply_changed.wait(),.5)
        self.assertEqual((await self.state.delivery_counts()).get('pending'),1)

    async def test_cursor_only_commit_and_failed_transaction_do_not_signal_ready_replies(self):
        self.state.reply_changed.clear()
        await self.state.accept_batch({'ret':0,'msgs':[],'get_updates_buf':'synthetic-next'},phase='runtime')
        self.assertFalse(self.state.reply_changed.is_set())
        def failed():
            self.state.db.execute('BEGIN IMMEDIATE')
            try:
                self.state._queue_reply('rolled-back','synthetic',0)
                raise ValueError('synthetic rollback')
            finally:self.state.db.execute('ROLLBACK')
        with self.assertRaises(ValueError):await self.state._call(failed,wake=True)
        self.assertFalse(self.state.reply_changed.is_set())
        self.assertEqual(await self.state.delivery_counts(),{})

    async def test_new_context_wakes_already_pending_reply_without_duplicate_send(self):
        await self.state.queue_reply('waiting-for-context','synthetic result')
        sent=asyncio.Event(); calls=[]
        async def send(*args,**kwargs):
            calls.append(kwargs['client_id']);sent.set();return {'ret':0}
        runner=asyncio.create_task(Sender(self.state,SimpleNamespace(send_text=send)).run())
        try:
            await asyncio.sleep(.03)
            self.assertFalse(sent.is_set())
            await self.incoming('/status')
            await asyncio.wait_for(sent.wait(),.5)
            await asyncio.sleep(.02)
            self.assertEqual(len(calls),1)
        finally:
            runner.cancel();await asyncio.gather(runner,return_exceptions=True)
