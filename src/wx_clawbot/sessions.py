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


async def verify_binding(binding: SessionBinding, directory, agent, *, require_visible=False) -> dict:
    """Verify an established target; only first association needs the TUI footer."""
    if not binding.thread_id or not binding.native_session_id:
        raise SessionUnbound("原生会话身份记录不完整")
    if not await directory.validate(binding.endpoint):
        raise SessionUnbound("原终端或 Codex 进程已退出或变化")
    if require_visible:
        visible_identity = getattr(directory, "current_thread_id", None)
        if visible_identity is None or await visible_identity(binding.endpoint) != binding.thread_id:
            raise SessionUnbound("首次关联的终端会话 ID 无法核验")
    if agent.runtime_identity != binding.runtime_identity:
        raise SessionUnbound("原生运行时已换代，需要重新核验")
    thread = await agent.inspect(binding.thread_id)
    if thread.get("id") != binding.thread_id:
        raise SessionUnbound("原生 thread 身份不匹配")
    if thread.get("sessionId") != binding.native_session_id:
        raise SessionUnbound("原生 session 身份已变化")
    if Path(thread["cwd"]).resolve() != binding.project.resolve(strict=True):
        raise SessionUnbound("原会话的项目目录已变化")
    if not await thread_is_loaded(agent, thread):
        raise SessionUnbound("原会话已不在原生运行时中加载")
    if agent.runtime_identity != binding.runtime_identity or not await directory.validate(binding.endpoint):
        raise SessionUnbound("核验期间原终端、进程或运行时已变化")
    return thread
