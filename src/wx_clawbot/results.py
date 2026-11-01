"""Bounded completion work; native control events never await result rendering."""

import asyncio
from collections import deque

from .agents.rpc import ConnectionLost


class ResultWork:
    def __init__(self, complete, *, concurrency=2, limit=128):
        self.complete = complete
        self.concurrency, self.limit = concurrency, limit
        self.pending = deque()
        self.keys = set()
        self.jobs = {}
        self.changed = asyncio.Event()
        self.closed = False

    def enqueue(self, thread_id, turn_id):
        if any(not isinstance(value, str) or not value or len(value) > 128 for value in (thread_id, turn_id)):
            raise ConnectionLost("Bounded native completion identities required")
        key = (thread_id, turn_id)
        if self.closed:
            raise ConnectionLost("Completion generation is closed")
        if key in self.keys:
            return
        if len(self.keys) >= self.limit:
            raise ConnectionLost("Completion work budget exceeded; reconcile native outcomes")
        self.keys.add(key)
        self.pending.append(key)
        self.changed.set()

    async def run(self):
        try:
            while True:
                self.changed.clear()
                for key, job in tuple(self.jobs.items()):
                    if job.done():
                        job.result()  # Storage/protocol failures must reach the supervisor.
                        del self.jobs[key]
                        self.keys.remove(key)
                busy = {key[0] for key in self.jobs}
                # Skip a busy thread without blocking an independent thread.
                for _ in range(len(self.pending)):
                    key = self.pending.popleft()
                    if key[0] in busy or len(self.jobs) >= self.concurrency:
                        self.pending.append(key)
                        continue
                    job = asyncio.create_task(self.complete(*key))
                    self.jobs[key] = job
                    busy.add(key[0])
                    job.add_done_callback(lambda _: self.changed.set())
                await self.changed.wait()
        finally:
            self.closed = True
            jobs = tuple(self.jobs.values())
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            self.jobs.clear()
            self.pending.clear()
            self.keys.clear()
