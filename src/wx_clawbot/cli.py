"""Local diagnostics. No terminal input, model calls, or WeChat traffic."""

import argparse
import asyncio
import json
import platform
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

from . import __version__
from .config import ConfigError, load_projects


def probe_host() -> dict:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "wx_clawbot.hosts.iterm2"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "error_type": "AuthenticationTimeout"}
    except (OSError, ValueError):
        pass
    return {"status": "failed", "error_type": "ProbeFailed"}


def doctor(config: Path | None = None, *, iterm: bool = False) -> tuple[dict, bool]:
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
    dependencies = {}
    for name in ["iterm2", "protobuf", "websockets"]:
        try:
            dependencies[name] = package_version(name)
        except PackageNotFoundError:
            dependencies[name] = None
            ok = False
    report["dependencies"] = dependencies
    if codex:
        try:
            result = subprocess.run([codex, "app-server", "daemon", "version"],
                                    capture_output=True, text=True, timeout=5)
            runtime = json.loads(result.stdout) if result.returncode == 0 else {}
            report["runtime"] = {key: runtime.get(key) for key in
                                 ("status", "cliVersion", "appServerVersion")}
            if runtime.get("status") != "running":
                ok = False
        except (OSError, ValueError, subprocess.TimeoutExpired):
            report["runtime"] = {"status": "unavailable"}
            ok = False
    if iterm:
        report["iterm2"] = probe_host()
        ok = ok and report["iterm2"].get("status") == "connected"
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
    check.add_argument("--iterm2", action="store_true", help="显式测试 iTerm2 API，可能触发脚本授权")
    native = commands.add_parser("native-probe", help="只读测试既有 Codex Unix WebSocket 握手")
    native.add_argument("--socket", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "native-probe":
        from .agents.codex import CodexConnection

        async def probe_native():
            connection = await CodexConnection.connect(args.socket)
            try:
                return {"status": "connected", "server_version": connection.server_version}
            finally:
                await connection.close()

        try:
            report = asyncio.run(probe_native())
            ok = True
        except Exception as exc:
            report = {"status": "failed", "error_type": type(exc).__name__}
            ok = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    report, ok = doctor(args.config, iterm=args.iterm2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1
