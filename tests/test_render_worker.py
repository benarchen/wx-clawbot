import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.output import _render_process, render_segments, render_in_worker


class RenderWorkerTests(unittest.IsolatedAsyncioTestCase):
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
