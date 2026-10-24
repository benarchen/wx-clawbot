"""Bounded WebSocket RPC. A timeout never means a task was not executed."""

import asyncio
import json
from typing import Any


class ConnectionLost(ConnectionError):
    pass


class OutcomeUnknown(TimeoutError):
    """The peer may have accepted the request. Do not automatically replay it."""


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class JsonRpc:
    MAX_MESSAGE = 1024 * 1024

    def __init__(self, transport: Any, *, event_limit: int = 256):
        self.transport = transport
        self.events: asyncio.Queue[dict] = asyncio.Queue(maxsize=event_limit)
        self.pending: dict[tuple[type, int | str], asyncio.Future] = {}
        self.failure: ConnectionLost | None = None
        self.sequence = 0
        self.lock = asyncio.Lock()
        self.read_task = asyncio.create_task(self._read())

    @staticmethod
    def key(value: Any) -> tuple[type, int | str]:
        if type(value) not in (int, str):
            raise ConnectionLost("Invalid native request ID type")
        return type(value), value

    async def _send(self, message: dict) -> None:
        if self.failure:
            raise self.failure
        data = json.dumps(message, ensure_ascii=False, allow_nan=False)
        if len(data.encode()) > self.MAX_MESSAGE:
            raise ValueError("RPC message exceeds configured bound")
        async with self.lock:
            await self.transport.send(data)

    async def request(self, method: str, params: dict, *, timeout: float = 10) -> Any:
        if self.failure:
            raise self.failure
        self.sequence += 1
        request_id = self.sequence
        key = self.key(request_id)
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            async with asyncio.timeout(timeout):
                await self._send({"id": request_id, "method": method, "params": params})
                return await future
        except TimeoutError as exc:
            raise OutcomeUnknown("RPC outcome unknown; reconcile native state before retry") from exc
        except (BrokenPipeError, ConnectionResetError) as exc:
            self._fail(ConnectionLost("Native connection disconnected during send"))
            raise self.failure from exc
        finally:
            self.pending.pop(key, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def notify(self, method: str, params: dict) -> None:
        await self._send({"method": method, "params": params})

    async def next_event(self, *, timeout: float = 10) -> dict:
        # Poll the bounded queue without allowing a disconnect to hang a consumer.
        async with asyncio.timeout(timeout):
            while True:
                if self.failure:
                    raise self.failure
                try:
                    return await asyncio.wait_for(self.events.get(), 0.1)
                except TimeoutError:
                    continue

    def _fail(self, failure: ConnectionLost) -> None:
        if self.failure is None:
            self.failure = failure
        for future in self.pending.values():
            if not future.done():
                future.set_exception(self.failure)

    async def _read(self) -> None:
        try:
            while True:
                raw = await self.transport.recv()
                if not raw:
                    raise ConnectionLost("Native connection closed; task outcomes require reconciliation")
                if len(raw.encode() if isinstance(raw, str) else raw) > self.MAX_MESSAGE:
                    raise ConnectionLost("RPC message exceeds configured bound")
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ConnectionLost("RPC message must be an object")
                if "method" in message:
                    if not isinstance(message["method"], str):
                        raise ConnectionLost("RPC method must be a string")
                    if "id" in message:
                        self.key(message["id"])
                    # Never silently drop an approval or terminal event on overload.
                    self.events.put_nowait(message)
                elif "id" in message:
                    key = self.key(message["id"])
                    if ("result" in message) == ("error" in message):
                        raise ConnectionLost("RPC response must contain result or error")
                    future = self.pending.get(key)
                    if future is None or future.done():
                        continue  # Late response cannot cause an automatic retry.
                    if "error" in message:
                        error = message["error"]
                        if not isinstance(error, dict) or type(error.get("code")) is not int:
                            raise ConnectionLost("Invalid RPC error")
                        future.set_exception(RpcError(error["code"], str(error.get("message", "RPC error"))))
                    else:
                        future.set_result(message["result"])
                else:
                    raise ConnectionLost("Unrecognized RPC message")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc if isinstance(exc, ConnectionLost) else ConnectionLost(type(exc).__name__))

    async def close(self) -> None:
        self._fail(ConnectionLost("Bridge connection closed"))
        self.read_task.cancel()
        await asyncio.gather(self.read_task, return_exceptions=True)
        await self.transport.close()
