"""Minimal agent boundary; unavailable capabilities stay explicitly false."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Capabilities:
    observe: bool = False
    submit_idle: bool = False
    queue: bool = False
    interrupt: bool = False
    shared_interactions: bool = False


@dataclass(frozen=True)
class SubmissionReceipt:
    client_submission_id: str
    turn_id: str


class AgentAdapter(Protocol):
    capabilities: Capabilities

    async def inspect(self, thread_id: str) -> dict: ...

    async def observe_loaded(self, thread_id: str, project: Path) -> dict: ...

    async def submit_idle(self, thread_id: str, project: Path, text: str,
                          client_submission_id: str) -> SubmissionReceipt: ...
