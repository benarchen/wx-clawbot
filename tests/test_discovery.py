import unittest
from unittest.mock import AsyncMock, patch

from wx_clawbot.hosts.discovery import ItermDirectory, TerminalEndpoint, inspect_terminal
from wx_clawbot.hosts.process import ProcessIdentity


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_shell_is_not_an_agent(self):
        session = AsyncMock()
        session.session_id = "fixture-terminal"
        session.async_get_variable.side_effect = [100, "/dev/ttys001"]
        identity = ProcessIdentity(100, (1, 100), "/bin/zsh", 101)
        with patch("wx_clawbot.hosts.discovery.read_process", return_value=identity), \
                patch("wx_clawbot.hosts.discovery.tty_device", return_value=101):
            endpoint = await inspect_terminal(session)
        self.assertEqual(endpoint.classification, "ordinary_terminal")

    async def test_wrong_tty_never_becomes_codex_candidate(self):
        session = AsyncMock()
        session.session_id = "fixture-terminal"
        session.async_get_variable.side_effect = [100, "/dev/ttys001"]
        identity = ProcessIdentity(100, (1, 100), "/opt/bin/codex", 102)
        with patch("wx_clawbot.hosts.discovery.read_process", return_value=identity), \
                patch("wx_clawbot.hosts.discovery.tty_device", return_value=101):
            endpoint = await inspect_terminal(session)
        self.assertEqual(endpoint.classification, "unverified_process")

    async def test_missing_pid_is_unavailable(self):
        session = AsyncMock()
        session.session_id = "fixture-terminal"
        session.async_get_variable.side_effect = ["", "/dev/ttys001"]
        self.assertEqual((await inspect_terminal(session)).classification, "exited_or_unavailable")

    async def test_pid_reuse_within_same_second_invalidates_endpoint(self):
        old = ProcessIdentity(100, (1, 100), "/opt/bin/codex", 101)
        new = ProcessIdentity(100, (1, 101), "/opt/bin/codex", 101)
        endpoint = TerminalEndpoint("fixture-terminal", old, "codex_candidate")
        directory = ItermDirectory(None)
        from types import SimpleNamespace
        app = SimpleNamespace(get_session_by_id=lambda _: object())
        with patch('iterm2.async_get_app', new=AsyncMock(return_value=app)), \
                patch('wx_clawbot.hosts.discovery.inspect_terminal', new=AsyncMock(return_value=
                    TerminalEndpoint('fixture-terminal', new, 'codex_candidate'))):
            self.assertFalse(await directory.validate(endpoint))

    async def test_exited_terminal_invalidates_endpoint(self):
        endpoint = TerminalEndpoint("fixture-terminal",
                                    ProcessIdentity(100, (1, 100), "/opt/bin/codex", 101),
                                    "codex_candidate")
        directory = ItermDirectory(None)
        from types import SimpleNamespace
        app = SimpleNamespace(get_session_by_id=lambda _: None)
        with patch('iterm2.async_get_app', new=AsyncMock(return_value=app)):
            self.assertFalse(await directory.validate(endpoint))

    async def test_invalid_host_pid_does_not_inspect_another_process(self):
        for value in (True, 100.5, float("inf"), "100.5", "invalid"):
            session = AsyncMock()
            session.session_id = "fixture-terminal"
            session.async_get_variable.side_effect = [value, "/dev/ttys001"]
            with self.subTest(pid=value), \
                    patch("wx_clawbot.hosts.discovery.read_process") as read:
                endpoint = await inspect_terminal(session)
                read.assert_not_called()
                self.assertEqual(endpoint.classification, "exited_or_unavailable")
