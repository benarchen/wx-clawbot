import unittest
from unittest.mock import AsyncMock, patch

from wx_clawbot.hosts.discovery import ProcessIdentity, inspect_terminal


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_shell_is_not_an_agent(self):
        session = AsyncMock()
        session.session_id = "fixture-terminal"
        session.async_get_variable.side_effect = [100, "/dev/ttys001"]
        identity = ProcessIdentity(100, "fixture-start", "/bin/zsh", "ttys001")
        with patch("wx_clawbot.hosts.discovery.read_process", return_value=identity):
            endpoint = await inspect_terminal(session)
        self.assertEqual(endpoint.classification, "ordinary_terminal")

    async def test_wrong_tty_never_becomes_codex_candidate(self):
        session = AsyncMock()
        session.session_id = "fixture-terminal"
        session.async_get_variable.side_effect = [100, "/dev/ttys001"]
        identity = ProcessIdentity(100, "fixture-start", "/opt/bin/codex", "ttys002")
        with patch("wx_clawbot.hosts.discovery.read_process", return_value=identity):
            endpoint = await inspect_terminal(session)
        self.assertEqual(endpoint.classification, "unverified_process")

    async def test_missing_pid_is_unavailable(self):
        session = AsyncMock()
        session.session_id = "fixture-terminal"
        session.async_get_variable.side_effect = ["", "/dev/ttys001"]
        self.assertEqual((await inspect_terminal(session)).classification, "exited_or_unavailable")
