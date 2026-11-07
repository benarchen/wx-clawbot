"""Persist a visible launch intent before an iTerm2 mutation; never replay uncertainty."""

import asyncio
import os
import re
import shlex
import sys
import time
from dataclasses import asdict
from pathlib import Path

from ..channels.private import private_directory, private_lease, read_json, write_json
from ..config import Project, resolve_directory
from .launch import native_tui_command


class LaunchError(ValueError):
    pass


class LaunchPending(LaunchError):
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
        return shlex.join([str(Path(sys.executable).absolute()), "-I", "-m", "wx_clawbot.launcher",
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

    def __init__(self, connection=None, owned_window_id=None, *, lifecycle=None):
        self.connection, self.owned_window_id = connection, owned_window_id
        self.lifecycle, self.host_generation = lifecycle, None

    async def __call__(self, command):
        if self.lifecycle is not None:
            if self.host_generation != self.lifecycle.generation:
                self.owned_window_id = None
                self.host_generation = self.lifecycle.generation
            return await self.lifecycle.call(lambda connection: self._create(connection, command))
        return await self._create(self.connection, command)

    async def _create(self, connection, command):
        import iterm2

        app = await iterm2.async_get_app(connection)
        window = app.get_window_by_id(self.owned_window_id) if self.owned_window_id else None
        if window is None:
            window = await iterm2.Window.async_create(connection, command=command)
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


async def reconcile_launch(registry, launch_id, directory, native):
    """Read-only host/native reconciliation followed by a proven ready record."""
    from ..sessions import SessionBinding, SessionUnbound, verify_binding

    check_launch_id(launch_id)
    with private_lease(registry.root / (launch_id + ".lock")):
        record = registry.load(launch_id)
        if record["phase"] not in {"starting", "unknown", "handshaking", "ready"}:
            raise LaunchPending("Launch has no visible host operation to reconcile")
        boot_file = registry.root / (launch_id + ".boot.json")
        if not boot_file.exists():
            raise LaunchPending("Visible launcher has not acknowledged its process")
        boot = read_json(boot_file)
        if boot.get("launch_id") != launch_id:
            raise LaunchError("Launcher receipt identity mismatch")
        candidates = [endpoint for endpoint in await directory.discover()
                      if endpoint.classification == "codex_candidate" and endpoint.process is not None
                      and endpoint.process.pid == boot.get("pid")
                      and list(endpoint.process.started) == boot.get("started")
                      and endpoint.process.tty_device == boot.get("tty_device")]
        if len(candidates) != 1:
            raise LaunchPending("No unique live Codex process matches the launcher receipt")
        endpoint = candidates[0]
        endpoint_changed = record.get("terminal_id") not in {None, endpoint.terminal_id}
        if Path(endpoint.process.executable).resolve() != Path(record["executable"]):
            raise SessionUnbound("Visible executable identity changed")
        # A ready launch has durable boot/handshake proof for its exact thread.
        # Reuse it after a desktop switch; a changed endpoint still needs visible
        # proof before we can associate that endpoint with the original thread.
        established = record["phase"] == "ready" and not endpoint_changed
        visible_id = record.get("thread_id") if established else await directory.current_thread_id(endpoint)
        if visible_id is None:
            raise LaunchPending("Current native thread ID is not displayed by the terminal")
        page = await native.list_project_threads(Path(record["cwd"]))
        if page.get("nextCursor"):
            raise LaunchError("Launch reconciliation exceeds native page bound")
        marker = "WX-LAUNCH-" + launch_id
        threads = [thread for thread in page["data"] if thread["id"] == visible_id
                   and thread.get("preview", "").startswith(marker)
                   and thread.get("status", {}).get("type") in {"idle", "active", "systemError"}
                   and thread.get("forkedFromId") is None]
        if len(threads) != 1:
            raise LaunchPending("Visible thread has no matching original launch handshake")
        thread = await native.inspect(visible_id)
        if (record.get("thread_id") not in {None, thread["id"]}
                or record.get("native_session_id") not in {None, thread["sessionId"]}
                or record.get("runtime_identity") is not None
                and tuple(record["runtime_identity"]) != native.runtime_identity):
            raise SessionUnbound("Previously bound runtime or thread changed")
        if endpoint_changed and (record["phase"] != "ready" or record.get("thread_id") != thread["id"]
                                or record.get("native_session_id") != thread["sessionId"]
                                or tuple(record.get("runtime_identity") or ()) != native.runtime_identity):
            raise SessionUnbound("Changed terminal requires the exact previously verified native identity")
        binding = SessionBinding(endpoint, Path(record["cwd"]), native.runtime_identity,
                                 thread["id"], thread["sessionId"])
        await verify_binding(binding, directory, native, require_visible=not established)
        turns = (await native.read_turns(thread["id"], limit=1))["data"]
        if not turns or turns[0].get("status") != "completed":
            raise LaunchPending("Original visible handshake has not completed")
        user = [part.get("text", "") for item in turns[0].get("items", []) if item.get("type") == "userMessage"
                for part in item.get("content", [])]
        output = [item.get("text", "") for item in turns[0].get("items", []) if item.get("type") == "agentMessage"]
        if not any(text.startswith(marker) for text in user) or not any(marker in text for text in output):
            raise LaunchError("Native turn does not prove the launch handshake")
        if record["phase"] != "ready" and record["title"]:
            await native.rpc.request("thread/name/set", {"threadId": thread["id"], "name": record["title"]})
        record.update(phase="ready", terminal_id=endpoint.terminal_id, thread_id=thread["id"],
                      native_session_id=thread["sessionId"], runtime_identity=native.runtime_identity,
                      process=asdict(endpoint.process), model=thread.get("model"),
                      model_provider=thread.get("modelProvider"))
        registry.save(record)
        return binding
