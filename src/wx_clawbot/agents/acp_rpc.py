"""Bounded stdio JSON-RPC 2.0 client for Agent Client Protocol (ACP) subprocesses."""

import asyncio
import json
from collections import deque
from typing import Any

from .rpc import ConnectionLost, OutcomeUnknown, RpcError


class StdioJsonRpc:
    # A 10 MiB image expands to ~13.3 MiB base64 in ACP prompt content blocks.
    MAX_MESSAGE = 16 * 1024 * 1024
    MAX_SEND = 16 * 1024 * 1024
    MAX_EVENT_BYTES = 32 * 1024 * 1024
    MAX_STDERR_LINES = 64

    def __init__(self, process: Any, *, event_limit: int = 512, on_notification=None):
        self.process = process
        self.on_notification = on_notification
        self.events: asyncio.Queue[dict] = asyncio.Queue(maxsize=event_limit)
        self.event_sizes: deque[int] = deque()
        self.event_bytes = 0
        self.pending: dict[tuple[type, int | str], asyncio.Future] = {}
        self.failure: ConnectionLost | None = None
        self.sequence = 0
        self.lock = asyncio.Lock()
        self.stderr_tail: deque[str] = deque(maxlen=self.MAX_STDERR_LINES)
        self.read_task = asyncio.create_task(self._read())
        self.stderr_task = (
            asyncio.create_task(self._read_stderr())
            if getattr(process, "stderr", None) is not None
            else None
        )

    @staticmethod
    def key(value: Any) -> tuple[type, int | str]:
        if type(value) not in (int, str):
            raise ConnectionLost("Invalid ACP request ID type")
        return type(value), value

    async def _send(self, message: dict) -> None:
        if self.failure:
            raise self.failure
        data = json.dumps(message, ensure_ascii=False, allow_nan=False)
        encoded = (data + "\n").encode("utf-8")
        if len(encoded) > self.MAX_SEND:
            raise ValueError("ACP RPC message exceeds configured bound")
        async with self.lock:
            if self.failure:
                raise self.failure
            self.process.stdin.write(encoded)
            await self.process.stdin.drain()

    async def request(self, method: str, params: dict | None = None, *, timeout: float | None = 30) -> Any:
        if self.failure:
            raise self.failure
        self.sequence += 1
        request_id = self.sequence
        key = self.key(request_id)
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            if timeout is None:
                await self._send(payload)
                return await future
            async with asyncio.timeout(timeout):
                await self._send(payload)
                return await future
        except TimeoutError as exc:
            raise OutcomeUnknown("ACP RPC outcome unknown; do not automatically replay") from exc
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            self._fail(ConnectionLost("ACP subprocess disconnected during send"))
            raise self.failure from exc
        finally:
            self.pending.pop(key, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def notify(self, method: str, params: dict | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        try:
            await self._send(payload)
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            self._fail(ConnectionLost("ACP subprocess disconnected during notify"))
            raise self.failure from exc

    async def respond(self, request_id: int | str, result: dict) -> None:
        self.key(request_id)
        if not isinstance(result, dict):
            raise ValueError("ACP response must be an object")
        try:
            await self._send({"jsonrpc": "2.0", "id": request_id, "result": result})
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            self._fail(ConnectionLost("ACP subprocess disconnected during response"))
            raise self.failure from exc

    async def respond_error(self, request_id: int | str, code: int, message: str) -> None:
        self.key(request_id)
        try:
            await self._send({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": str(message)[:512]},
            })
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    async def next_event(self, *, timeout: float = 10) -> dict:
        async with asyncio.timeout(timeout):
            while True:
                if self.failure and self.events.empty():
                    raise self.failure
                try:
                    event = await asyncio.wait_for(self.events.get(), 0.1)
                    self.event_bytes -= self.event_sizes.popleft()
                    return event
                except TimeoutError:
                    continue

    def _fail(self, failure: ConnectionLost) -> None:
        if self.failure is None:
            self.failure = failure
        for future in self.pending.values():
            if not future.done():
                future.set_exception(self.failure)

    async def _read_stderr(self) -> None:
        try:
            while True:
                raw = await self.process.stderr.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    self.stderr_tail.append(line[:256])
        except (asyncio.CancelledError, OSError):
            pass

    async def _read(self) -> None:
        try:
            while True:
                raw = await self.process.stdout.readline()
                if not raw:
                    raise ConnectionLost("ACP subprocess closed stdout; active turns require reconciliation")
                if len(raw) > self.MAX_MESSAGE:
                    raise ConnectionLost("ACP RPC message exceeds configured bound")
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                message = json.loads(text)
                if not isinstance(message, dict):
                    raise ConnectionLost("ACP RPC message must be an object")
                if "method" in message:
                    if not isinstance(message["method"], str):
                        raise ConnectionLost("ACP RPC method must be a string")
                    if "id" in message:
                        self.key(message["id"])
                    elif self.on_notification is not None:
                        # Process server notifications synchronously in wire order before
                        # any subsequent RPC response future can wake a caller.
                        self.on_notification(message)
                        continue
                    if self.event_bytes + len(raw) > self.MAX_EVENT_BYTES:
                        raise ConnectionLost("ACP event byte budget exceeded")
                    await self.events.put(message)
                    self.event_sizes.append(len(raw))
                    self.event_bytes += len(raw)
                elif "id" in message:
                    key = self.key(message["id"])
                    if ("result" in message) == ("error" in message):
                        raise ConnectionLost("ACP RPC response must contain result or error")
                    future = self.pending.get(key)
                    if future is None or future.done():
                        continue
                    if "error" in message:
                        error = message["error"]
                        if not isinstance(error, dict) or type(error.get("code")) is not int:
                            raise ConnectionLost("Invalid ACP RPC error")
                        future.set_exception(RpcError(error["code"], str(error.get("message", "ACP RPC error"))))
                    else:
                        future.set_result(message["result"])
                else:
                    raise ConnectionLost("Unrecognized ACP RPC message")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc if isinstance(exc, ConnectionLost) else ConnectionLost(type(exc).__name__))

    async def close(self) -> None:
        self._fail(ConnectionLost("ACP bridge connection closed"))
        try:
            if getattr(self.process, "stdin", None) is not None:
                self.process.stdin.close()
        except Exception:
            pass
        for task in (self.read_task, self.stderr_task):
            if task is not None:
                task.cancel()
        tasks = [t for t in (self.read_task, self.stderr_task) if t is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if getattr(self.process, "returncode", None) is None:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except TimeoutError:
                try:
                    self.process.terminate()
                    await asyncio.wait_for(self.process.wait(), timeout=3)
                except TimeoutError:
                    try:
                        self.process.kill()
                    except ProcessLookupError:
                        pass
                    await self.process.wait()
                except ProcessLookupError:
                    pass
