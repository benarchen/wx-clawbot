"""Fixed visible-terminal entry point; user content is read privately, never evaluated."""

import argparse
import os
import shlex
from pathlib import Path

from .channels.private import write_json
from .config import Project, resolve_directory
from .hosts.launch import native_tui_command
from .hosts.process import read_process
from .hosts.visible import LaunchError, LaunchRegistry


def launch_argv(record):
    project = Project(record["project_alias"], Path(record["project_root"]).resolve(strict=True))
    cwd = resolve_directory(project, record["cwd"])
    command = native_tui_command(Path(record["executable"]), Path(record["codex_home"]), cwd,
                                 path=record["path"])
    prompt = ("WX-LAUNCH-" + record["launch_id"] + "\n"
              "这是可见会话启动核验。仅检查当前目录适用的 AGENTS.md，并回复上面的完整标记；"
              "不修改文件，不运行测试，不提交。")
    return [*shlex.split(command), prompt]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wx-clawbot-launcher")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--launch-id", required=True)
    args = parser.parse_args(argv)
    registry = LaunchRegistry(args.registry)
    record = registry.load(args.launch_id)
    if record["phase"] not in {"starting", "handshaking"}:
        raise LaunchError("Launch is not authorized to start a visible child")
    native_argv = launch_argv(record)
    process = read_process(os.getpid())
    if process is None:
        raise LaunchError("Launcher process identity is unavailable")
    write_json(registry.root / (args.launch_id + ".boot.json"),
               {"launch_id": args.launch_id, "pid": process.pid, "started": process.started,
                "tty_device": process.tty_device})
    os.chdir(record["cwd"])  # This dedicated child only; never the bridge process.
    os.execv(native_argv[0], native_argv)


if __name__ == "__main__":
    main()
