"""Native identity and complete loaded snapshots without sockets or UI."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import os
import stat
import unittest
from unittest.mock import AsyncMock, Mock

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.sessions import SessionBinding, SessionUnbound, binding_key, legacy_binding_key, verify_binding
from wx_clawbot.hosts.discovery import TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity


class LoadedSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def connection(self, pages):
        native = object.__new__(CodexConnection)
        native._runtime_identity = (1, 2)
        native.socket_path = SimpleNamespace(stat=lambda: SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600,
            st_uid=os.getuid(), st_dev=1, st_ino=2))
        native.rpc = SimpleNamespace(request=AsyncMock(side_effect=pages), _fail=Mock())
        return native

    async def test_same_path_replaced_socket_revokes_identity_before_any_native_query(self):
        from wx_clawbot.agents.rpc import ConnectionLost
        native = self.connection([{'data': []}])
        native.socket_path.stat = lambda: SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600,
            st_uid=os.getuid(), st_dev=1, st_ino=3)
        with self.assertRaises(ConnectionLost):
            await native.loaded_threads()
        native.rpc.request.assert_not_called()
        native.rpc._fail.assert_called()

    async def test_endpoint_change_during_read_rejects_an_otherwise_valid_native_reply(self):
        from wx_clawbot.agents.rpc import ConnectionLost
        native = self.connection([])
        async def changed(*_):
            native.socket_path.stat = lambda: SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600,
                st_uid=os.getuid(), st_dev=2, st_ino=3)
            return {'thread': {'id': 'a'}}
        native.rpc.request.side_effect = changed
        with self.assertRaises(ConnectionLost):
            await native.inspect('a')

    async def test_complete_membership_does_not_stop_on_first_matching_page(self):
        native = self.connection([{'data': ['a'], 'nextCursor': 'next'}, {'data': ['b'], 'nextCursor': None}])
        self.assertEqual(await native.loaded_threads(), frozenset({'a', 'b'}))
        self.assertEqual(native.rpc.request.await_count, 2)
        self.assertEqual(native.rpc.request.await_args.args[1], {'limit': 100, 'cursor': 'next'})

    async def test_positive_early_match_cannot_hide_later_duplicate_or_invalid_page(self):
        for last in ({'data': ['a']}, {'data': [None]}, {'data': [] , 'nextCursor': 'next'}):
            native = self.connection([{'data': ['a'], 'nextCursor': 'next'}, last])
            with self.subTest(last=last), self.assertRaises(ValueError):
                await native.is_loaded('a')

    async def test_invalid_pages_and_identity_lengths_are_rejected(self):
        for page in ({}, {'data': ['']}, {'data': ['x' * 257]}, {'data': ['a', 'a']}, {'data': [True]},
                     {'data': [str(i) for i in range(101)]}):
            with self.subTest(page=page), self.assertRaises(ValueError):
                await self.connection([page]).loaded_threads()

    async def test_page_bound_refuses_incomplete_runtime_snapshot(self):
        pages = [{'data': [str(i)], 'nextCursor': str(i)} for i in range(10)]
        with self.assertRaisesRegex(ValueError, 'bound'):
            await self.connection(pages).loaded_threads()

    async def test_not_loaded_thread_is_never_resumed_for_subscription(self):
        root = Path(__file__).resolve().parents[1]
        native = self.connection([])
        native.inspect = AsyncMock(return_value={'id': 'a', 'cwd': str(root), 'status': {'type': 'notLoaded'}})
        with self.assertRaises(ValueError):
            await native.observe_loaded('a', root)
        native.rpc.request.assert_not_called()


class BindingIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.binding = SessionBinding(None, self.root, (1, 2), 'thread-a', 'native-root')

    def test_host_title_and_origin_never_enter_native_stable_identity(self):
        host = TerminalEndpoint('terminal', ProcessIdentity(123, (1, 2), '/fixture/codex', 123), 'codex_candidate')
        other = replace(self.binding, endpoint=host)
        self.assertEqual(binding_key(self.binding), binding_key(other))
        self.assertNotEqual(binding_key(other), legacy_binding_key(host, other))

    def test_fork_shared_native_session_root_keeps_distinct_thread_identity(self):
        self.assertNotEqual(binding_key(self.binding), binding_key(replace(self.binding, thread_id='fork-a')))
        self.assertNotEqual(binding_key(self.binding), binding_key(replace(self.binding, runtime_identity=(1, 3))))
        self.assertNotEqual(binding_key(self.binding), binding_key(replace(self.binding, native_session_id='new-root')))

    async def test_invalid_native_identity_never_queries_agent(self):
        agent = SimpleNamespace(runtime_identity=(1, 2), inspect=AsyncMock())
        for value in (replace(self.binding, thread_id=''), replace(self.binding, thread_id=123),
                      replace(self.binding, native_session_id=None), replace(self.binding, runtime_identity=(True, 2)),
                      replace(self.binding, runtime_identity=())):
            with self.subTest(value=value), self.assertRaises(SessionUnbound):
                await verify_binding(value, None, agent)
        agent.inspect.assert_not_called()

    async def test_relative_or_disappeared_project_identity_is_rejected(self):
        agent = SimpleNamespace(runtime_identity=(1, 2), inspect=AsyncMock(return_value={
            'id': 'thread-a', 'sessionId': 'native-root', 'cwd': '.', 'status': {'type': 'idle'}}))
        with self.assertRaises(SessionUnbound):
            await verify_binding(self.binding, None, agent)
