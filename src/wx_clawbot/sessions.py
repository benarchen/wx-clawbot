"""Exact native routing identity; host provenance is optional and never inferred."""

from dataclasses import dataclass
from pathlib import Path
import uuid

from .hosts.discovery import TerminalEndpoint
from .agents.base import thread_is_loaded


class SessionUnbound(ValueError):
    def __init__(self, message, *, reason="evidence_missing"):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class SessionBinding:
    # A real launch may supply provenance. Existing native targets need no host.
    endpoint: TerminalEndpoint | None
    project: Path
    runtime_identity: tuple[int, int]
    thread_id: str
    native_session_id: str
    agent: str = "codex"


def binding_key(binding: SessionBinding) -> str:
    if binding.agent == "antigravity":
        material = repr(("agy-v1", binding.thread_id, str(binding.project)))
        return "s-" + uuid.uuid5(uuid.NAMESPACE_URL, material).hex
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
    if agent is None or agent.runtime_identity is None:
        raise SessionUnbound("原生连接暂不可用，身份尚未核验", reason="verification_pending")
    if binding.agent == "antigravity":
        if getattr(agent, "agent_kind", None) != "antigravity":
            raise SessionUnbound("目标会话与 Antigravity 运行时不匹配", reason="runtime_changed")
        try:
            thread = await agent.inspect(binding.thread_id)
        except ValueError:
            raise SessionUnbound("Antigravity 会话已卸载或不在活跃会话列表中", reason="not_loaded") from None
        if thread.get("id") != binding.thread_id or thread.get("sessionId") != binding.native_session_id:
            raise SessionUnbound("Antigravity 会话身份不匹配", reason="native_identity_changed")
        try:
            valid_project = (binding.project.is_absolute() and binding.project.is_dir()
                             and binding.project.resolve(strict=True) == binding.project
                             and isinstance(thread.get("cwd"), str) and Path(thread["cwd"]).is_absolute()
                             and Path(thread["cwd"]).resolve(strict=True) == binding.project)
        except OSError:
            valid_project = False
        if not valid_project:
            raise SessionUnbound("原会话的项目目录已变化", reason="cwd_changed")
        if thread.get("status", {}).get("type") not in {"idle", "active", "resumable"}:
            raise SessionUnbound("Antigravity 会话当前不可接入", reason="not_loaded")
        if agent.runtime_identity is None:
            raise SessionUnbound("核验期间 Antigravity 连接断开", reason="verification_pending")
        return thread
    if agent.runtime_identity != binding.runtime_identity:
        raise SessionUnbound("原生运行时已换代，需要重新核验", reason="runtime_changed")
    thread = await agent.inspect(binding.thread_id)
    if thread.get("id") != binding.thread_id:
        raise SessionUnbound("原生 thread 身份不匹配", reason="native_identity_changed")
    if thread.get("sessionId") != binding.native_session_id:
        raise SessionUnbound("原生 session 身份已变化", reason="native_identity_changed")
    try:
        valid_project = (binding.project.is_absolute() and binding.project.is_dir()
                         and binding.project.resolve(strict=True) == binding.project
                         and isinstance(thread.get("cwd"), str) and Path(thread["cwd"]).is_absolute()
                         and Path(thread["cwd"]).resolve(strict=True) == binding.project)
    except OSError:
        valid_project = False
    if not valid_project:
        raise SessionUnbound("原会话的项目目录已变化", reason="cwd_changed")
    if not await thread_is_loaded(agent, thread):
        raise SessionUnbound("原会话已不在原生运行时中加载", reason="not_loaded")
    if agent.runtime_identity is None:
        raise SessionUnbound("核验期间原生连接断开", reason="verification_pending")
    if agent.runtime_identity != binding.runtime_identity:
        raise SessionUnbound("核验期间原生运行时已变化", reason="runtime_changed")
    return thread
