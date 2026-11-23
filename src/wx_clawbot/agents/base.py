"""Minimal agent boundary; unavailable capabilities stay explicitly false."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


AGENT_ALIASES = {
    "codex": "codex",
    "agy": "antigravity",
    "antigravity": "antigravity",
}


def normalize_agent(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return AGENT_ALIASES.get(value.strip().lower())


@dataclass(frozen=True)
class Capabilities:
    observe: bool = False
    submit_idle: bool = False
    queue: bool = False
    interrupt: bool = False
    shared_interactions: bool = False
    image_input: bool = False
    bridge_queue: bool = False
    model_control: bool = False
    external_observe: bool = True


@dataclass(frozen=True)
class SubmissionReceipt:
    client_submission_id: str
    turn_id: str


async def thread_is_loaded(agent, thread: dict) -> bool:
    status = thread.get("status", {}).get("type")
    if status in {"idle", "active"}:
        return True
    if status != "systemError" or thread.get("canAcceptDirectInput") is not True:
        return False
    checker = getattr(agent, "is_loaded", None)
    return checker is not None and (await checker(thread["id"])) is True


class AgentAdapter(Protocol):
    capabilities: Capabilities
    runtime_identity: tuple[int, int]

    async def inspect(self, thread_id: str) -> dict: ...

    async def is_loaded(self, thread_id: str) -> bool: ...

    async def loaded_threads(self) -> frozenset[str]: ...

    async def observe_loaded(self, thread_id: str, project: Path) -> dict: ...

    async def submit_idle(self, thread_id: str, project: Path, text: str,
                          client_submission_id: str) -> SubmissionReceipt: ...
