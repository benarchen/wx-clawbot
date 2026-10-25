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

    async def acquire(self, target, role: str):
        if not isinstance(role, str) or not role or len(role) > 128:
            raise ValueError("Bounded explicit subscription role required")
        async with self.lock:
            session = await self.catalog.require(target)
            agent = self.catalog.agent
            if not agent.capabilities.observe:
                raise SubscriptionUnavailable("Agent does not support native event observation")
            current = self.roles.get(target.session_id)
            if current is None:
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
            await self.catalog.agent.unsubscribe(session.binding.thread_id)
            del self.roles[target.session_id]
            del self.bound[target.session_id]
            return True

    def has(self, target, role: str):
        return role in self.roles.get(target.session_id, ())
