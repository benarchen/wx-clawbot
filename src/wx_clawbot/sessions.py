"""Revalidate an explicitly attested terminal/native pairing before routing."""

from dataclasses import dataclass
from pathlib import Path

from .hosts.discovery import TerminalEndpoint
from .agents.base import thread_is_loaded


class SessionUnbound(ValueError):
    pass


@dataclass(frozen=True)
class SessionBinding:
    # Construct only after a native input/status handshake; cwd/title is not proof.
    endpoint: TerminalEndpoint
    project: Path
    runtime_identity: tuple[int, int]
    thread_id: str
    native_session_id: str


async def verify_binding(binding: SessionBinding, directory, agent) -> dict:
    if not binding.thread_id or not binding.native_session_id:
        raise SessionUnbound("Native identity proof is incomplete")
    if not await directory.validate(binding.endpoint):
        raise SessionUnbound("Original terminal or process identity is no longer valid")
    visible_identity = getattr(directory, "current_thread_id", None)
    if visible_identity is None or await visible_identity(binding.endpoint) != binding.thread_id:
        raise SessionUnbound("Current terminal thread cannot be verified; refresh its displayed session ID")
    if agent.runtime_identity != binding.runtime_identity:
        raise SessionUnbound("Native runtime generation changed")
    thread = await agent.inspect(binding.thread_id)
    if thread.get("sessionId") != binding.native_session_id:
        raise SessionUnbound("Native session generation changed")
    if Path(thread["cwd"]).resolve() != binding.project.resolve(strict=True):
        raise SessionUnbound("Native project identity changed")
    if not await thread_is_loaded(agent, thread):
        raise SessionUnbound("Original native thread is not loaded")
    return thread
