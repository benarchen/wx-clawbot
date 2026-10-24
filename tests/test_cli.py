import unittest
from unittest.mock import patch

from wx_clawbot.cli import doctor


class DoctorTests(unittest.TestCase):
    @patch("wx_clawbot.cli.shutil.which", return_value=None)
    def test_missing_codex_is_failure(self, _which):
        report, ok = doctor()
        self.assertFalse(ok)
        self.assertIsNone(report["codex_version"])
        self.assertNotIn("path", report)
