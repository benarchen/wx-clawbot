"""Read-only diagnostics, explicit binding and an owner-only foreground bridge."""

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
    for name in ["iterm2", "protobuf", "websockets", "segno"]:
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
    migration = commands.add_parser("migrate-state", help="默认只读检查本项目账本升级计划")
    migration.add_argument("--state-dir", type=Path,
                            default=Path.home() / "Library" / "Application Support" / "wx-clawbot")
    migration.add_argument("--apply", action="store_true", help="显式执行已授权升级；先验证备份，要求前台已停止")
    maintenance = commands.add_parser("maintain-state", help="默认只读查看程序自有已结记录的保留期计划")
    maintenance.add_argument("--state-dir", type=Path,
                            default=Path.home() / "Library" / "Application Support" / "wx-clawbot")
    maintenance.add_argument("--apply", action="store_true", help="显式授权清理七天正文／三十天已结摘要，要求前台停止")
    run = commands.add_parser("serve", help="前台运行本人微信与已注册项目桥接")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--socket", required=True, type=Path)
    run.add_argument("--codex-executable", required=True, type=Path, help="已核验的原生 Codex 可执行文件")
    run.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    run.add_argument("--state-dir", type=Path,
                     default=Path.home() / "Library" / "Application Support" / "wx-clawbot")
    wechat = commands.add_parser("wechat", help="独立微信登录与本人文本联调")
    actions = wechat.add_subparsers(dest="wechat_action", required=True)
    login = actions.add_parser("login", help="生成本项目二维码并前台等待，不发送消息")
    login.add_argument("--wait", type=int, default=300)
    login.add_argument("--fresh", action="store_true", help="明确刷新已过期二维码")
    login.add_argument("--open", action="store_true", help="用默认浏览器打开本地二维码页")
    login.add_argument("--verify-code-stdin", action="store_true", help="从管道读取手机配对码")
    bind = actions.add_parser("bind", help="扫码后明确确认本人测试账号")
    bind.add_argument("--confirm-self", required=True, action="store_true")
    bind.add_argument("--owner-fingerprint", required=True)
    echo = actions.add_parser("echo", help="仅回复本人发来的指定测试口令，不执行 Agent")
    echo.add_argument("--challenge", required=True)
    echo.add_argument("--count", type=int, default=2)
    echo.add_argument("--timeout", type=int, default=180)
    for action in (login, bind, echo):
        action.add_argument("--state-dir", type=Path,
                            default=Path.home() / "Library" / "Application Support" / "wx-clawbot")
    args = parser.parse_args(argv)
    if args.command in {"migrate-state", "maintain-state"}:
        from . import schema
        from .channels.private import load_credentials
        try:
            credentials = load_credentials(args.state_dir / "credentials.json")
            if args.command == "maintain-state":
                from .retention import maintain
                report = maintain(args.state_dir, credentials, apply=args.apply)
            else:
                report = schema.upgrade(args.state_dir, credentials) if args.apply else schema.inspect(args.state_dir, credentials)
        except Exception as exc:
            print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, ensure_ascii=False))
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve":
        from .service import serve
        from .schema import UpgradeRequired

        def emit(value):
            print(json.dumps(value, ensure_ascii=False), flush=True)

        try:
            asyncio.run(serve(load_projects(args.config), args.state_dir, args.socket,
                              args.codex_executable, args.codex_home, emit=emit))
        except KeyboardInterrupt:
            emit({"status": "stopped", "native_terminals_preserved": True})
            return 130
        except UpgradeRequired:
            emit({"status": "upgrade_required", "message": "请先运行 migrate-state 只读查看计划；已有账本不会自动升级。"})
            return 2
        except Exception as exc:
            emit({"status": "failed", "error_type": type(exc).__name__,
                  "message": "前台桥接已停止；原生任务可能仍在执行，未知任务不会自动重放。"})
            return 1
        return 0
    if args.command == "wechat":
        return wechat_command(args)
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


def wechat_command(args) -> int:
    from .channels.diagnostics import echo
    from .channels.login import confirm_owner, login

    def emit(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)

    try:
        if args.wechat_action == "login":
            code = None
            if args.verify_code_stdin:
                if sys.stdin.isatty():
                    raise ValueError("Pairing code must arrive through a private pipe")
                code = sys.stdin.read(32).strip()
            report = asyncio.run(login(args.state_dir, wait=args.wait, fresh=args.fresh,
                                       open_page=args.open, verify_code=code))
        elif args.wechat_action == "bind":
            report = confirm_owner(args.state_dir, args.owner_fingerprint)
        else:
            report = asyncio.run(echo(args.state_dir, challenge=args.challenge,
                                      count=args.count, timeout=args.timeout, emit=emit))
        emit(report)
        return 0 if report.get("status") in {"connected", "owner_confirmed", "awaiting_owner_confirmation",
                                             "server_accepted_test_replies", "waiting", "need_verifycode"} else 1
    except KeyboardInterrupt:
        emit({"status": "stopped", "message": "前台联调已停止；未知投递不自动重试。"})
        return 130
    except Exception as exc:
        report = {"status": "failed", "error_type": type(exc).__name__}
        if getattr(exc, "category", None) in {"tls", "dns", "timeout", "network"}:
            report["category"] = exc.category
        emit(report)
        return 1
