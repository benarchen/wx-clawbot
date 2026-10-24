import os
import sys
import unittest
from pathlib import Path

from wx_clawbot.hosts.process import read_process


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
