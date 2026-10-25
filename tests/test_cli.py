import unittest
from unittest.mock import patch

from wx_clawbot.cli import doctor
from wx_clawbot.cli import probe_host
import subprocess


class DoctorTests(unittest.TestCase):
    @patch("wx_clawbot.cli.shutil.which", return_value="/fixture/command")
    @patch("wx_clawbot.cli.subprocess.run")
    def test_malformed_or_unverified_runtime_is_reported_without_sensitive_fields(self, run, _which):
        for raw in ('[]', '{"status":"running","cliVersion":"private token","appServerVersion":"9.9.9","managedCodexPath":"private path"}'):
            run.side_effect = [subprocess.CompletedProcess([], 0, "codex-cli 0.163.0"), subprocess.CompletedProcess([], 0, raw)]
            report, ok = doctor()
            self.assertFalse(ok)
            self.assertNotIn("private", str(report))

    @patch("wx_clawbot.cli.shutil.which", return_value=None)
    def test_missing_codex_is_failure(self, _which):
        report, ok = doctor()
        self.assertFalse(ok)
        self.assertIsNone(report["codex_version"])
        self.assertNotIn("path", report)

    @patch("wx_clawbot.cli.subprocess.run", side_effect=subprocess.TimeoutExpired("probe", 20))
    def test_host_auth_timeout_is_failure(self, _run):
        self.assertEqual(probe_host()["status"], "unavailable")

    @patch("wx_clawbot.cli.subprocess.run")
    def test_host_crash_does_not_leak_stderr(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "private token")
        result = probe_host()
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("private", str(result))
