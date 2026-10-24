import shlex
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from wx_clawbot.hosts.launch import native_tui_command


class LaunchTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "launch-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_node_wrapper_rejected_before_visible_launch(self):
        executable = self.root / "codex"
        executable.write_text("#!/usr/bin/env node\n")
        executable.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "native macOS"):
            native_tui_command(executable, self.root, self.root)

    def test_paths_cannot_expand_shell_commands(self):
        executable = self.root / "codex ' $(touch NEVER)"
        executable.write_bytes(b"\xcf\xfa\xed\xfe")
        executable.chmod(0o700)
        project = self.root / 'project $(touch NEVER) "'
        project.mkdir()
        home = self.root / "runtime ' $HOME"
        home.mkdir()
        with patch.dict("os.environ", {"PATH": "/test/bin:/usr/bin:/bin"}):
            command = native_tui_command(executable, home, project)
        self.assertEqual(shlex.split(command), ["/usr/bin/env", "CODEX_HOME=" + str(home),
                                               "PATH=/test/bin:/usr/bin:/bin", str(executable),
                                               "--cd", str(project)])
        self.assertFalse((self.root / "NEVER").exists())
