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
    def __init__(self, connection=None, *, lifecycle=None):
        self.connection, self.lifecycle = connection, lifecycle

    async def discover(self) -> list[TerminalEndpoint]:
        if self.lifecycle is not None:
            return await self.lifecycle.call(lambda connection: ItermDirectory(connection).discover())
        import iterm2

        app = await iterm2.async_get_app(self.connection)
        endpoints = []
        for window in app.windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    endpoints.append(await inspect_terminal(session))
        return endpoints

    async def validate(self, endpoint: TerminalEndpoint) -> bool:
        # Recheck stable terminal ID, PID, process start and TTY before any routing.
        return any(current == endpoint and current.classification == "codex_candidate"
                   for current in await self.discover())

    async def current_thread_id(self, endpoint: TerminalEndpoint) -> str | None:
        if self.lifecycle is not None:
            return await self.lifecycle.call(lambda connection: ItermDirectory(connection).current_thread_id(endpoint))
        import iterm2
        from .identity import footer_thread_id

        app = await iterm2.async_get_app(self.connection)
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
