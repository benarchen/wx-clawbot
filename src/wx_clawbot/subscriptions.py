"""Native subscriptions shared by input focus, observation and admitted tasks."""

import asyncio


class SubscriptionUnavailable(ValueError):
    pass


class Subscriptions:
    def __init__(self, catalog):
        self.catalog = catalog
        self.roles = {}
        self.bound = {}
        self.lock = asyncio.Lock()
        self.releasing = {}

    async def acquire(self, target, role: str):
        if not isinstance(role, str) or not role or len(role) > 128:
            raise ValueError("Bounded explicit subscription role required")
        async with self.lock:
            session = await self.catalog.require(target)
            agent_kind = getattr(session.binding, "agent", "codex")
            agent = self.catalog.backend_for(agent_kind) if hasattr(self.catalog, "backend_for") else self.catalog.agent
            if agent is None or not agent.capabilities.observe:
                raise SubscriptionUnavailable("Agent does not support native event observation")
            if role == "observer" and not getattr(agent.capabilities, "external_observe", True):
                raise SubscriptionUnavailable("Antigravity 会话采用后台协议托管，不支持桌面 TUI 实时观察（/attach）；请用 /focus 选择会话。")
            current = self.roles.get(target.session_id)
            if current is None:
                shared = any(getattr(s.binding, "agent", "codex") == agent_kind
                             and s.binding.thread_id == session.binding.thread_id for s in self.bound.values())
                if not shared:
                    await agent.observe_loaded(session.binding.thread_id, target.cwd)
                current = set()
                self.roles[target.session_id] = current
                self.bound[target.session_id] = session
            current.add(role)
            return session

    async def release(self, target, role: str):
        async with self.lock:
            current = self.roles.get(target.session_id)
            if current is None or role not in current:
                return False
            if len(current) > 1:
                current.remove(role)  # Other tasks still require the native subscription.
                return True
            # Do not require a still-visible endpoint to remove our own subscription:
            # the user may have closed or changed the terminal in the meantime.
            session = self.bound.get(target.session_id)
            if session is None or session.target != target:
                raise SubscriptionUnavailable("Original subscription identity is no longer registered")
            agent_kind = getattr(session.binding, "agent", "codex")
            shared = any(key != target.session_id and getattr(s.binding, "agent", "codex") == agent_kind
                         and s.binding.thread_id == session.binding.thread_id
                         for key, s in self.bound.items())
            if not shared:
                thread_id = session.binding.thread_id
                finished = asyncio.Event()
                self.releasing[thread_id] = finished
                try:
                    agent = self.catalog.backend_for(agent_kind) if hasattr(self.catalog, "backend_for") else self.catalog.agent
                    if agent is not None:
                        await agent.unsubscribe(thread_id)
                finally:
                    self.releasing.pop(thread_id, None)
                    finished.set()
            del self.roles[target.session_id]
            del self.bound[target.session_id]
            return True

    def event_session(self, target, thread_id: str):
        session = self.bound.get(target.session_id)
        if (not self.roles.get(target.session_id) or session is None or session.target != target
                or session.binding.thread_id != thread_id):
            raise SubscriptionUnavailable("Native event has no matching verified subscription")
        return session

    async def retain_event(self, target, thread_id: str, role: str):
        """Pin an exact request from an existing stream, without admitting new work.

        Native approval/question modals can hide the TUI identity footer. Only
        an already verified subscription may supply this passive event binding;
        acquire() remains the full freshness gate for routing and execution.
        """
        if not isinstance(role, str) or not role.startswith(("interaction-r-", "task-")) or len(role) > 128:
            raise ValueError("Explicit native event retention role required")
        # Local retention has no external await and is atomic on this event loop.
        # Wait only for this thread's unsubscribe, not another thread's slow RPC.
        while (finished := self.releasing.get(thread_id)) is not None:
            await finished.wait()
        session = self.event_session(target, thread_id)
        self.roles[target.session_id].add(role)
        return session

    def has(self, target, role: str):
        return role in self.roles.get(target.session_id, ())
