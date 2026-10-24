"""Local diagnostics. No terminal input, model calls, or WeChat traffic."""

import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path

from . import __version__
from .config import ConfigError, load_projects


def doctor(config: Path | None = None) -> tuple[dict, bool]:
    codex = shutil.which("codex")
    version = None
    if codex:
        try:
            result = subprocess.run([codex, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip().startswith("codex-cli "):
                version = result.stdout.strip().splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            pass
    report = {"version": __version__, "python": platform.python_version(),
              "codex_version": version, "config": "not_checked"}
    ok = version is not None
    if config is not None:
        try:
            report["project_count"] = len(load_projects(config))
            report["config"] = "valid"
        except ConfigError as exc:
            report["config"] = "invalid"
            report["error"] = str(exc)
            ok = False
    return report, ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wx-clawbot")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", help="只读核对本机版本与项目配置")
    check.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    report, ok = doctor(args.config)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1
