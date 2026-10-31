import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.hosts.lifecycle import HostLifecycle, HostUnavailable, ItermBackend, run_process


def connection():
    return SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))


class HostLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = SimpleNamespace(identity=AsyncMock(return_value="application-one"),
                                       connect=AsyncMock(side_effect=connection),
                                       launch=AsyncMock(), probe=AsyncMock())
        self.host = HostLifecycle(self.backend, rpc_timeout=.02)
        self.addAsyncCleanup(self.host.close)

    async def test_absent_application_is_never_launched_by_passive_recovery(self):
        self.backend.identity.return_value = None
        for _ in range(20):
            with self.assertRaises(HostUnavailable):
                await self.host.ensure()
        self.assertEqual(self.host.state, "not_running")
        self.backend.launch.assert_not_awaited()
        self.backend.connect.assert_not_awaited()

    async def test_concurrent_explicit_requests_launch_and_connect_only_once(self):
        self.backend.identity.return_value = None
        async def launched():
            self.backend.identity.return_value = "application-one"
        self.backend.launch.side_effect = launched
        generations = await asyncio.gather(*(self.host.ensure(launch=True, explicit=True) for _ in range(10)))
        self.backend.launch.assert_awaited_once()
        self.backend.connect.assert_awaited_once()
        self.assertEqual(len(set(generations)), 1)

    async def test_restarted_app_replaces_connection_and_rejects_old_generation(self):
        first = await self.host.ensure()
        previous = self.host.connection
        self.host.verified(first)
        self.backend.identity.return_value = "application-two"
        second = await self.host.ensure()
        self.assertNotEqual(first, second)
        previous.websocket.close.assert_awaited_once()
        self.assertIsNot(self.host.connection, previous)
        with self.assertRaises(HostUnavailable):
            self.host.verified(first)
        self.host.verified(second)
        await self.host.disconnect("rpc", expected=first)
        self.assertEqual(self.host.state, "ready")

    async def test_unresponsive_read_expires_and_recovery_accepts_new_work(self):
        await self.host.ensure()
        async def hung(_):
            await asyncio.Event().wait()
        with self.assertRaises(HostUnavailable):
            await asyncio.wait_for(self.host.call(hung), .3)
        self.assertEqual(self.host.state, "unavailable")
        self.assertIsNone(self.host._connection)
        await self.host.ensure()
        self.assertEqual(await self.host.call(AsyncMock(return_value="ok")), "ok")

    async def test_late_reply_cannot_commit_after_connection_changed(self):
        await self.host.ensure()
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(_):
            started.set()
            await release.wait()
            return "old result"
        work = asyncio.create_task(self.host.call(delayed))
        await started.wait()
        await self.host.disconnect()
        await self.host.ensure()
        new = self.host.connection
        release.set()
        with self.assertRaises(HostUnavailable):
            await work
        self.assertIs(self.host.connection, new)

    async def test_authorization_failure_is_not_repeated_until_explicit_request(self):
        self.backend.connect.side_effect = HostUnavailable("authentication")
        for _ in range(3):
            with self.assertRaises(HostUnavailable):
                await self.host.ensure()
        self.backend.connect.assert_awaited_once()
        with self.assertRaises(HostUnavailable):
            await self.host.ensure(explicit=True)
        self.assertEqual(self.backend.connect.await_count, 2)
        self.backend.connect.side_effect = connection
        self.backend.identity.return_value = "new-application"
        await self.host.ensure()
        self.assertFalse(self.host.authentication_blocked)

    async def test_cancelled_rpc_retires_connection_and_does_not_keep_mutation_running(self):
        await self.host.ensure()
        started = asyncio.Event()
        mutation_finished = False
        async def blocked(_):
            nonlocal mutation_finished
            started.set()
            await asyncio.Event().wait()
            mutation_finished = True
        work = asyncio.create_task(self.host.call(blocked))
        await started.wait()
        work.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await work
        self.assertFalse(mutation_finished)
        self.assertIsNone(self.host._connection)

    async def test_completed_reader_cannot_be_reused_as_live_connection(self):
        await self.host.ensure()
        previous = self.host.connection
        reader = asyncio.create_task(asyncio.sleep(0))
        await reader
        setattr(previous, "_Connection__dispatch_forever_future", reader)
        await self.host.ensure()
        self.assertIsNot(self.host.connection, previous)

    async def test_twenty_reconnects_leave_only_current_owned_reader(self):
        readers, connections = [], []
        async def connect():
            result = connection()
            reader = asyncio.create_task(asyncio.Event().wait())
            readers.append(reader)
            connections.append(result)
            setattr(result, "_Connection__dispatch_forever_future", reader)
            return result
        self.backend.connect.side_effect = connect
        for index in range(20):
            self.backend.identity.return_value = index
            await self.host.ensure()
        self.assertEqual(sum(not r.done() for r in readers), 1)
        self.assertTrue(all(c.websocket.close.await_count == 1 for c in connections[:-1]))
        await self.host.close()
        self.assertTrue(all(r.done() for r in readers))


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unresponsive_api_never_starts_authorization_request(self):
        backend = ItermBackend()
        with patch("wx_clawbot.hosts.lifecycle.run_process", new=AsyncMock()) as authorization, \
                patch.object(backend, "_probe_auth_transport", new=AsyncMock(side_effect=HostUnavailable("connect"))):
            with self.assertRaises(HostUnavailable) as caught:
                await backend.connect()
        self.assertEqual(caught.exception.phase, "connect")
        authorization.assert_not_awaited()

    async def test_auth_transport_probe_never_sends_credentials_or_requests_ui(self):
        backend = ItermBackend()
        class Unauthorized(Exception):
            status_code = 401
        with patch("iterm2.connection._headers", return_value={
                "x-iterm2-cookie": "private-cookie", "x-iterm2-key": "private-key"}), \
                patch.object(backend, "_open_websocket", new=AsyncMock(side_effect=Unauthorized)) as open_socket:
            await backend._probe_auth_transport()
        headers = open_socket.await_args.args[0]
        self.assertNotIn("x-iterm2-cookie", headers)
        self.assertNotIn("x-iterm2-key", headers)
        self.assertEqual(headers["x-iterm2-disable-auth-ui"], "true")
        self.assertEqual(open_socket.await_args.kwargs["timeout"], 2)

    async def test_auth_transport_probe_closes_allowed_connection_without_api_calls(self):
        backend = ItermBackend()
        websocket = SimpleNamespace(close=AsyncMock())
        with patch.object(backend, "_open_websocket", new=AsyncMock(return_value=websocket)):
            await backend._probe_auth_transport()
        websocket.close.assert_awaited_once()

    async def test_auth_transport_probe_unresponsive_server_reports_connect_failure(self):
        backend = ItermBackend()
        with patch.object(backend, "_open_websocket", new=AsyncMock(side_effect=TimeoutError)):
            with self.assertRaises(HostUnavailable) as caught:
                await backend._probe_auth_transport()
        self.assertEqual(caught.exception.phase, "connect")

    async def test_authentication_timeout_with_unresponsive_server_is_retryable(self):
        backend = ItermBackend()
        with patch("wx_clawbot.hosts.lifecycle.run_process", new=AsyncMock(side_effect=TimeoutError)), \
                patch.object(backend, "_probe_auth_transport", create=True,
                             new=AsyncMock(side_effect=[None, HostUnavailable("connect")])) as health:
            with self.assertRaises(HostUnavailable) as caught:
                await backend.connect()
        self.assertEqual(caught.exception.phase, "connect")
        self.assertEqual(health.await_count, 2)

    async def test_authentication_timeout_with_responsive_server_still_blocks_repeated_auth(self):
        backend = ItermBackend()
        with patch("wx_clawbot.hosts.lifecycle.run_process", new=AsyncMock(side_effect=TimeoutError)), \
                patch.object(backend, "_probe_auth_transport", create=True, new=AsyncMock()) as health:
            with self.assertRaises(HostUnavailable) as caught:
                await backend.connect()
        self.assertEqual(caught.exception.phase, "authentication")
        self.assertEqual(health.await_count, 2)

    async def test_auth_transport_timeout_recovers_same_app_without_explicit_command(self):
        backend = ItermBackend()
        host = HostLifecycle(SimpleNamespace(identity=AsyncMock(return_value="same-app"),
                                             connect=backend.connect, probe=AsyncMock()))
        self.addAsyncCleanup(host.close)
        from iterm2.connection import websockets_client
        async def receive():
            await asyncio.Event().wait()
        transport = SimpleNamespace(recv=receive, close=AsyncMock())
        with patch("wx_clawbot.hosts.lifecycle.run_process",
                   new=AsyncMock(side_effect=[TimeoutError(), (0, b"fixture-cookie fixture-key\n")])), \
                patch.object(backend, "_probe_auth_transport", create=True,
                             new=AsyncMock(side_effect=[None, HostUnavailable("connect"), None])), \
                patch.object(websockets_client, "unix_connect", new=AsyncMock(return_value=transport)), \
                patch.object(websockets_client, "connect", new=AsyncMock(return_value=transport)):
            with self.assertRaises(HostUnavailable):
                await host.ensure()
            self.assertFalse(host.authentication_blocked)
            generation = await host.ensure()
            host.verified(generation)
            self.assertEqual(host.state, "ready")

    async def test_authentication_never_calls_sync_sdk_create_or_changes_environment(self):
        backend = ItermBackend()
        before = dict(os.environ)
        from iterm2.connection import websockets_client
        transport = SimpleNamespace(recv=AsyncMock(side_effect=asyncio.CancelledError), close=AsyncMock())
        with patch("wx_clawbot.hosts.lifecycle.run_process", new=AsyncMock(return_value=(0, b"fixture-cookie fixture-key\n"))), \
                patch.object(backend, "_probe_auth_transport", new=AsyncMock()), \
                patch("iterm2.Connection.async_create", new=AsyncMock(side_effect=AssertionError("synchronous auth"))), \
                patch.object(websockets_client, "unix_connect", new=AsyncMock(return_value=transport)), \
                patch.object(websockets_client, "connect", new=AsyncMock(return_value=transport)):
            result = await backend.connect()
            from wx_clawbot.hosts.connection import close_connection
            await close_connection(result)
        self.assertEqual(dict(os.environ), before)

    async def test_malformed_or_denied_auth_is_redacted_and_never_opens_socket(self):
        backend = ItermBackend()
        for code, output in [(1, b"private-secret"), (0, b"one-part"), (0, b"secret\nvalue key")]:
            with patch("wx_clawbot.hosts.lifecycle.run_process", new=AsyncMock(return_value=(code, output))), \
                    patch.object(backend, "_probe_auth_transport", new=AsyncMock()):
                with self.assertRaises(HostUnavailable) as caught:
                    await backend.connect()
                self.assertEqual(caught.exception.phase, "authentication")
                self.assertNotIn("secret", str(caught.exception))

    async def test_real_owned_child_is_reaped_after_timeout_and_event_loop_remains_live(self):
        started = asyncio.get_running_loop().time()
        with self.assertRaises(TimeoutError):
            await run_process([sys.executable, "-c", "import time; time.sleep(60)"], timeout=.05)
        self.assertLess(asyncio.get_running_loop().time() - started, 2.2)
        self.assertEqual(await run_process([sys.executable, "-c", "print('ok')"]), (0, b"ok\n"))

    async def test_oversized_child_output_is_stopped_without_accumulating_output(self):
        with self.assertRaises(ValueError):
            await run_process([sys.executable, "-c", "import sys,time; print('x'*5000,flush=True); time.sleep(60)"], limit=64)
