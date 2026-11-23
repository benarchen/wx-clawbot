import unittest
from unittest.mock import patch

from wx_clawbot.cli import doctor
from wx_clawbot.cli import probe_host
import subprocess


class DoctorTests(unittest.TestCase):
    @patch("wx_clawbot.cli.shutil.which", return_value="/fixture/command")
    @patch("wx_clawbot.cli.subprocess.run")
    def test_verified_daemon_need_not_match_cli_version(self, run, _which):
        run.side_effect = [subprocess.CompletedProcess([], 0, "codex-cli 0.164.0"),
                           subprocess.CompletedProcess([], 0, '{"status":"running","cliVersion":"0.164.0","appServerVersion":"0.165.0"}')]
        report, ok = doctor()
        self.assertTrue(ok)
        self.assertTrue(report["runtime"]["verified_schema"])
        self.assertEqual(report["runtime"]["appServerVersion"], "0.165.0")

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

    @patch("wx_clawbot.cli.shutil.which")
    def test_default_agent_antigravity_doctor_passes_without_codex(self, which):
        import json, tempfile
        from pathlib import Path
        which.side_effect = lambda name: "/usr/bin/git" if name == "git" else None
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            proj.mkdir()
            cfg = Path(tmp) / "config.json"
            cfg.write_text(json.dumps({"default_agent": "agy", "projects": [{"alias": "p1", "root": str(proj)}]}))
            with patch("wx_clawbot.cli.doctor_antigravity", return_value={"status": "available", "version": "1.5.14"}):
                report, ok = doctor(cfg)
            self.assertTrue(ok)
            self.assertEqual(report["default_agent"], "antigravity")
            self.assertEqual(report["antigravity"]["status"], "available")
            with patch("wx_clawbot.cli.doctor_antigravity", return_value={"status": "not_installed", "version": None}):
                _, ok_missing = doctor(cfg)
            self.assertFalse(ok_missing)
