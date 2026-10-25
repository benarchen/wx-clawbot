"""Explicit foreground CLI acceptance in one new owned iTerm2 terminal.

No task injection, messages, process signals, launchd registration or native stops.
Requires a stopped bridge and an existing confirmed owner runtime directory.
"""

import argparse
import asyncio
import hashlib
import json
import shlex
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from wx_clawbot.channels.private import private_directory, write_json
from wx_clawbot.config import load_projects
from wx_clawbot.hosts.connection import close_connection
from wx_clawbot.hosts.discovery import ItermDirectory
from wx_clawbot.hosts.process import read_process, read_process_directory
from wx_clawbot.operations import consumer_busy, status


async def cli(*args):
    def invoke():
        result = subprocess.run([sys.executable, "-m", "wx_clawbot", *args], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError("Formal CLI returned failure")
        return json.loads(result.stdout)
    return await asyncio.to_thread(invoke)


async def wait_status(root, expected):
    async with asyncio.timeout(45):
        while True:
            report = status(root)
            if report["status"] == expected:
                return report
            await asyncio.sleep(0.25)


async def run(args):
    import iterm2
    if not args.confirm_owned_test_terminals:
        raise ValueError("Explicit dedicated-terminal acceptance required")
    root = private_directory(args.report_dir.resolve())
    report_path = root / "case.json"
    if report_path.exists():
        raise ValueError("Existing integration case must not be repeated")
    fixture = args.fixture_root.resolve(strict=True)
    projects = load_projects(args.config)
    if len(projects) != 2 or any(not p.root.is_relative_to(fixture) for p in projects):
        raise ValueError("Only the two dedicated fixture projects are eligible")
    if consumer_busy(args.state_dir):
        raise ValueError("Existing foreground must be stopped before acceptance")
    baseline = status(args.state_dir)
    config_path = args.codex_home / "config.toml"
    config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
    host = await iterm2.Connection.async_create()
    case = {"phase": "prepared", "config_sha256": config_sha, "cycles": []}
    write_json(report_path, case)
    try:
        directory = ItermDirectory(host)
        preserved = []
        for endpoint in await directory.discover():
            if endpoint.classification == "codex_candidate":
                cwd = await asyncio.to_thread(read_process_directory, endpoint.process)
                if cwd and cwd.is_relative_to(fixture):
                    preserved.append(json.loads(json.dumps(asdict(endpoint.process))))
        if len(preserved) < 2:
            raise ValueError("Expected dedicated original native terminals")
        case.update(phase="visible_start_intent", native_processes=preserved)
        write_json(report_path, case, replace=True)
        command = shlex.join([str(Path(sys.executable).absolute().parent / "wx-clawbot"), "serve",
                             "--config", str(args.config.resolve()), "--state-dir", str(args.state_dir.resolve()),
                             "--codex-home", str(args.codex_home.resolve())])
        shell = "cd " + shlex.quote(str(Path.cwd())) + " && " + command + "; exec /bin/zsh -l"
        window = await iterm2.Window.async_create(host, command=shlex.join(["/bin/zsh", "-l", "-c", shell]))
        if not window or not window.current_tab or not window.current_tab.current_session:
            raise RuntimeError("Visible CLI terminal unavailable; do not create another automatically")
        session = window.current_tab.current_session
        case.update(terminal_id=session.session_id, window_id=window.window_id)
        write_json(report_path, case, replace=True)
        for index in range(2):
            if index:
                # Only this explicitly created test terminal receives CLI input.
                await asyncio.sleep(1)
                await session.async_send_text(command + "\n", suppress_broadcast=True)
            running = await wait_status(args.state_dir, "running")
            case["phase"] = "running"
            write_json(report_path, case, replace=True)
            if running["tasks"] != baseline["tasks"]:
                raise RuntimeError("Unexpected task-state change; inspect without replay")
            doctor = await cli("doctor", "--config", str(args.config), "--state-dir", str(args.state_dir))
            if doctor["state"]["status"] != "running":
                raise RuntimeError("Doctor did not observe formal foreground")
            stopped = await cli("stop", "--state-dir", str(args.state_dir))
            if stopped["status"] != "stop_requested":
                raise RuntimeError("Stop was not accepted for this instance")
            final = await wait_status(args.state_dir, "stopped")
            case["phase"] = "stopped_verifying"
            write_json(report_path, case, replace=True)
            if final["tasks"] != baseline["tasks"]:
                raise RuntimeError("Stopping changed task outcomes")
            for record in preserved:
                current = read_process(record["pid"])
                if current is None or json.loads(json.dumps(asdict(current))) != record:
                    raise RuntimeError("An original native process changed")
            if hashlib.sha256(config_path.read_bytes()).hexdigest() != config_sha:
                raise RuntimeError("Global configuration changed")
            case["cycles"].append({"index": index + 1, "running": True, "doctor": True,
                                   "controlled_stop": True, "native_processes_preserved": len(preserved),
                                   "tasks_unchanged": True, "config_unchanged": True})
            write_json(report_path, case, replace=True)
        case.update(phase="verified", messages_sent_by_test=0, native_submission_calls=0,
                    launchd_registered=False, final_status="stopped")
        write_json(report_path, case, replace=True)
        print(json.dumps({key: case[key] for key in ("phase", "cycles", "messages_sent_by_test", "native_submission_calls", "launchd_registered", "final_status")}))
    finally:
        await close_connection(host)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / "Library" / "Application Support" / "wx-clawbot")
    parser.add_argument("--confirm-owned-test-terminals", action="store_true")
    asyncio.run(run(parser.parse_args()))
