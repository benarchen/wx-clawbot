"""Exact native routing identity; host provenance is optional and never inferred."""

from dataclasses import dataclass
from pathlib import Path
import uuid

from .hosts.discovery import TerminalEndpoint
from .agents.base import thread_is_loaded


class SessionUnbound(ValueError):
    pass


@dataclass(frozen=True)
class SessionBinding:
    # A real launch may supply provenance. Existing native targets need no host.
    endpoint: TerminalEndpoint | None
    project: Path
    runtime_identity: tuple[int, int]
    thread_id: str
    native_session_id: str


def binding_key(binding: SessionBinding) -> str:
    material = repr(("native-v1", binding.runtime_identity, binding.thread_id,
                     binding.native_session_id, str(binding.project)))
    return "s-" + uuid.uuid5(uuid.NAMESPACE_URL, material).hex


def legacy_binding_key(endpoint: TerminalEndpoint, binding: SessionBinding) -> str:
    """Reconstruct only an exact old fingerprint from real host provenance."""
    material = repr((endpoint.terminal_id, endpoint.process, binding.runtime_identity,
                     binding.thread_id, binding.native_session_id))
    return "s-" + uuid.uuid5(uuid.NAMESPACE_URL, material).hex


async def verify_binding(binding: SessionBinding, directory, agent) -> dict:
    """Verify the exact native target without consulting host identity or display."""
    if (any(not isinstance(value, str) or not 0 < len(value) <= 256
            for value in (binding.thread_id, binding.native_session_id))
            or not isinstance(binding.runtime_identity, tuple) or len(binding.runtime_identity) != 2
            or any(type(value) is not int or value <= 0 for value in binding.runtime_identity)):
        raise SessionUnbound("原生会话身份记录不完整")
    if agent.runtime_identity != binding.runtime_identity:
        raise SessionUnbound("原生运行时已换代，需要重新核验")
    thread = await agent.inspect(binding.thread_id)
    if thread.get("id") != binding.thread_id:
        raise SessionUnbound("原生 thread 身份不匹配")
    if thread.get("sessionId") != binding.native_session_id:
        raise SessionUnbound("原生 session 身份已变化")
    try:
        valid_project = (binding.project.is_absolute() and binding.project.is_dir()
                         and binding.project.resolve(strict=True) == binding.project
                         and isinstance(thread.get("cwd"), str) and Path(thread["cwd"]).is_absolute()
                         and Path(thread["cwd"]).resolve(strict=True) == binding.project)
    except OSError:
        valid_project = False
    if not valid_project:
        raise SessionUnbound("原会话的项目目录已变化")
    if not await thread_is_loaded(agent, thread):
        raise SessionUnbound("原会话已不在原生运行时中加载")
    if agent.runtime_identity != binding.runtime_identity:
        raise SessionUnbound("核验期间原生运行时已变化")
    return thread
