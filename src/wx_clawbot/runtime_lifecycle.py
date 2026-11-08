"""Keep WeChat alive while host and existing native connections recover."""

import asyncio
import hashlib
from pathlib import Path

from .agents.base import Capabilities
from .agents.codex import CodexConnection
from .agents.rpc import ConnectionLost
from .catalog import SessionCatalog
from .commands import CommandError, parse_command, parse_project
from .controller import Controller, RouteCommitFailed
from .execution import Execution
from .hosts.discovery import ItermDirectory
from .hosts.launch import native_tui_command
from .hosts.lifecycle import HostUnavailable
from .routing import RouteError
from .runtime_discovery import discover_runtime


def native_failure_report(error):
    """Bounded exception classes only; never forward exception messages or paths."""
    report = {"status": "native_unavailable", "error_type": type(error).__name__}
    if isinstance(error, BaseExceptionGroup):
        stack, names = [iter((error,))], set()
        for _ in range(64):
            while stack:
                child = next(stack[-1], None)
                if child is not None:
                    break
                stack.pop()
            else:
                break
            if isinstance(child, BaseExceptionGroup):
                stack.append(iter(child.exceptions))
            else:
                names.add(type(child).__name__)
                if len(names) > 8:
                    break
        report["error_types"] = sorted(names)[:8]
        report["classification_truncated"] = bool(stack)
    return report


class UnavailableNative:
    capabilities = Capabilities()
    runtime_identity = None

    async def list_project_threads(self, *_):
        return {"data": []}

    async def loaded_threads(self):
        return frozenset()


class OfflineExecution:
    def __init__(self, controller):
        self.controller = controller

    async def reconcile(self):
        pass

    async def control(self, command):
        state = self.controller.state
        if command.name == "status":
            if command.argument:
                task = await state.tasks(task_id=command.argument)
                if task is None:
                    raise CommandError("任务不存在。")
                return (f"{task['target']['project_alias']}｜{task['id']}：{task['state']}。\n"
                        + await state.describe_admission(task) + '\n原生离线，以上为最后保存的记录。')
            tasks = await state.tasks(active_only=True)
            occupancy = await state.occupancy_counts()
            return ("执行目标尚未重新核验；原生运行时未就绪，不会自动重放任务。\n"
                    + ("\n".join(f"{t['id']}：{t['state']}" for t in tasks[:20]) or "暂无未结束任务。")
                    + f"\n历史未知且已释放占用：{occupancy.get('released_unknown',0)} 条；以上为最后记录。")
        if command.name == "stop" and command.argument:
            task = await state.tasks(task_id=command.argument)
            if task and task["state"] == "received":
                if await state.task_finish(task["id"], "cancelled", f"已撤销尚未提交的任务：{task['id']}。",
                                           only_if={"received"}, reply_priority=0):
                    return None
        raise CommandError("原生连接不可用，操作未发送；旧交互不能答复，请查询 /status。")


class BridgeRuntime:
    def __init__(self, projects, state, starter, host, socket, executable, codex_home, *, emit=None):
        self.projects, self.state, self.starter, self.host = projects, state, starter, host
        self.socket, self.executable, self.codex_home = socket, executable, codex_home
        self.emit = emit
        self.native_state, self.native_generation = "unavailable", 0
        self.controller = self.offline_controller()
        self.pending_restore = False
        self.host_generation = None
        self.transition = asyncio.Lock()
        self.project_manager = None

    def offline_controller(self):
        catalog = SessionCatalog(self.projects, ItermDirectory(lifecycle=self.host), UnavailableNative())
        controller = Controller(self.projects, catalog, self.state, self.starter,
                                self.executable, self.codex_home, host=self.host)
        controller.native_ready = False
        controller.engine = OfflineExecution(controller)
        controller.project_manager = getattr(self, "project_manager", None)
        return controller

    async def initialize(self):
        snapshot = await self.state.load_routes()
        if self.project_manager is not None:
            from .project_registry import sanitize_routes
            snapshot = sanitize_routes(snapshot, self.project_manager.store.config)
        if snapshot and isinstance(snapshot.get("cwd"), str):
            try:
                project, cwd = self.controller.routes.resolve_cd(snapshot["cwd"])
                self.controller.routes.project, self.controller.routes.cwd = project, cwd
                revision = snapshot.get("revision")
                if type(revision) is int and revision >= 0:
                    self.controller.routes.revision = revision + 1
            except RouteError:
                pass

    def prepare(self, message):
        if not getattr(message, "content", ()) and not getattr(message, "error", None):
            command = parse_command(message.text)
            if command.name in {"project", "projects"} and self.project_manager is not None:
                args = parse_project(command.argument) if command.name == "project" else {"action": "list"}
                return self.project_command(message, args)
        return self.controller.prepare(message)

    async def project_command(self, message, args):
        from .project_registry import ProjectError, describe
        from .config import ConfigError
        action = args.pop("action")
        if action in {"add", "remove"}:
            args["request"] = "wx-prj-" + hashlib.sha256(message.message_id.encode()).hexdigest()[:32]
        try:
            async with asyncio.timeout(30):
                result = await self.project_manager.execute(action, **args)
            await self.reply(message, describe(result))
        except (ProjectError, ConfigError) as exc:
            await self.reply(message, str(exc), priority=0)
        except (OSError, TimeoutError):
            await self.reply(message, "项目变更未确认，请检查请求记录，不要自动重试。\n请求：" + args.get("request", "无"), priority=0)
        finally:
            await self.state.handled(message.message_id)

    async def reply(self, *args, **kwargs):
        await self.controller.reply(*args, **kwargs)

    def report(self):
        return {"host": self.host.report(), "native": {"state": self.native_state,
                                                       "generation": self.native_generation}}

    async def restore_host(self):
        async with self.transition:
            return await self._restore_host()

    async def _restore_host(self):
        controller = self.controller
        if not controller.native_ready:
            return False
        if self.host._connection is None and not self.pending_restore:
            return False
        if not self.pending_restore and self.host_generation == self.host.generation:
            return False
        async with asyncio.timeout(25):
            async with controller.changes:
                if controller is not self.controller:
                    raise HostUnavailable("changed")
                generation = self.host.generation
                controller.recovering = True
                try:
                    if self.pending_restore:
                        await controller.restore()
                        if not controller.catalog.sessions:
                            await controller._refresh()
                        await controller.engine.reconcile()
                    else:
                        await controller.recover_host()
                    if self.host._connection is not None:
                        self.host.verified(generation)
                        self.host_generation = generation
                    self.pending_restore = False
                finally:
                    controller.recovering = False
        return True

    async def watch_host(self):
        delay = 1
        while True:
            try:
                generation = await self.host.ensure()
                if not self.controller.native_ready:
                    self.host.verified(generation)
                # Explicit commands perform the same restore before mutating;
                # the watchdog must not wait behind a long visible handshake.
                if not self.controller.changes.locked() and not self.controller.selection_pending:
                    await self.restore_host()
                delay = 1
            except (HostUnavailable, TimeoutError, OSError):
                delay = min(delay * 2, 15)
            if self.emit:
                self.emit({"status": "capabilities", **self.report()})
            await asyncio.sleep(delay if self.host.state != "ready" else 5)

    async def connect_native(self):
        socket, executable = self.socket, self.executable
        if socket is None or executable is None:
            found_socket, found_executable = await asyncio.to_thread(discover_runtime, self.codex_home)
            socket, executable = socket or found_socket, executable or found_executable
        executable = executable.resolve(strict=True)
        native_tui_command(executable, self.codex_home, self.codex_home)
        native = await CodexConnection.connect(socket)
        if Path(native.server_info["codexHome"]).resolve(strict=True) != self.codex_home:
            await native.close()
            raise ValueError("Native runtime belongs to another Codex home")
        return native, executable

    async def run(self):
        delay = 1
        while True:
            native = engine = None
            controller = None
            try:
                self.native_state = "connecting"
                native, executable = await self.connect_native()
                self.native_generation += 1
                self.native_state = "ready"
                async with self.transition:
                    await self.controller.retire()
                    catalog = SessionCatalog(self.projects, ItermDirectory(lifecycle=self.host), native)
                    controller = Controller(self.projects, catalog, self.state, self.starter,
                                            executable, self.codex_home, host=self.host)
                    controller.native_generation = self.native_generation
                    controller.project_manager = self.project_manager
                    engine = Execution(controller)
                    self.controller = controller
                    self.pending_restore = True
                    self.host_generation = None
                    controller.before_change = self.restore_host
                    await self.initialize()
                await self.restore_host()  # Native targets do not wait for a host connection.
                try:
                    await self.host.ensure()
                    await self.restore_host()
                except (HostUnavailable, TimeoutError):
                    pass
                delay = 1
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(engine.run())
                    tasks.create_task(engine.maintain())
                    async def recover_uncertain_selection():
                        await controller.recovery_requested.wait()
                        raise ConnectionLost("Selection cleanup requires a fresh native subscription")
                    tasks.create_task(recover_uncertain_selection())
            except RouteCommitFailed:
                raise
            except Exception as exc:
                # Transport/protocol availability is independent of WeChat.
                # Persisting state errors must still fail instead of being
                # silently retried as connection errors.
                from .channels.http import ProtocolError
                import sqlite3
                def state_failure(error):
                    if isinstance(error, BaseExceptionGroup):
                        return any(state_failure(e) for e in error.exceptions)
                    return isinstance(error, (ProtocolError, RouteCommitFailed, sqlite3.Error))
                if state_failure(exc):
                    raise
                if self.emit:
                    self.emit(native_failure_report(exc))
            finally:
                self.native_state = "unavailable"
                if controller is not None:
                    controller.native_ready = False
                async with self.transition:
                    if controller is not None:
                        await controller.retire()
                    if engine is not None:
                        await engine.close()
                        await self.state.native_disconnected()
                    if native is not None:
                        await native.close()
                    self.controller = self.offline_controller()
                    await self.initialize()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)
