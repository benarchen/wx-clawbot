"""Persist a visible launch intent before an iTerm2 mutation; never replay uncertainty."""

import asyncio
import os
import re
import shlex
import sys
import time
from pathlib import Path

from ..channels.private import private_directory, private_lease, read_json, write_json
from ..config import Project, resolve_directory
from .launch import native_tui_command


class LaunchError(ValueError):
    pass


def check_launch_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise LaunchError("Invalid stable launch identity")


class LaunchRegistry:
    def __init__(self, root: Path):
        self.root = private_directory(root)

    def load(self, launch_id):
        check_launch_id(launch_id)
        record = read_json(self.root / (launch_id + ".json"))
        if (record.get("version") != 1 or record.get("launch_id") != launch_id
                or record.get("phase") not in {"prepared", "starting", "handshaking", "ready", "unknown", "failed"}):
            raise LaunchError("Invalid private launch record")
        return record

    def save(self, record):
        check_launch_id(record["launch_id"])
        write_json(self.root / (record["launch_id"] + ".json"), record, replace=True)

    def prepare(self, launch_id, project: Project, cwd: Path, executable: Path, codex_home: Path, title=""):
        check_launch_id(launch_id)
        if not isinstance(title, str) or len(title) > 128 or "\0" in title:
            raise LaunchError("Bounded title required")
        cwd = resolve_directory(project, str(cwd))
        native_tui_command(executable, codex_home, cwd)  # Validate before any host mutation.
        target = {"project_alias": project.alias, "project_root": str(project.root), "cwd": str(cwd),
                  "executable": str(executable.resolve(strict=True)),
                  "codex_home": str(codex_home.resolve(strict=True)), "title": title}
        filename = self.root / (launch_id + ".json")
        if filename.exists():
            record = self.load(launch_id)
            if any(record.get(key) != value for key, value in target.items()):
                raise LaunchError("Launch identity was reused for another target")
            return record
        record = {"version": 1, "launch_id": launch_id, "phase": "prepared", "created_at": time.time(),
                  "path": os.environ.get("PATH", os.defpath), **target}
        write_json(filename, record)
        return record

    def command(self, launch_id):
        check_launch_id(launch_id)
        # Preserve the venv interpreter path: resolving its symlink loses the venv.
        return shlex.join([str(Path(sys.executable).absolute()), "-m", "wx_clawbot.launcher",
                           "--registry", str(self.root), "--launch-id", launch_id])


class VisibleStarter:
    def __init__(self, registry: LaunchRegistry, create_terminal):
        self.registry, self.create_terminal = registry, create_terminal
        self.lock = asyncio.Lock()

    async def start(self, launch_id, project, cwd, executable, codex_home, title=""):
        check_launch_id(launch_id)
        async with self.lock:
            with private_lease(self.registry.root / (launch_id + ".lock")):
                record = self.registry.prepare(launch_id, project, cwd, executable, codex_home, title)
                if record["phase"] != "prepared":
                    return record  # Starting/unknown needs reconciliation, never another host call.
                record["phase"] = "starting"
                self.registry.save(record)
                try:
                    async with asyncio.timeout(15):
                        endpoint = await self.create_terminal(self.registry.command(launch_id))
                    if not isinstance(endpoint, dict) or set(endpoint) != {"window_id", "tab_id", "terminal_id"} or any(
                        not isinstance(endpoint.get(key), str) or not endpoint[key]
                        for key in ("window_id", "tab_id", "terminal_id")
                    ):
                        raise LaunchError("Visible endpoint receipt is incomplete")
                    record.update(phase="handshaking", **endpoint)
                    self.registry.save(record)
                except BaseException:
                    record["phase"] = "unknown"
                    try:
                        self.registry.save(record)
                    except OSError:
                        pass  # A durable starting record is also uncertain and non-replayable.
                    raise
                return record


class ItermWindowStarter:
    """Creates only a new owned window, or a tab in that explicitly owned window."""

    def __init__(self, connection, owned_window_id=None):
        self.connection, self.owned_window_id = connection, owned_window_id

    async def __call__(self, command):
        import iterm2

        app = await iterm2.async_get_app(self.connection)
        window = app.get_window_by_id(self.owned_window_id) if self.owned_window_id else None
        if window is None:
            window = await iterm2.Window.async_create(self.connection, command=command)
            if window is None:
                raise LaunchError("New owned terminal ended before acknowledgement")
            self.owned_window_id = window.window_id
            tab = window.current_tab
        else:
            tab = await window.async_create_tab(command=command)
        if tab is None or tab.current_session is None:
            raise LaunchError("No visible terminal endpoint returned")
        return {"window_id": window.window_id, "tab_id": tab.tab_id,
                "terminal_id": tab.current_session.session_id}
