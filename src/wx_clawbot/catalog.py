"""Project-scoped native sessions, joined to a terminal by its current visible UUID."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Project
from .routing import Target
from .sessions import SessionBinding, SessionUnbound, verify_binding


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

    def project_for(self, cwd: Path):
        candidates = [p for p in self.projects.values() if cwd.is_relative_to(p.root)]
        return max(candidates, key=lambda p: len(p.root.parts)) if candidates else None

    async def discover(self, keyword="") -> tuple[CatalogSession, ...]:
        if not isinstance(keyword, str) or len(keyword) > 4096:
            raise ValueError("Bounded session search required")
        try:
            async with asyncio.timeout(self.DISCOVERY_SECONDS):
                view = getattr(self.directory, "discovery_view", None)
                directory = await view() if view is not None else self.directory
                return await self._discover(keyword, directory)
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
                return {identity: thread for identity, thread in threads.items()
                        if thread['status']['type'] in {'idle', 'active', 'systemError'}}
            if not isinstance(cursor, str) or not 0 < len(cursor) <= 4096 or cursor in cursors:
                raise DiscoveryUnavailable("原生会话分页游标无效，不能使用不完整列表派发。")
            cursors.add(cursor)
        raise DiscoveryUnavailable("单目录会话列表超过十页上限，不能使用不完整列表派发。")

    async def _discover(self, keyword, directory):
        found, pages, unverified = {}, {}, []
        budget = {'pages': 0, 'threads': 0, 'bytes': 0, 'identities': set()}
        endpoints = await directory.discover()
        if len(endpoints) > 256:
            raise ValueError("Too many terminal endpoints for a bounded discovery")
        for endpoint in endpoints:
            if endpoint.classification != "codex_candidate":
                continue
            cwd = await directory.cwd(endpoint)
            project = self.project_for(cwd) if isinstance(cwd, Path) else None
            if project is None:
                continue  # No footer/history reads in unregistered projects.
            if cwd not in pages:
                pages[cwd] = await self.project_threads(cwd, budget)
            visible_id = await directory.current_thread_id(endpoint)
            thread = pages[cwd].get(visible_id)
            if thread is None:
                unverified.append({"terminal_id": endpoint.terminal_id, "project_alias": project.alias,
                                   "reason": "current_thread_id_missing" if visible_id is None else "thread_not_loaded_in_runtime"})
                continue
            binding = SessionBinding(endpoint, cwd, self.agent.runtime_identity, thread["id"], thread["sessionId"])
            try:
                await verify_binding(binding, directory, self.agent)
            except SessionUnbound:
                unverified.append({"terminal_id": endpoint.terminal_id, "project_alias": project.alias,
                                   "reason": "identity_changed"})
                continue
            material = repr((endpoint.terminal_id, endpoint.process, binding.runtime_identity,
                             binding.thread_id, binding.native_session_id))
            identity = "s-" + uuid.uuid5(uuid.NAMESPACE_URL, material).hex
            origin = "managed" if thread["id"] in self.managed_threads else "original"
            target = Target(identity, project.alias, cwd, origin)
            title = thread.get("name") or "Codex 会话"
            if not isinstance(title, str):
                raise ValueError("Invalid native session title")
            session = CatalogSession(target, binding, title[:128])
            found[identity] = session
        # Replace only after the complete discovery succeeded.
        self.sessions = found
        self.unverified = unverified
        needle = keyword.casefold()
        return tuple(sorted((session for session in found.values() if needle in
                             (session.target.project_alias + " " + str(session.target.cwd) + " " + session.title).casefold()),
                            key=lambda session: (session.target.project_alias, session.target.session_id)))

    async def require(self, target: Target) -> CatalogSession:
        session = self.sessions.get(target.session_id)
        if session is None or session.target != target:
            raise SessionUnbound("Session list entry is no longer registered")
        await verify_binding(session.binding, self.directory, self.agent)
        return session
