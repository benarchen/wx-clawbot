"""Discover only the existing managed daemon through the installed official CLI."""

import json
import os
import shutil
import subprocess
from pathlib import Path


def discover_runtime(codex_home: Path):
    codex = shutil.which("codex")
    if codex is None:
        raise ValueError("Codex CLI unavailable")
    env = dict(os.environ, CODEX_HOME=str(codex_home.expanduser().resolve(strict=True)))
    result = subprocess.run([codex, "app-server", "daemon", "version"], env=env,
                            capture_output=True, text=True, timeout=5)
    if result.returncode or len(result.stdout) > 65536:
        raise ValueError("Existing daemon cannot be inspected")
    report = json.loads(result.stdout)
    if not isinstance(report, dict) or report.get("status") != "running":
        raise ValueError("Existing daemon is not running")
    for name in ("socketPath", "managedCodexPath"):
        if not isinstance(report.get(name), str) or not Path(report[name]).is_absolute():
            raise ValueError("Daemon metadata lacks an absolute endpoint or executable")
    return Path(report["socketPath"]), Path(report["managedCodexPath"])
