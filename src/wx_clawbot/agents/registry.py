"""Shared multi-agent routing, labeling and backend resolution policies."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AgentPolicy:
    kind: str
    tag: str
    runtime_label: str
    queue_label: str
    uses_visible_host: bool


POLICIES: dict[str, AgentPolicy] = {
    "codex": AgentPolicy(
        kind="codex",
        tag="〔codex〕",
        runtime_label="原生运行时",
        queue_label="原生队列",
        uses_visible_host=True,
    ),
    "antigravity": AgentPolicy(
        kind="antigravity",
        tag="〔agy〕",
        runtime_label="Antigravity 运行时",
        queue_label="桥接队列",
        uses_visible_host=False,
    ),
}


def policy_for(agent_kind: str) -> AgentPolicy:
    return POLICIES.get(agent_kind, POLICIES["codex"])


def runtime_label(agent_kind: str) -> str:
    return policy_for(agent_kind).runtime_label


def queue_label(agent_kind: str) -> str:
    return policy_for(agent_kind).queue_label


def session_tag(agent_kind: str) -> str:
    return policy_for(agent_kind).tag


def managed_key(target) -> tuple:
    if getattr(target, "agent", "codex") == "codex":
        return (target.project_alias, target.cwd)
    return (target.project_alias, target.cwd, target.agent)


def handoff_block(agent_kind: str, thread_id: str) -> str:
    if agent_kind != "antigravity" or not thread_id:
        return ""
    return f"电脑接手：\n\n```sh\nagy --conversation {thread_id}\n```"


def resolve_control_agent(
    command,
    target,
    *,
    default_agent: str = "codex",
    backend_ready: Callable[[str], bool] | None = None,
) -> str:
    """Resolve the target agent for native control commands in one place."""
    explicit = getattr(command, "agent", None)
    if explicit is not None:
        return explicit
    if target is not None:
        return getattr(target, "agent", "codex")
    if backend_ready is not None:
        if backend_ready(default_agent):
            return default_agent
        if backend_ready("antigravity") and not backend_ready("codex"):
            return "antigravity"
    return "codex"
