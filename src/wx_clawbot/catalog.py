"""Project-scoped native sessions, joined to a terminal by its current visible UUID."""

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


class SessionCatalog:
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
        found, pages, unverified = {}, {}, []
        endpoints = await self.directory.discover()
        if len(endpoints) > 256:
            raise ValueError("Too many terminal endpoints for a bounded discovery")
        for endpoint in endpoints:
            if endpoint.classification != "codex_candidate":
                continue
            cwd = await self.directory.cwd(endpoint)
            project = self.project_for(cwd) if isinstance(cwd, Path) else None
            if project is None:
                continue  # No footer/history reads in unregistered projects.
            if cwd not in pages:
                page = await self.agent.list_project_threads(cwd)
                if page.get("nextCursor"):
                    raise ValueError("Project session list exceeds supported bound")
                pages[cwd] = {t["id"]: t for t in page["data"]
                              if t.get("status", {}).get("type") in {"idle", "active"}}
            visible_id = await self.directory.current_thread_id(endpoint)
            thread = pages[cwd].get(visible_id)
            if thread is None:
                unverified.append({"terminal_id": endpoint.terminal_id, "project_alias": project.alias,
                                   "reason": "current_thread_id_missing" if visible_id is None else "thread_not_loaded_in_runtime"})
                continue
            binding = SessionBinding(endpoint, cwd, self.agent.runtime_identity, thread["id"], thread["sessionId"])
            try:
                await verify_binding(binding, self.directory, self.agent)
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
