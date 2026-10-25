"""Experimental daemon queue operations. The TUI's local queue is not this queue."""

import asyncio
from pathlib import Path

from .codex import CodexConnection
from .base import thread_is_loaded


class QueueFull(ValueError):
    """Admission refused before thread/queue/add was sent."""


class NativeQueue:
    def __init__(self, connection: CodexConnection, thread_id: str, project: Path):
        self.connection, self.thread_id = connection, thread_id
        self.project = project.resolve(strict=True)
        self.add_lock = asyncio.Lock()

    async def _validate(self) -> dict:
        thread = await self.connection.inspect(self.thread_id)
        if Path(thread["cwd"]).resolve() != self.project or not await thread_is_loaded(self.connection, thread):
            raise ValueError("Queue target is not the loaded native project thread")
        return thread

    async def list(self) -> list[dict]:
        await self._validate()
        result = await self.connection.rpc.request("thread/queue/list", {
            "threadId": self.thread_id, "limit": 100,
        })
        items = result.get("data")
        if not isinstance(items, list) or result.get("nextCursor"):
            raise ValueError("Native queue exceeds supported snapshot bound")
        ids = []
        for item in items:
            if not isinstance(item, dict) or any(
                not isinstance(item.get(key), str) or not item[key]
                for key in ("id", "clientUserMessageId")
            ):
                raise ValueError("Invalid native queue identity")
            ids.append(item["id"])
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate native queue identity")
        return items

    async def add(self, text: str, client_id: str) -> dict:
        if (not isinstance(text, str) or not text.strip() or len(text) > 32000
                or not isinstance(client_id, str) or not client_id or len(client_id) > 128):
            raise ValueError("Bounded text and stable submission identity required")
        async with self.add_lock:
            items = await self.list()
            if any(item["clientUserMessageId"] == client_id for item in items):
                raise ValueError("Submission already queued; reconcile instead of resubmitting")
            if len(items) >= 10:
                raise QueueFull("Native queue is full for bridge admission")
            result = await self.connection.rpc.request("thread/queue/add", {
                "threadId": self.thread_id, "clientUserMessageId": client_id,
                "input": [{"type": "text", "text": text}],
            })
            item = result.get("queuedSubmission", {})
            if item.get("clientUserMessageId") != client_id or not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("Queue receipt identity missing; reconcile before retry")
            return item

    async def delete(self, queue_id: str) -> bool:
        if not isinstance(queue_id, str) or not queue_id:
            raise ValueError("Exact queued submission identity required")
        if not any(item["id"] == queue_id for item in await self.list()):
            return False  # It may already be executing; this is not a cancellation receipt.
        result = await self.connection.rpc.request("thread/queue/delete", {
            "threadId": self.thread_id, "queuedSubmissionId": queue_id,
        })
        if type(result.get("deleted")) is not bool:
            raise ValueError("Native deletion receipt missing")
        return result["deleted"]

    async def request_interrupt(self, turn_id: str) -> dict:
        await self._validate()
        page = await self.connection.rpc.request("thread/turns/list", {
            "threadId": self.thread_id, "limit": 1, "itemsView": "notLoaded",
            "sortDirection": "desc",
        })
        turns = page.get("data", [])
        if not turns or turns[0].get("id") != turn_id or turns[0].get("status") != "inProgress":
            raise ValueError("Target turn is not currently running")
        # This receipt only acknowledges the request. turn/completed must confirm interrupted.
        return await self.connection.rpc.request("turn/interrupt", {
            "threadId": self.thread_id, "turnId": turn_id,
        })
