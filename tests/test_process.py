import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wx_clawbot.hosts.process import ProcessIdentity, read_process, read_process_directory


@unittest.skipUnless(sys.platform == "darwin", "macOS native identity")
class ProcessTests(unittest.TestCase):
    def test_own_process_native_identity_is_stable_and_precise(self):
        first = read_process(os.getpid())
        second = read_process(os.getpid())
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first.pid, os.getpid())
        self.assertGreater(first.started[0], 0)
        self.assertTrue(0 <= first.started[1] < 1_000_000)
        self.assertTrue(Path(first.executable).is_absolute())

    def test_invalid_ids_are_rejected_without_process_access(self):
        for pid in (True, 0, -1, 2**31, "1", None):
            with self.subTest(pid=pid):
                self.assertIsNone(read_process(pid))

    def test_own_process_directory_is_read_without_arguments_or_environment(self):
        self.assertEqual(read_process_directory(read_process(os.getpid())), Path.cwd().resolve())

    def test_directory_lookup_refuses_pid_reuse_before_spawning_lsof(self):
        identity = ProcessIdentity(123, (1, 2), "/example/codex", 101)
        with patch("wx_clawbot.hosts.process.read_process", return_value=None), \
             patch("wx_clawbot.hosts.process.subprocess.run") as process:
            self.assertIsNone(read_process_directory(identity))
            process.assert_not_called()

    def test_directory_lookup_refuses_generation_change_during_read(self):
        identity = ProcessIdentity(123, (1, 2), "/example/codex", 101)
        output = b"p123\0\nfcwd\0n" + os.fsencode(Path.cwd()) + b"\0\n"
        with patch("wx_clawbot.hosts.process.read_process", side_effect=[identity, None]), \
             patch("wx_clawbot.hosts.process.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=output)):
            self.assertIsNone(read_process_directory(identity))
