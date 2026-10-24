"""Read-only endpoint evidence. A Codex process alone does not establish a thread."""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    started: str
    executable: str
    tty: str


@dataclass(frozen=True)
class TerminalEndpoint:
    terminal_id: str
    process: ProcessIdentity | None
    classification: str


async def read_process(pid: int) -> ProcessIdentity | None:
    if type(pid) is not int or pid <= 0:
        return None
    process = await asyncio.create_subprocess_exec(
        "/bin/ps", "-p", str(pid), "-o", "lstart=,comm=,tty=",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "LC_ALL": "C"},
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 3)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    if process.returncode:
        return None
    parts = stdout.decode(errors="replace").strip().split(maxsplit=5)
    if len(parts) != 6:
        return None
    executable, tty = parts[5].rsplit(maxsplit=1)
    return ProcessIdentity(pid, " ".join(parts[:5]), executable, tty.removeprefix("/dev/"))


async def inspect_terminal(session) -> TerminalEndpoint:
    pid = await session.async_get_variable("jobPid")
    tty = await session.async_get_variable("tty")
    try:
        identity = await read_process(int(pid))
    except (TypeError, ValueError):
        identity = None
    if identity is None:
        classification = "exited_or_unavailable"
    elif identity.tty != str(tty).removeprefix("/dev/"):
        classification = "unverified_process"
    elif Path(identity.executable).name == "codex":
        classification = "codex_candidate"
    else:
        classification = "ordinary_terminal"
    return TerminalEndpoint(session.session_id, identity, classification)


class ItermDirectory:
    def __init__(self, connection):
        self.connection = connection

    async def discover(self) -> list[TerminalEndpoint]:
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
