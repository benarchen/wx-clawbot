"""Read-only endpoint evidence. A Codex process alone does not establish a thread."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .process import ProcessIdentity, read_process, read_process_directory


@dataclass(frozen=True)
class TerminalEndpoint:
    terminal_id: str
    process: ProcessIdentity | None
    classification: str


def tty_device(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    path = Path(value)
    if path.parent != Path("/dev") or not path.name.startswith("tty"):
        return None
    try:
        return path.stat().st_rdev if path.is_char_device() else None
    except OSError:
        return None


async def inspect_terminal(session) -> TerminalEndpoint:
    pid = await session.async_get_variable("jobPid")
    tty = await session.async_get_variable("tty")
    try:
        valid_pid = type(pid) is int or (
            type(pid) is float and pid.is_integer()
        ) or (isinstance(pid, str) and pid.isascii() and pid.isdigit())
        identity = await asyncio.to_thread(read_process, int(pid)) if valid_pid else None
    except (TypeError, ValueError):
        identity = None
    if identity is None:
        classification = "exited_or_unavailable"
    elif identity.tty_device != tty_device(tty):
        classification = "unverified_process"
    elif Path(identity.executable).name == "codex":
        classification = "codex_candidate"
    else:
        classification = "ordinary_terminal"
    return TerminalEndpoint(session.session_id, identity, classification)


class ItermDirectory:
    def __init__(self, connection=None, *, lifecycle=None, _app=None):
        self.connection, self.lifecycle, self._app = connection, lifecycle, _app

    def _connected(self, connection):
        if self._app is not None and connection is not self.connection:
            from .lifecycle import HostUnavailable
            raise HostUnavailable("changed")
        return ItermDirectory(connection, _app=self._app)

    async def _get_app(self):
        if self._app is not None:
            return self._app
        import iterm2
        return await iterm2.async_get_app(self.connection)

    async def discovery_view(self):
        # Only the caller's discovery owns this SDK list. Every target's PID,
        # TTY and footer still comes from fresh RPC/process evidence.
        if self.lifecycle is not None:
            async def acquire(connection):
                view = await ItermDirectory(connection).discovery_view()
                view.lifecycle = self.lifecycle
                return view
            return await self.lifecycle.call(acquire)
        return ItermDirectory(self.connection, _app=await self._get_app())

    async def discover(self) -> list[TerminalEndpoint]:
        if self.lifecycle is not None:
            return await self.lifecycle.call(lambda connection: self._connected(connection).discover())
        app = await self._get_app()
        endpoints = []
        for window in app.windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    endpoints.append(await inspect_terminal(session))
        return endpoints

    async def validate(self, endpoint: TerminalEndpoint) -> bool:
        # Recheck stable terminal ID, PID, process start and TTY before any routing.
        if self.lifecycle is not None:
            return await self.lifecycle.call(lambda connection: self._connected(connection).validate(endpoint))
        app = await self._get_app()
        session = app.get_session_by_id(endpoint.terminal_id)
        if session is None:
            return False
        current = await inspect_terminal(session)
        return current == endpoint and current.classification == "codex_candidate"

    async def current_thread_id(self, endpoint: TerminalEndpoint) -> str | None:
        if self.lifecycle is not None:
            return await self.lifecycle.call(lambda connection: self._connected(connection).current_thread_id(endpoint))
        from .identity import footer_thread_id

        app = await self._get_app()
        session = app.get_session_by_id(endpoint.terminal_id)
        if session is None or await inspect_terminal(session) != endpoint:
            return None
        screen = await session.async_get_screen_contents()
        identity = footer_thread_id(screen)
        return identity if await inspect_terminal(session) == endpoint else None

    async def cwd(self, endpoint: TerminalEndpoint) -> Path | None:
        if endpoint.process is None or endpoint.classification != "codex_candidate":
            return None
        return await asyncio.to_thread(read_process_directory, endpoint.process)
