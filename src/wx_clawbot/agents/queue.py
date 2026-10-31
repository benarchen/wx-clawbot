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
        items, ids, cursors, cursor = [], set(), set(), None
        for _ in range(100):
            params = {"threadId": self.thread_id, "limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            result = await self.connection.rpc.request("thread/queue/list", params)
            rows = result.get("data")
            if not isinstance(rows, list) or len(items) + len(rows) > 100:
                raise ValueError("Native queue exceeds supported snapshot bound")
            for row in rows:
                if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key]
                                                   for key in ("id", "clientUserMessageId")):
                    raise ValueError("Invalid native queue identity")
                if row["id"] in ids:
                    raise ValueError("Duplicate native queue identity")
                ids.add(row["id"])
                # Native input may contain large inline images; retain identities only.
                items.append({"id": row["id"], "clientUserMessageId": row["clientUserMessageId"]})
            cursor = result.get("nextCursor")
            if cursor is None:
                return items
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("Native queue cursor is invalid or repeated")
            cursors.add(cursor)
        raise ValueError("Native queue exceeds supported page bound")

    async def add(self, text: str, client_id: str, *, input_items=None) -> dict:
        if (not isinstance(text, str) or not text.strip() or len(text) > 32000
                or not isinstance(client_id, str) or not client_id or len(client_id) > 128):
            raise ValueError("Bounded text and stable submission identity required")
        content = [{"type": "text", "text": text}] if input_items is None else input_items
        if not isinstance(content, list) or not 1 <= len(content) <= 21:
            raise ValueError("Bounded native image/text input required")
        images = 0
        for item in content:
            if not isinstance(item, dict):
                raise ValueError("Invalid native input item")
            if item.get("type") == "text":
                if set(item) != {"type", "text"} or not isinstance(item["text"], str) or len(item["text"]) > 32000:
                    raise ValueError("Invalid bounded text input")
            elif item.get("type") == "localImage":
                images += 1
                if not isinstance(item.get("path"), str):
                    raise ValueError("A local image path string is required")
                path = Path(item.get("path", ""))
                if set(item) != {"type", "path"} or not path.is_absolute() or path.is_symlink() or not path.is_file():
                    raise ValueError("Verified local image input required")
            else:
                raise ValueError("Unsupported native input type")
        if images > 1:
            raise ValueError("Only one image per native task is supported")
        if sum(len(item["text"]) for item in content if item["type"] == "text") > 32000:
            raise ValueError("Combined text input exceeds the bound")
        if not images and not any(item["text"].strip() for item in content):
            raise ValueError("A nonempty native input is required")
        async with self.add_lock:
            items = await self.list()
            if any(item["clientUserMessageId"] == client_id for item in items):
                raise ValueError("Submission already queued; reconcile instead of resubmitting")
            if len(items) >= 10:
                raise QueueFull("Native queue is full for bridge admission")
            result = await self.connection.rpc.request("thread/queue/add", {
                "threadId": self.thread_id, "clientUserMessageId": client_id,
                "input": content,
            })
            item = result.get("queuedSubmission", {})
            if item.get("clientUserMessageId") != client_id or not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("Queue receipt identity missing; reconcile before retry")
            return {"id": item["id"], "clientUserMessageId": item["clientUserMessageId"]}

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
