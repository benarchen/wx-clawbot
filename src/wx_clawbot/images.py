"""Prepare private attachments without occupying native admission or control paths."""

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

from .channels.http import ProtocolError
from .channels.media import ImageError, MAX_BYTES, download_image
from .image_files import verify_image_file, write_image_file


MAX_DISK_BYTES = 256 * 1024 * 1024


def disk_usage(root):
    directory = root / "attachments"
    if directory.is_symlink():
        raise ImageError("file_unavailable")
    if not directory.exists():
        return 0
    total = 0
    for index, path in enumerate(directory.iterdir()):
        if index >= 1024 or path.is_symlink() or not path.is_file():
            raise ImageError("capacity")
        total += path.stat().st_size
    return total


class ImagePreparer:
    def __init__(self, state):
        self.state = state
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wx-image")
        self.slots = asyncio.Semaphore(2)
        self.capacity = asyncio.Lock()
        self.reserved = 0
        self.inflight = set()
        self.closed = False

    def worker(self, function, *args):
        future = asyncio.get_running_loop().run_in_executor(self.pool, function, *args)
        self.inflight.add(future)
        def done(completed):
            self.inflight.discard(completed)
            if not completed.cancelled():
                completed.exception()
        future.add_done_callback(done)
        return future

    async def prepare(self, task):
        rows = await self.state.attachments(task_id=task["id"])
        if len(rows) != 1:
            raise ImageError("invalid_image")
        row = rows[0]
        if row["state"] == "ready":
            return
        if row["state"] not in {"pending", "preparing"}:
            raise ImageError("file_unavailable")
        await self.slots.acquire()
        reserved, future = False, None
        def release(_=None):
            if reserved:
                self.reserved -= MAX_BYTES
            self.slots.release()
        try:
            if self.closed:
                raise ImageError("file_unavailable")
            async with self.capacity:
                usage = await asyncio.to_thread(disk_usage, self.state.path.parent)
                if usage + self.reserved + MAX_BYTES > MAX_DISK_BYTES:
                    raise ImageError("capacity")
                self.reserved += MAX_BYTES
                reserved = True
            current = await self.state.tasks(task_id=task["id"])
            if current["state"] != "received":
                return
            if row["filename"]:
                try:
                    future = self.worker(verify_image_file, self.state.path.parent, row["filename"], row["sha256"], row["byte_size"])
                    await asyncio.shield(future)
                except FileNotFoundError:
                    pass
                else:
                    await self.state.finish_attachment(row["id"])
                    return
            future = self.worker(download_image, json.loads(row["media"]))
            data, metadata = await asyncio.shield(future)
            current = await self.state.tasks(task_id=task["id"])
            if current["state"] != "received":
                return  # Late worker completion cannot authorize a cancelled task.
            filename = row["filename"] or uuid.uuid4().hex + (".png" if metadata["format"] == "PNG" else ".jpg")
            await self.state.prepare_attachment_file(row["id"], filename=filename, **metadata)
            future = self.worker(write_image_file, self.state.path.parent, filename, data, metadata["sha256"])
            await asyncio.shield(future)
            await self.state.finish_attachment(row["id"])
        except ImageError as exc:
            code = "capacity" if exc.code == "capacity" else "download_failed" if exc.code.startswith("download") else "invalid_image"
            await self.state.finish_attachment(row["id"], error_code=code)
            raise
        except (OSError, ProtocolError):
            await self.state.finish_attachment(row["id"], error_code="file_unavailable")
            raise ImageError("file_unavailable") from None
        finally:
            # Cancelled callers retain their lane and disk reservation until the
            # blocking worker actually exits, preventing hidden excess workers.
            if future is not None and not future.done():
                future.add_done_callback(release)
            else:
                release()

    async def inputs(self, task):
        rows = {r["id"]: r for r in await self.state.attachments(task_id=task["id"])}
        content = []
        try:
            for item in task["input_items"]:
                if item["type"] == "text":
                    content.append({"type": "text", "text": item["text"]})
                else:
                    row = rows[item["attachment_id"]]
                    if row["state"] != "ready":
                        raise ImageError("file_unavailable")
                    path = await asyncio.to_thread(verify_image_file, self.state.path.parent, row["filename"], row["sha256"], row["byte_size"])
                    content.append({"type": "localImage", "path": str(path)})
        except (KeyError, OSError, ProtocolError):
            raise ImageError("file_unavailable") from None
        if not any(p["type"] == "text" and p["text"].strip() for p in content):
            content.insert(0, {"type": "text", "text": task["input"]})
        return content

    async def close(self):
        self.closed = True
        if self.inflight:
            await asyncio.gather(*(asyncio.shield(f) for f in tuple(self.inflight)), return_exceptions=True)
        self.pool.shutdown(wait=False)
