"""Connect only to an existing native runtime; never starts or resumes a copy."""

import os
import stat
from dataclasses import replace
from pathlib import Path

from websockets.asyncio.client import unix_connect

from .rpc import JsonRpc, ConnectionLost
from .base import Capabilities, SubmissionReceipt, thread_is_loaded
from .. import __version__

SUPPORTED_SERVER_VERSIONS = frozenset({"0.163.0", "0.164.0", "0.165.0", "0.166.0", "0.167.0"})


class CodexConnection:
    capabilities = Capabilities(observe=True, submit_idle=True, queue=True,
                                interrupt=True, shared_interactions=True)
    def __init__(self, transport):
        self.rpc = JsonRpc(transport)

    @property
    def runtime_identity(self):
        try:
            metadata = self.socket_path.stat()
            if (stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == os.getuid()
                    and not stat.S_IMODE(metadata.st_mode) & 0o077
                    and (metadata.st_dev, metadata.st_ino) == self._runtime_identity):
                return self._runtime_identity
        except OSError:
            pass
        self.rpc._fail(ConnectionLost("Native runtime endpoint generation changed"))
        return None

    def _check_runtime(self):
        if self.runtime_identity is None:
            raise ConnectionLost("Native runtime endpoint generation changed")

    @classmethod
    async def connect(cls, socket: Path) -> "CodexConnection":
        metadata = socket.stat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise ValueError("Existing native runtime socket required")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("Native socket must be private and owned by current user")
        transport = await unix_connect(
            str(socket), uri="ws://localhost/", open_timeout=5, close_timeout=2,
            max_size=JsonRpc.MAX_MESSAGE, max_queue=2,
        )
        connection = cls(transport)
        connection.socket_path = socket
        connection._runtime_identity = (metadata.st_dev, metadata.st_ino)
        try:
            result = await connection.rpc.request("initialize", {
                "clientInfo": {"name": "wx-clawbot", "version": __version__},
                "capabilities": {"experimentalApi": True},
            })
            if not isinstance(result, dict) or not all(
                key in result for key in ("userAgent", "platformFamily", "platformOs", "codexHome")
            ):
                raise ValueError("Unsupported native initialize response")
            user_agent = result["userAgent"]
            if not isinstance(user_agent, str) or "/" not in user_agent:
                raise ValueError("Unsupported native server identity")
            version_parts = user_agent.split("/", 1)[1].split()
            server_version = version_parts[0] if version_parts else ""
            if server_version not in SUPPORTED_SERVER_VERSIONS:
                raise ValueError("Native version has no verified schema baseline")
            connection.server_version = server_version
            connection.capabilities = replace(cls.capabilities, image_input=server_version in {"0.165.0", "0.166.0", "0.167.0"})
            connection.server_info = result
            connection._check_runtime()
            await connection.rpc.notify("initialized", {})
            return connection
        except BaseException:
            await connection.close()
            raise

    async def inspect(self, thread_id: str) -> dict:
        self._check_runtime()
        result = await self.rpc.request("thread/read", {"threadId": thread_id, "includeTurns": False})
        self._check_runtime()
        thread = result.get("thread", {})
        if thread.get("id") != thread_id:
            raise ValueError("Native thread identity mismatch")
        return thread

    async def list_project_threads(self, project: Path, *, cursor: str | None = None) -> dict:
        self._check_runtime()
        project = project.resolve(strict=True)
        if not project.is_dir():
            raise ValueError("Existing project directory required")
        params = {"cwd": str(project), "useStateDbOnly": True, "limit": 100}
        if cursor is not None:
            params["cursor"] = cursor
        result = await self.rpc.request("thread/list", params)
        self._check_runtime()
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ValueError("Invalid native thread page")
        directories = {}
        for thread in result["data"]:
            if not isinstance(thread, dict) or not isinstance(thread.get("cwd"), str):
                raise ValueError("Native thread escaped requested project scope")
            cwd = thread['cwd']
            if cwd not in directories:
                directories[cwd] = Path(cwd).resolve()
            if directories[cwd] != project:
                raise ValueError("Native thread escaped requested project scope")
        return result

    async def is_loaded(self, thread_id: str) -> bool:
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Exact native thread identity required")
        return thread_id in await self.loaded_threads()

    async def loaded_threads(self) -> frozenset[str]:
        """A bounded complete runtime snapshot, containing opaque identities only."""
        self._check_runtime()
        cursor, seen, identities = None, set(), set()
        for _ in range(10):
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            result = await self.rpc.request("thread/loaded/list", params)
            rows = result.get("data") if isinstance(result, dict) else None
            if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(v, str) or not 0 < len(v) <= 256 for v in rows):
                raise ValueError("Invalid native loaded-thread page")
            if identities.intersection(rows) or len(set(rows)) != len(rows):
                raise ValueError("Duplicate native loaded-thread identity")
            identities.update(rows)
            cursor = result.get("nextCursor")
            if cursor is None:
                self._check_runtime()
                return frozenset(identities)
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError("Invalid native loaded-thread cursor")
            seen.add(cursor)
        raise ValueError("Native loaded-thread list exceeds supported bound")

    async def observe_loaded(self, thread_id: str, project: Path) -> dict:
        """Subscribe to a loaded thread; never hydrate a stored or forked copy."""
        before = await self.inspect(thread_id)
        if Path(before["cwd"]).resolve() != project.resolve(strict=True):
            raise ValueError("Native project identity mismatch")
        if not await thread_is_loaded(self, before):
            raise ValueError("Thread is not loaded in the target native runtime")
        result = await self.rpc.request("thread/resume", {"threadId": thread_id, "excludeTurns": True})
        after = result.get("thread", {})
        for field in ("id", "cwd", "sessionId", "model", "modelProvider"):
            if after.get(field) != before.get(field):
                raise ValueError("Native identity or model changed during subscription")
        if not await thread_is_loaded(self, after):
            raise ValueError("Original thread unloaded during subscription")
        return after

    async def read_turns(self, thread_id: str, *, cursor: str | None = None, limit: int = 20) -> dict:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Bounded native history page required")
        params = {"threadId": thread_id, "limit": limit, "itemsView": "full", "sortDirection": "asc"}
        if cursor is not None:
            params["cursor"] = cursor
        return await self.rpc.request("thread/turns/list", params)

    async def unsubscribe(self, thread_id: str) -> str:
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Exact native thread identity required")
        result = await self.rpc.request("thread/unsubscribe", {"threadId": thread_id})
        status = result.get("status") if isinstance(result, dict) else None
        if status not in {"unsubscribed", "notSubscribed", "notLoaded"}:
            raise ValueError("Native unsubscribe acknowledgement is missing")
        return status

    async def submit_idle(self, thread_id: str, project: Path, text: str,
                          client_submission_id: str) -> SubmissionReceipt:
        """Submit once to a verified idle native thread; never queue or replay here."""
        if not isinstance(text, str) or not text.strip() or not isinstance(client_submission_id, str) or not client_submission_id:
            raise ValueError("Nonempty input and stable submission identity required")
        thread = await self.inspect(thread_id)
        if Path(thread["cwd"]).resolve() != project.resolve(strict=True):
            raise ValueError("Native project identity mismatch")
        if thread.get("status", {}).get("type") != "idle":
            raise ValueError("Session is not idle; native queue coordination required")
        if thread.get("canAcceptDirectInput") is not True:
            raise ValueError("Native thread does not permit direct input")
        result = await self.rpc.request("turn/start", {
            "threadId": thread_id, "input": [{"type": "text", "text": text}],
            "clientUserMessageId": client_submission_id,
        })
        turn_id = result.get("turn", {}).get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("Native submission receipt has no turn identity; reconcile before retry")
        return SubmissionReceipt(client_submission_id, turn_id)

    async def close(self) -> None:
        await self.rpc.close()
