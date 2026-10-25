"""One owner's routing state; targets are frozen before asynchronous dispatch."""

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, Project, resolve_directory


class RouteError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    session_id: str
    project_alias: str
    cwd: Path
    origin: str = "original"


@dataclass(frozen=True)
class SessionList:
    list_id: str
    targets: tuple[Target, ...]
    expires_at: float


@dataclass(frozen=True)
class Dispatch:
    target: Target
    route_revision: int
    text: str


class Routes:
    def __init__(self, projects: tuple[Project, ...], *, ttl=600, clock=time.monotonic):
        if not projects or not 1 <= ttl <= 3600 or len({p.alias for p in projects}) != len(projects):
            raise ValueError("Unique registered projects and a bounded list TTL required")
        self.projects = {p.alias: p for p in projects}
        self.ttl, self.clock = ttl, clock
        self.project = None
        self.cwd = None
        self.target = None
        self.observer = None
        self.mode = "unbound"
        self.revision = 0
        self.list = None

    def validate_target(self, target: Target):
        project = self.projects.get(target.project_alias)
        if not target.session_id or project is None or target.origin not in {"original", "managed"}:
            raise RouteError("会话尚未注册或身份未核验。")
        try:
            cwd = resolve_directory(project, str(target.cwd))
        except ConfigError as exc:
            raise RouteError("会话目录已失效或越出注册范围。") from exc
        if cwd != target.cwd:
            raise RouteError("会话目录必须使用已核验的真实路径。")

    def resolve_cd(self, value: str) -> tuple[Project, Path]:
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise RouteError("请提供项目别名或目录。")
        value = value.strip()
        if value in self.projects:
            project = self.projects[value]
            try:
                return project, resolve_directory(project, str(project.root))
            except ConfigError as exc:
                raise RouteError("项目根目录不可访问。") from exc
        path = Path(value).expanduser()
        if not path.is_absolute():
            if self.cwd is None:
                raise RouteError("尚未选择目录，请先使用项目别名或绝对路径。")
            path = self.cwd / path
        try:
            real = path.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise RouteError("目录不可访问。") from exc
        candidates = [p for p in self.projects.values() if real.is_relative_to(p.root)]
        if not candidates:
            raise RouteError("目录不在已注册项目范围内。")
        project = max(candidates, key=lambda p: len(p.root.parts))
        try:
            return project, resolve_directory(project, str(real))
        except ConfigError as exc:
            raise RouteError("目录不可访问。") from exc

    def snapshot(self, targets: tuple[Target, ...]) -> SessionList:
        if len(targets) > 100 or len({t.session_id for t in targets}) != len(targets):
            raise RouteError("会话列表超出上限或包含重复身份。")
        for target in targets:
            self.validate_target(target)
        snapshot = SessionList("list-" + uuid.uuid4().hex, tuple(targets), self.clock() + self.ttl)
        # Listing ends focused input; an independent observation remains intact.
        self.target, self.mode = None, "unbound"
        self.list = snapshot
        self.revision += 1
        return snapshot

    def select(self, index: int, *, snapshot: SessionList | None = None) -> Target:
        snapshot = self.list if snapshot is None else snapshot
        if snapshot is None or self.clock() >= snapshot.expires_at:
            raise RouteError("会话列表已过期，请重新执行 /sessions。")
        if type(index) is not int or not 1 <= index <= len(snapshot.targets):
            raise RouteError("会话序号不在该列表中。")
        target = snapshot.targets[index - 1]
        self.validate_target(target)
        return target

    def _check_revision(self, expected: int):
        if expected != self.revision:
            raise RouteError("处理期间选择已变化，请刷新后重试。")

    def focus(self, target: Target, *, expected: int):
        self._check_revision(expected)
        self.validate_target(target)
        self.target, self.mode = target, "focused"
        self.project, self.cwd = self.projects[target.project_alias], target.cwd
        self.revision += 1

    def managed(self, target: Target, *, expected: int):
        if target.origin != "managed":
            raise RouteError("该会话不是本项目创建的受管会话。")
        self.focus(target, expected=expected)
        self.mode = "managed"

    def unfocus(self):
        self.target, self.mode = None, "unbound"
        self.revision += 1

    def attach_confirmed(self, target: Target, *, expected: int):
        # Called only after the host/agent confirms an actual native subscription.
        self._check_revision(expected)
        self.validate_target(target)
        if self.observer != target:
            self.observer = target
            self.revision += 1

    def detach_confirmed(self, *, expected: int):
        self._check_revision(expected)
        if self.observer is not None:
            self.observer = None
            self.revision += 1

    def freeze(self, text: str, *, target: Target | None = None) -> Dispatch:
        target = target if target is not None else self.target
        if target is None:
            raise RouteError("请先使用 /cd 或 /focus 选择执行目标。")
        if not isinstance(text, str) or not text.strip() or len(text) > 32000:
            raise RouteError("请提供不超过 32000 个字符的任务。")
        self.validate_target(target)
        return Dispatch(target, self.revision, text)
