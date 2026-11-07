"""Project-scoped loaded native targets; host cwd only extends the declared scope."""

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Project
from .routing import Target
from .sessions import SessionBinding, SessionUnbound, binding_key, legacy_binding_key, verify_binding
from .hosts.lifecycle import HostUnavailable


@dataclass(frozen=True)
class CatalogSession:
    target: Target
    binding: SessionBinding
    title: str


class DiscoveryUnavailable(ValueError):
    """An incomplete discovery cannot authorize new dispatch."""


class SessionCatalog:
    DISCOVERY_SECONDS = 25
    PROJECT_PAGES = 10
    TOTAL_PAGES = 64
    TOTAL_THREADS = 4096
    TOTAL_BYTES = 32 * 1024 * 1024

    def __init__(self, projects: tuple[Project, ...], directory, agent):
        self.projects = {p.alias: p for p in projects}
        self.directory, self.agent = directory, agent
        self.sessions = {}
        self.unverified = []
        self.managed_threads = set()
        self.legacy_targets = {}
        self.directories = {p.root for p in projects}
        self.scope_note = "发现范围为注册根与已知的准确目录，不递归扫描子目录。"

    def project_for(self, cwd: Path):
        candidates = [p for p in self.projects.values() if cwd.is_relative_to(p.root)]
        return max(candidates, key=lambda p: len(p.root.parts)) if candidates else None

    def _describe(self, binding, *, managed=False, title="Codex 会话"):
        project = self.project_for(binding.project)
        if project is None or not isinstance(title, str):
            raise ValueError("Registered project and native title required")
        identity = binding_key(binding)
        origin = "managed" if managed or binding.thread_id in self.managed_threads else "original"
        target = Target(identity, project.alias, binding.project, origin)
        return CatalogSession(target, binding, title[:128])

    def remember_verified(self, binding, *, managed=False, title="Codex 会话"):
        """Retain an association already proven by launch reconciliation."""
        session = self._describe(binding, managed=managed, title=title)
        self.sessions[session.target.session_id] = session
        self.include_directory(binding.project)
        return session

    def include_directory(self, cwd):
        cwd = Path(cwd)
        if cwd.resolve(strict=True) != cwd or not cwd.is_dir() or self.project_for(cwd) is None:
            raise ValueError("Registered canonical directory required")
        if len(self.directories | {cwd}) > 256:
            raise DiscoveryUnavailable("会话发现超过 256 个准确目录的上限。")
        self.directories.add(cwd)

    async def discover(self, keyword="") -> tuple[CatalogSession, ...]:
        if not isinstance(keyword, str) or len(keyword) > 4096:
            raise ValueError("Bounded session search required")
        try:
            async with asyncio.timeout(self.DISCOVERY_SECONDS):
                return await self._discover(keyword)
        except DiscoveryUnavailable:
            raise
        except TimeoutError:
            raise DiscoveryUnavailable("会话发现超过总时限，尚未取得完整证据；本次未授予新的派发资格。") from None
        except (ValueError, TypeError, KeyError):
            raise DiscoveryUnavailable("原生会话列表或身份数据无效，尚未取得完整证据；请核对后刷新。") from None

    async def project_threads(self, cwd, budget):
        threads, cursor, cursors = {}, None, set()
        for _ in range(self.PROJECT_PAGES):
            if budget['pages'] >= self.TOTAL_PAGES:
                raise DiscoveryUnavailable("会话发现超过总页数上限，不能使用不完整列表派发。")
            page = (await self.agent.list_project_threads(cwd, cursor=cursor) if cursor is not None
                    else await self.agent.list_project_threads(cwd))
            rows = page.get('data') if isinstance(page, dict) else None
            if not isinstance(rows, list) or len(rows) > 100:
                raise DiscoveryUnavailable("原生会话分页形态无效，不能使用不完整列表派发。")
            budget['pages'] += 1
            budget['bytes'] += len(json.dumps(page, ensure_ascii=False, allow_nan=False).encode())
            if budget['bytes'] > self.TOTAL_BYTES:
                raise DiscoveryUnavailable("会话发现超过字节预算，不能使用不完整列表派发。")
            directories = {}
            for thread in rows:
                if (not isinstance(thread, dict) or not isinstance(thread.get('id'), str)
                        or not 0 < len(thread['id']) <= 256 or thread['id'] in budget['identities']
                        or not isinstance(thread.get('cwd'), str)
                        or not isinstance(thread.get('status'), dict)
                        or not isinstance(thread['status'].get('type'), str)):
                    raise DiscoveryUnavailable("原生会话身份重复、越界或结构无效，不能授予新的派发资格。")
                value = thread['cwd']
                if value not in directories:
                    directories[value] = Path(value).resolve()
                if directories[value] != cwd:
                    raise DiscoveryUnavailable("原生会话目录越界，不能授予新的派发资格。")
                threads[thread['id']] = thread
                budget['identities'].add(thread['id'])
                budget['threads'] += 1
                if budget['threads'] > self.TOTAL_THREADS:
                    raise DiscoveryUnavailable("会话发现超过总条数上限，不能使用不完整列表派发。")
            cursor = page.get('nextCursor')
            if cursor is None:
                return threads
            if not isinstance(cursor, str) or not 0 < len(cursor) <= 4096 or cursor in cursors:
                raise DiscoveryUnavailable("原生会话分页游标无效，不能使用不完整列表派发。")
            cursors.add(cursor)
        raise DiscoveryUnavailable("单目录会话列表超过十页上限，不能使用不完整列表派发。")

    async def _discover(self, keyword):
        found, aliases, unverified = {}, {}, []
        budget = {'pages': 0, 'threads': 0, 'bytes': 0, 'identities': set()}
        generation = self.agent.runtime_identity
        endpoints = []
        # SDK metadata can add exact cwds and prove an old fingerprint; it never
        # determines native thread identity and cannot block root-only discovery.
        self.scope_note = "发现范围为注册根与已知准确目录；子目录不作递归扫描。"
        try:
            async with asyncio.timeout(1):
                view = getattr(self.directory, "discovery_view", None)
                directory = await view() if view is not None else self.directory
                candidates = await directory.discover()
                if len(candidates) > 256:
                    raise DiscoveryUnavailable("宿主端点超过有界目录发现上限。")
                for endpoint in candidates:
                    if endpoint.classification != "codex_candidate" or endpoint.process is None:
                        continue
                    cwd = await directory.cwd(endpoint)
                    if isinstance(cwd, Path) and self.project_for(cwd) is not None:
                        self.include_directory(cwd)
                        endpoints.append(endpoint)
        except (HostUnavailable, OSError, TimeoutError):
            self.scope_note += "宿主目录扩展暂不可用，仍核验注册根与已登记目录。"
        loaded = await self.agent.loaded_threads()
        if not isinstance(loaded, frozenset) or any(not isinstance(v, str) or not v for v in loaded):
            raise ValueError("Complete native loaded-thread identities required")
        for cwd in sorted(self.directories):
            project = self.project_for(cwd)
            if project is None or not cwd.is_dir() or cwd.resolve() != cwd:
                continue
            threads = await self.project_threads(cwd, budget)
            for identity in sorted(loaded.intersection(threads)):
                thread = threads[identity]
                if not isinstance(thread.get("sessionId"), str) or not thread["sessionId"]:
                    raise ValueError("Native session identity required")
                binding = SessionBinding(None, cwd, generation, identity, thread["sessionId"])
                try:
                    await verify_binding(binding, None, self.agent)
                except SessionUnbound:
                    unverified.append({"project_alias": project.alias, "reason": "native_identity_changed"})
                    continue
                title = thread.get("name") or "Codex 会话"
                session = self._describe(binding, title=title)
                found[session.target.session_id] = session
                for endpoint in endpoints:
                    old_key = legacy_binding_key(endpoint, binding)
                    if old_key in aliases and aliases[old_key].binding != binding:
                        raise ValueError("Conflicting legacy native identity")
                    aliases[old_key] = session
        if self.agent.runtime_identity != generation:
            raise DiscoveryUnavailable("发现期间原生运行时已变化，本次未授予派发资格。")
        # Replace only after the complete discovery succeeded.
        self.sessions = found
        self.legacy_targets = aliases
        self.unverified = unverified
        needle = keyword.casefold()
        return tuple(sorted((session for session in found.values() if needle in
                             (session.target.project_alias + " " + str(session.target.cwd) + " " + session.title).casefold()),
                            key=lambda session: (session.target.project_alias, session.target.session_id)))

    async def require(self, target: Target) -> CatalogSession:
        session = self.sessions.get(target.session_id)
        if session is None:
            current = self.legacy_targets.get(target.session_id)
            if current is not None:
                session = replace(current, target=replace(current.target, session_id=target.session_id))
        if session is None or session.target != target:
            raise SessionUnbound("所选会话已无法核验或不在有效会话目录中")
        await verify_binding(session.binding, self.directory, self.agent)
        return session
