import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.config import Project
from wx_clawbot.hosts.discovery import TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity
from wx_clawbot.sessions import SessionUnbound


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "w05-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = Project("fixture", self.root)
        self.endpoint = TerminalEndpoint("terminal-one", ProcessIdentity(123, (1, 2), "/example/codex", 101), "codex_candidate")
        self.thread = {"id": "thread-one", "sessionId": "session-one", "cwd": str(self.root),
                       "status": {"type": "idle"}, "name": "Architecture review"}
        self.directory = SimpleNamespace(discover=AsyncMock(return_value=[self.endpoint]),
                        cwd=AsyncMock(return_value=self.root), validate=AsyncMock(return_value=True),
                        current_thread_id=AsyncMock(return_value="thread-one"))
        self.agent = SimpleNamespace(runtime_identity=(1, 2),
                        list_project_threads=AsyncMock(return_value={"data": [self.thread]}),
                        inspect=AsyncMock(return_value=self.thread))
        self.catalog = SessionCatalog((self.project,), self.directory, self.agent)

    async def test_verified_native_identity_is_stable_across_refresh_and_filtering(self):
        first = (await self.catalog.discover())[0]
        second = (await self.catalog.discover("architecture"))[0]
        self.assertEqual(first.target.session_id, second.target.session_id)
        self.assertEqual((await self.catalog.require(first.target)).binding.thread_id, "thread-one")

    async def test_unregistered_process_directory_never_triggers_screen_or_native_reads(self):
        self.directory.cwd.return_value = self.root.parent
        self.assertEqual(await self.catalog.discover(), ())
        self.directory.current_thread_id.assert_not_called()
        self.agent.list_project_threads.assert_not_called()
        self.agent.inspect.assert_not_called()

    async def test_missing_footer_is_reported_unverified_and_not_guessed_from_one_thread(self):
        self.directory.current_thread_id.return_value = None
        self.assertEqual(await self.catalog.discover(), ())
        self.assertEqual(self.catalog.unverified[0]["reason"], "current_thread_id_missing")
        self.agent.inspect.assert_not_called()

    async def test_same_process_new_conversation_preserves_verified_old_binding(self):
        original = (await self.catalog.discover())[0]
        new = {**self.thread, "id": "thread-two", "sessionId": "session-two"}
        self.agent.list_project_threads.return_value = {"data": [self.thread, new]}
        self.directory.current_thread_id.return_value = "thread-two"
        self.agent.inspect.side_effect = lambda identity: self.thread if identity == "thread-one" else new
        sessions = await self.catalog.discover()
        current = next(s for s in sessions if s.binding.thread_id == "thread-two")
        self.assertEqual(current.binding.thread_id, "thread-two")
        self.assertNotEqual(current.target.session_id, original.target.session_id)
        self.assertEqual((await self.catalog.require(original.target)), original)
        self.assertEqual({s.binding.thread_id for s in sessions}, {"thread-one", "thread-two"})

    async def test_known_thread_remains_discoverable_when_footer_is_hidden(self):
        original = (await self.catalog.discover())[0]
        self.directory.current_thread_id.return_value = None
        self.assertEqual(await self.catalog.discover(), (original,))
        self.assertEqual(await self.catalog.require(original.target), original)

    async def test_launch_registration_during_retained_binding_check_does_not_break_discovery(self):
        original = (await self.catalog.discover())[0]
        self.directory.current_thread_id.return_value = None
        registered = False

        async def inspect(identity):
            nonlocal registered
            if not registered:
                registered = True
                other = replace(original.binding, thread_id="registered-during-query", native_session_id="other-session")
                self.catalog.remember_verified(other, managed=True)
            return self.thread

        self.agent.inspect.side_effect = inspect
        self.assertEqual(await self.catalog.discover(), (original,))
        self.assertEqual(await self.catalog.require(original.target), original)

    async def test_known_binding_is_removed_on_process_exit_runtime_change_or_unload(self):
        for failure in ("process", "runtime", "unload", "session"):
            self.directory.discover.return_value = [self.endpoint]
            self.directory.validate.return_value = True
            self.directory.current_thread_id.return_value = "thread-one"
            self.agent.runtime_identity = (1, 2)
            self.thread.update(sessionId="session-one", status={"type": "idle"})
            self.catalog = SessionCatalog((self.project,), self.directory, self.agent)
            original = (await self.catalog.discover())[0]
            self.directory.current_thread_id.return_value = None
            if failure == "process":
                self.directory.discover.return_value = []
                self.directory.validate.return_value = False
            elif failure == "runtime":
                self.agent.runtime_identity = (2, 3)
            elif failure == "unload":
                self.thread["status"] = {"type": "notLoaded"}
            else:
                self.thread["sessionId"] = "changed-session"
            with self.subTest(failure=failure):
                self.assertEqual(await self.catalog.discover(), ())
                with self.assertRaises(SessionUnbound):
                    await self.catalog.require(original.target)

    async def test_failed_refresh_keeps_previous_catalog_but_stale_endpoint_cannot_route(self):
        original = (await self.catalog.discover())[0]
        self.agent.list_project_threads.return_value = {"data": [self.thread], "nextCursor": "more"}
        with self.assertRaises(ValueError):
            await self.catalog.discover()
        self.assertIn(original.target.session_id, self.catalog.sessions)
        self.directory.validate.return_value = False
        with self.assertRaises(SessionUnbound):
            await self.catalog.require(original.target)

    async def test_same_directory_two_terminals_are_joined_by_current_uuid_not_list_order(self):
        second = TerminalEndpoint("terminal-two", ProcessIdentity(124, (1, 3), "/example/codex", 102), "codex_candidate")
        other = {**self.thread, "id": "thread-two", "sessionId": "session-two"}
        self.directory.discover.return_value = [self.endpoint, second]
        self.directory.current_thread_id.side_effect = lambda endpoint: "thread-one" if endpoint == self.endpoint else "thread-two"
        self.agent.list_project_threads.return_value = {"data": [other, self.thread]}
        self.agent.inspect.side_effect = lambda identity: self.thread if identity == "thread-one" else other
        sessions = await self.catalog.discover()
        self.assertEqual({s.binding.endpoint.terminal_id: s.binding.thread_id for s in sessions},
                         {"terminal-one": "thread-one", "terminal-two": "thread-two"})
