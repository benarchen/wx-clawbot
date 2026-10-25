import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.hosts.discovery import TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity
from wx_clawbot.sessions import SessionBinding, SessionUnbound, verify_binding


class BindingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "binding-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        endpoint = TerminalEndpoint("fixture-terminal", ProcessIdentity(123, (1, 2), "/example/codex", 101), "codex_candidate")
        self.binding = SessionBinding(endpoint, self.project, (1, 2), "fixture-thread", "fixture-session")
        self.directory = SimpleNamespace(validate=AsyncMock(return_value=True),
                                         current_thread_id=AsyncMock(return_value="fixture-thread"))
        self.thread = {"id": "fixture-thread", "sessionId": "fixture-session",
                       "cwd": str(self.project), "status": {"type": "idle"}}
        self.agent = SimpleNamespace(runtime_identity=(1, 2), inspect=AsyncMock(return_value=self.thread))

    async def test_current_pairing_is_valid(self):
        self.assertEqual(await verify_binding(self.binding, self.directory, self.agent), self.thread)

    async def test_stale_terminal_stops_before_native_lookup(self):
        self.directory.validate.return_value = False
        with self.assertRaises(SessionUnbound):
            await verify_binding(self.binding, self.directory, self.agent)
        self.agent.inspect.assert_not_called()

    async def test_runtime_session_and_project_changes_are_rejected(self):
        for runtime, session, cwd, state in [((2, 3), "fixture-session", str(self.project), "idle"),
                                             ((1, 2), "different-session", str(self.project), "idle"),
                                             ((1, 2), "fixture-session", "/example/elsewhere", "idle"),
                                             ((1, 2), "fixture-session", str(self.project), "notLoaded")]:
            self.agent.runtime_identity = runtime
            self.thread.update(sessionId=session, cwd=cwd, status={"type": state})
            with self.subTest(state=state, session=session, runtime=runtime), self.assertRaises(SessionUnbound):
                await verify_binding(self.binding, self.directory, self.agent)

    async def test_same_process_with_another_visible_thread_is_not_the_original_binding(self):
        self.directory.current_thread_id.return_value = "new-desktop-thread"
        with self.assertRaises(SessionUnbound):
            await verify_binding(self.binding, self.directory, self.agent)
        self.agent.inspect.assert_not_called()

    async def test_missing_displayed_identity_is_not_inferred_from_loaded_thread(self):
        self.directory.current_thread_id.return_value = None
        with self.assertRaises(SessionUnbound):
            await verify_binding(self.binding, self.directory, self.agent)
        self.agent.inspect.assert_not_called()

    async def test_system_error_requires_positive_native_membership_and_direct_input(self):
        self.thread.update(status={"type": "systemError"}, canAcceptDirectInput=True)
        self.agent.is_loaded = AsyncMock(return_value=False)
        with self.assertRaises(SessionUnbound):
            await verify_binding(self.binding, self.directory, self.agent)
        self.agent.is_loaded.return_value = True
        self.assertEqual(await verify_binding(self.binding, self.directory, self.agent), self.thread)
        self.thread["canAcceptDirectInput"] = False
        with self.assertRaises(SessionUnbound):
            await verify_binding(self.binding, self.directory, self.agent)
