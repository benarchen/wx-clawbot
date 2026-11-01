import asyncio
import sqlite3
import unittest
import threading

from wx_clawbot.agents.rpc import ConnectionLost
from wx_clawbot.results import ResultWork
from wx_clawbot.output import render_in_worker


class ResultWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_thread_order_cross_thread_progress_and_inflight_deduplication(self):
        first, second, other = asyncio.Event(), asyncio.Event(), asyncio.Event()
        release, finish = asyncio.Event(), asyncio.Event()
        calls = []
        async def complete(thread, turn):
            calls.append((thread, turn))
            if turn == 'first':
                first.set()
                await release.wait()
            elif turn == 'second':
                second.set()
            else:
                other.set()
            await finish.wait()
        work = ResultWork(complete)
        for key in [('a', 'first'), ('a', 'second'), ('b', 'other'), ('a', 'first')]:
            work.enqueue(*key)
        runner = asyncio.create_task(work.run())
        try:
            await asyncio.wait_for(first.wait(), .5)
            await asyncio.wait_for(other.wait(), .5)
            self.assertFalse(second.is_set())
            self.assertEqual(len(work.jobs), 2)
            release.set()
            finish.set()
            await asyncio.wait_for(second.wait(), .5)
            self.assertEqual(calls, [('a', 'first'), ('b', 'other'), ('a', 'second')])
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
        self.assertTrue(work.closed)
        self.assertEqual((len(work.jobs), len(work.pending), len(work.keys)), (0, 0, 0))

    async def test_overload_fails_with_no_extra_work(self):
        work = ResultWork(lambda *_: None, limit=3)
        for i in range(3):
            work.enqueue('thread', str(i))
        with self.assertRaises(ConnectionLost):
            work.enqueue('thread', 'fourth')
        self.assertEqual(len(work.keys), 3)

    async def test_completion_identity_memory_is_bounded_before_enqueue(self):
        work=ResultWork(lambda *_:None)
        for thread,turn in ((None,'one'),('','one'),('thread',''),('thread','x'*129)):
            with self.subTest(thread=thread,turn_size=len(turn)),self.assertRaises(ConnectionLost):
                work.enqueue(thread,turn)
        self.assertEqual(len(work.keys),0)

    async def test_worker_failure_reaches_supervisor_and_cancels_others(self):
        stopped = asyncio.Event()
        async def complete(thread, turn):
            if thread == 'bad':
                await asyncio.sleep(0)
                raise sqlite3.OperationalError('synthetic storage failure')
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        work = ResultWork(complete)
        work.enqueue('bad', 'one')
        work.enqueue('other', 'two')
        with self.assertRaises(sqlite3.OperationalError):
            await asyncio.wait_for(work.run(), .5)
        self.assertTrue(stopped.is_set())
        self.assertEqual(len(work.jobs), 0)

    async def test_queued_duplicate_and_closed_generation_never_run(self):
        work = ResultWork(lambda *_: None, limit=1)
        work.enqueue('a', 'one')
        work.enqueue('a', 'one')
        self.assertEqual(len(work.pending), 1)
        work.closed = True
        with self.assertRaises(ConnectionLost):
            work.enqueue('a', 'one')

    async def test_cancelled_render_retains_its_lane_until_the_cpu_worker_exits(self):
        entered,release=threading.Event(),threading.Event()
        def renderer(text):
            entered.set()
            if not release.wait(2):raise AssertionError('worker release timeout')
            return text
        job=asyncio.create_task(render_in_worker('synthetic',renderer=renderer))
        try:
            await asyncio.wait_for(asyncio.to_thread(entered.wait),.5)
            job.cancel()
            await asyncio.sleep(.01)
            self.assertFalse(job.done())
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):await job
