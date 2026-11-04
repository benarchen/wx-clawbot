import asyncio
import json
import subprocess
import time
import threading
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.output import _render_process, _render_process_io, render_segments, render_in_worker


class RenderWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_with_full_stdout_pipe_does_not_wait_forever_for_exit(self):
        original=asyncio.create_subprocess_exec
        child=None
        async def spawn(*args, **kwargs):
            nonlocal child
            child=await original(sys.executable,'-I','-c',
                'import sys,time;sys.stdout.buffer.write(b"x"*3000000);sys.stdout.buffer.flush();time.sleep(10)',
                **kwargs)
            async with asyncio.timeout(2):
                while not child.stdout._paused:
                    await asyncio.sleep(.001)
            asyncio.current_task().cancel()
            return child
        try:
            with patch('wx_clawbot.output.asyncio.create_subprocess_exec',side_effect=spawn):
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(_render_process_io('x'*70000),.5)
        finally:
            if child is not None:
                if child.returncode is None:child.kill()
                while await child.stdout.read(65536):pass
                await child.wait()

    async def test_repeated_cancel_cannot_release_lane_before_owned_spawn_exits(self):
        entered,release=threading.Event(),threading.Event()
        async def slow_spawn(text):
            entered.set()
            await asyncio.to_thread(release.wait)
            return render_segments(text),1
        slots=asyncio.Semaphore(2)
        with patch('wx_clawbot.output._render_process_io',side_effect=slow_spawn):
            job=asyncio.create_task(render_in_worker('x'*40000,slots=slots))
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait),1)
                job.cancel();await asyncio.sleep(.01);job.cancel();await asyncio.sleep(.01)
                self.assertFalse(job.done())
                self.assertEqual(slots._value,1)
            finally:
                release.set()
                await asyncio.gather(job,return_exceptions=True)
        self.assertEqual(slots._value,2)

    async def test_slow_process_creation_does_not_block_control_loop(self):
        original = subprocess.Popen
        delays = []
        def delayed(*args, **kwargs):
            time.sleep(.15)
            return original(*args, **kwargs)
        async def heartbeat():
            for _ in range(30):
                start = time.monotonic()
                await asyncio.sleep(.01)
                delays.append(time.monotonic() - start)
        with patch('subprocess.Popen', side_effect=delayed):
            ticking = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            await asyncio.gather(render_in_worker('x' * 40000, slots=asyncio.Semaphore(2)), ticking)
        self.assertLess(max(delays), .1)

    async def test_actual_cancel_does_not_leave_pipe_protocol_callback_errors(self):
        loop = asyncio.get_running_loop()
        errors = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: errors.append(context))
        try:
            slots = asyncio.Semaphore(2)
            jobs = [asyncio.create_task(render_in_worker('x' * 500000, slots=slots)) for _ in range(8)]
            await asyncio.sleep(.04)
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            await asyncio.sleep(.05)
            self.assertEqual(slots._value, 2)
            self.assertFalse(errors)
        finally:
            loop.set_exception_handler(previous)

    async def test_actual_large_process_preserves_prefix_and_every_source_byte(self):
        prefix=lambda i,n:f'〔{i}/{n}〕synthetic\n\n'
        for raw in ('中文 English 内容。\n\n'*5000,
                    '```text\n'+('  A\\B  \r\n'*7000)+'```\r\n',
                    'literal\rdata'*6000):
            with self.subTest(kind=raw[:10]):
                expected=render_segments(raw,prefix=prefix)
                actual=await render_in_worker(raw,prefix=prefix,slots=asyncio.Semaphore(2))
                self.assertEqual(actual,expected)

    def process(self, raw=None):
        class Reader:
            def __init__(self):self.raw=raw
            async def read(self,_):
                if self.raw is None:await asyncio.Event().wait()
                value,self.raw=self.raw,b''
                return value
        writer=SimpleNamespace(write=lambda _:None,drain=AsyncMock(),close=lambda:None,wait_closed=AsyncMock())
        process=SimpleNamespace(stdin=writer,stdout=Reader(),returncode=None,killed=False)
        def kill():process.killed=True;process.returncode=-9
        async def wait():
            if process.returncode is None:process.returncode=0
            return process.returncode
        process.kill=kill;process.wait=wait
        return process

    async def test_cancelled_process_is_killed_reaped_and_releases_its_lane(self):
        process=self.process();slots=asyncio.Semaphore(2)
        with patch('wx_clawbot.output.asyncio.create_subprocess_exec',new=AsyncMock(return_value=process)):
            job=asyncio.create_task(render_in_worker('x'*70000,slots=slots))
            await asyncio.sleep(.01)
            self.assertEqual(slots._value,1)
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):await job
        self.assertTrue(process.killed)
        self.assertIsNotNone(process.returncode)
        self.assertEqual(slots._value,2)

    async def test_timed_out_process_is_killed_reaped_and_releases_its_lane(self):
        process=self.process();slots=asyncio.Semaphore(2)
        timeout=asyncio.timeout
        with patch('wx_clawbot.output.asyncio.create_subprocess_exec',new=AsyncMock(return_value=process)), \
                patch('wx_clawbot.output.asyncio.timeout',side_effect=lambda _:timeout(.03)):
            with self.assertRaises(TimeoutError):
                await render_in_worker('x'*70000,slots=slots)
        self.assertTrue(process.killed)
        self.assertIsNotNone(process.returncode)
        self.assertEqual(slots._value,2)

    async def test_invalid_or_oversized_child_output_is_never_frozen(self):
        for raw in (json.dumps({'parts':[],'peak_rss_bytes':1}).encode(),
                    json.dumps({'parts':[{'source':'x','before':0,'after':''}],'peak_rss_bytes':1}).encode(),
                    b'x'*(8*1024*1024+1)):
            process=self.process(raw)
            with self.subTest(size=len(raw)), \
                    patch('wx_clawbot.output.asyncio.create_subprocess_exec',new=AsyncMock(return_value=process)), \
                    self.assertRaises(ValueError):
                await _render_process('x'*70000)

    async def test_process_slots_are_global_to_the_state_not_released_by_waiting_cancel(self):
        slots=asyncio.Semaphore(2);entered=0;maximum=0;release=asyncio.Event()
        async def child(text):
            nonlocal entered,maximum
            entered+=1;maximum=max(maximum,entered)
            try:await release.wait()
            finally:entered-=1
            return render_segments(text),1
        with patch('wx_clawbot.output._render_process',side_effect=child):
            jobs=[asyncio.create_task(render_in_worker('x'*70000,slots=slots)) for _ in range(4)]
            try:
                await asyncio.sleep(.01)
                self.assertEqual(entered,2)
                jobs[-1].cancel()
                release.set()
                await asyncio.gather(*jobs,return_exceptions=True)
            finally:
                for job in jobs:job.cancel()
                await asyncio.gather(*jobs,return_exceptions=True)
        self.assertEqual(maximum,2)
        self.assertEqual(slots._value,2)

    async def test_medium_results_do_not_occupy_short_control_receipt_lanes(self):
        slots = asyncio.Semaphore(2)
        entered, release = asyncio.Event(), asyncio.Event()
        count = 0
        async def child(text):
            nonlocal count
            count += 1
            if count == 2:
                entered.set()
            await release.wait()
            return render_segments(text), 1
        with patch('wx_clawbot.output._render_process', side_effect=child):
            jobs = [asyncio.create_task(render_in_worker('x' * 40000, slots=slots)) for _ in range(2)]
            try:
                await asyncio.wait_for(entered.wait(), .5)
                self.assertEqual(slots._value, 0)
                receipt = await asyncio.wait_for(render_in_worker('small control receipt', slots=slots), .2)
                self.assertEqual(receipt, render_segments('small control receipt'))
            finally:
                release.set()
                await asyncio.gather(*jobs)

    async def test_medium_process_preserves_literal_source(self):
        raw = '```text\n' + '  A\\B  \r\n' * 4000 + '```\r\n'
        self.assertGreaterEqual(len(raw), 32768)
        self.assertLess(len(raw), 65536)
        self.assertEqual(await render_in_worker(raw, slots=asyncio.Semaphore(2)), render_segments(raw))
