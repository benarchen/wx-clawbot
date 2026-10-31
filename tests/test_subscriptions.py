import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.agents.base import Capabilities
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.routing import Target
from wx_clawbot.subscriptions import SubscriptionUnavailable, Subscriptions


class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.target = Target("fixture-session", "fixture", Path("/example/project"))
        self.session = SimpleNamespace(target=self.target, binding=SimpleNamespace(thread_id="fixture-thread"))
        self.agent = SimpleNamespace(capabilities=Capabilities(observe=True), observe_loaded=AsyncMock(),
                                     unsubscribe=AsyncMock(return_value="unsubscribed"))
        self.catalog = SimpleNamespace(agent=self.agent, require=AsyncMock(return_value=self.session),
                                       sessions={self.target.session_id: self.session})
        self.pool = Subscriptions(self.catalog)

    async def test_observer_and_input_share_one_native_subscription(self):
        await self.pool.acquire(self.target, "route")
        await self.pool.acquire(self.target, "observer")
        await self.pool.acquire(self.target, "observer")
        self.assertEqual(self.agent.observe_loaded.await_count, 1)
        await self.pool.release(self.target, "observer")
        self.agent.unsubscribe.assert_not_called()
        self.assertTrue(self.pool.has(self.target, "route"))

    async def test_detach_keeps_task_events_until_the_last_task_releases(self):
        await self.pool.acquire(self.target, "observer")
        await self.pool.acquire(self.target, "task-fixture")
        await self.pool.release(self.target, "observer")
        self.assertTrue(self.pool.has(self.target, "task-fixture"))
        await self.pool.release(self.target, "task-fixture")
        self.agent.unsubscribe.assert_awaited_once_with("fixture-thread")
        self.assertFalse(self.pool.roles)

    async def test_native_subscribe_denial_does_not_create_local_success(self):
        self.agent.observe_loaded.side_effect = PermissionError("denied")
        with self.assertRaises(PermissionError):
            await self.pool.acquire(self.target, "observer")
        self.assertFalse(self.pool.roles)

    async def test_rebinding_same_thread_to_new_endpoint_preserves_one_subscription(self):
        await self.pool.acquire(self.target, "route")
        await self.pool.acquire(self.target, "task-original")
        replacement = Target("new-terminal-session", "fixture", self.target.cwd)
        new_session = SimpleNamespace(target=replacement, binding=self.session.binding)
        self.catalog.require.return_value = new_session
        await self.pool.acquire(replacement, "route")
        self.agent.observe_loaded.assert_awaited_once()
        await self.pool.release(self.target, "route")
        await self.pool.release(self.target, "task-original")
        self.agent.unsubscribe.assert_not_awaited()
        await self.pool.release(replacement, "route")
        self.agent.unsubscribe.assert_awaited_once_with("fixture-thread")

    async def test_unknown_unsubscribe_keeps_subscription_state_for_reconciliation(self):
        await self.pool.acquire(self.target, "observer")
        self.agent.unsubscribe.side_effect = ConnectionError("unknown receipt")
        with self.assertRaises(ConnectionError):
            await self.pool.release(self.target, "observer")
        self.assertTrue(self.pool.has(self.target, "observer"))

    async def test_unsupported_agent_returns_explicit_unavailable_without_native_call(self):
        self.agent.capabilities = Capabilities()
        with self.assertRaises(SubscriptionUnavailable):
            await self.pool.acquire(self.target, "observer")
        self.agent.observe_loaded.assert_not_called()
        self.assertFalse(self.pool.roles)

    async def test_catalog_refresh_does_not_lose_the_identity_needed_to_release(self):
        await self.pool.acquire(self.target, "observer")
        self.catalog.sessions = {}
        await self.pool.release(self.target, "observer")
        self.agent.unsubscribe.assert_awaited_once_with("fixture-thread")
        self.assertFalse(self.pool.bound)

    async def test_unsubscribe_response_must_confirm_native_state(self):
        connection = object.__new__(CodexConnection)
        connection.rpc = SimpleNamespace(request=AsyncMock())
        for status in ("unsubscribed", "notSubscribed", "notLoaded"):
            connection.rpc.request.return_value = {"status": status}
            self.assertEqual(await connection.unsubscribe("fixture-thread"), status)
        for response in (None, [], {}, {"status": "unexpected"}):
            connection.rpc.request.return_value = response
            with self.assertRaises(ValueError):
                await connection.unsubscribe("fixture-thread")

    async def test_passive_event_requires_existing_exact_binding_and_cannot_grant_a_route(self):
        role = "interaction-r-" + "a" * 32
        with self.assertRaises(SubscriptionUnavailable):
            await self.pool.retain_event(self.target, "fixture-thread", role)
        await self.pool.acquire(self.target, "observer")
        self.catalog.require.reset_mock()
        self.catalog.require.side_effect = ValueError("modal hides footer")
        await self.pool.retain_event(self.target, "fixture-thread", role)
        self.catalog.require.assert_not_awaited()
        with self.assertRaises(SubscriptionUnavailable):
            await self.pool.retain_event(self.target, "different-thread", role)
        with self.assertRaises(ValueError):
            await self.pool.retain_event(self.target, "fixture-thread", "route")
        with self.assertRaises(ValueError):
            await self.pool.acquire(self.target, "task-new-dispatch")
        await self.pool.release(self.target, "observer")
        self.agent.unsubscribe.assert_not_awaited()
        await self.pool.release(self.target, role)
        self.agent.unsubscribe.assert_awaited_once_with("fixture-thread")
