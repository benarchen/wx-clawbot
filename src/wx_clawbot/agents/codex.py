"""Connect only to an existing native runtime; never starts or resumes a copy."""

import os
import stat
from pathlib import Path

from websockets.asyncio.client import unix_connect

from .rpc import JsonRpc


class CodexConnection:
    def __init__(self, transport):
        self.rpc = JsonRpc(transport)

    @classmethod
    async def connect(cls, socket: Path) -> "CodexConnection":
        metadata = socket.stat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise ValueError("Existing native runtime socket required")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("Native socket must be private and owned by current user")
        transport = await unix_connect(
            str(socket), uri="ws://localhost/", open_timeout=5, close_timeout=2,
            max_size=JsonRpc.MAX_MESSAGE, max_queue=16,
        )
        connection = cls(transport)
        connection.runtime_identity = (metadata.st_dev, metadata.st_ino)
        try:
            result = await connection.rpc.request("initialize", {
                "clientInfo": {"name": "wx-clawbot", "version": "0.1.0.dev0"},
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
            if server_version not in {"0.163.0", "0.164.0"}:
                raise ValueError("Native version has no verified schema baseline")
            connection.server_version = server_version
            connection.server_info = result
            await connection.rpc.notify("initialized", {})
            return connection
        except BaseException:
            await connection.close()
            raise

    async def inspect(self, thread_id: str) -> dict:
        result = await self.rpc.request("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = result.get("thread", {})
        if thread.get("id") != thread_id:
            raise ValueError("Native thread identity mismatch")
        return thread

    async def list_project_threads(self, project: Path, *, cursor: str | None = None) -> dict:
        project = project.resolve(strict=True)
        if not project.is_dir():
            raise ValueError("Existing project directory required")
        params = {"cwd": str(project), "useStateDbOnly": True, "limit": 100}
        if cursor is not None:
            params["cursor"] = cursor
        result = await self.rpc.request("thread/list", params)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ValueError("Invalid native thread page")
        for thread in result["data"]:
            if not isinstance(thread, dict) or not isinstance(thread.get("cwd"), str) or (
                Path(thread["cwd"]).resolve() != project
            ):
                raise ValueError("Native thread escaped requested project scope")
        return result

    async def observe_loaded(self, thread_id: str, project: Path) -> dict:
        """Subscribe to a loaded thread; never hydrate a stored or forked copy."""
        before = await self.inspect(thread_id)
        if Path(before["cwd"]).resolve() != project.resolve(strict=True):
            raise ValueError("Native project identity mismatch")
        if before.get("status", {}).get("type") not in {"idle", "active"}:
            raise ValueError("Thread is not loaded in the target native runtime")
        result = await self.rpc.request("thread/resume", {"threadId": thread_id, "excludeTurns": True})
        after = result.get("thread", {})
        for field in ("id", "cwd", "sessionId", "model", "modelProvider"):
            if after.get(field) != before.get(field):
                raise ValueError("Native identity or model changed during subscription")
        return after

    async def read_turns(self, thread_id: str, *, cursor: str | None = None) -> dict:
        params = {"threadId": thread_id, "limit": 20, "itemsView": "full", "sortDirection": "asc"}
        if cursor is not None:
            params["cursor"] = cursor
        return await self.rpc.request("thread/turns/list", params)

    async def close(self) -> None:
        await self.rpc.close()
