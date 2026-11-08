"""Explicit foreground bridge; closing this process leaves native terminals running."""

import asyncio
from pathlib import Path

from .channels.http import TransportError, WeixinHttp
from .channels.private import load_credentials, private_directory, private_lease
from .channels.wechat import WechatApi
from .commands import CommandError, parse_command
from .delivery import Sender
from .hosts.lifecycle import HostLifecycle
from .hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter
from .routing import RouteError
from .runtime_state import RuntimeState
from .operations import ForegroundInstance, StopRequested
from .schema import UpgradeRequired
from .runtime_lifecycle import BridgeRuntime


class ComponentError(RuntimeError):
    def __init__(self, component, error):
        self.component, self.error_type = component, type(error).__name__
        super().__init__(component)


async def component_task(component, work):
    try:
        return await work
    except StopRequested:
        raise
    except Exception as exc:
        raise ComponentError(component, exc) from None


def failure_report(error):
    if isinstance(error, BaseExceptionGroup):
        return [item for child in error.exceptions for item in failure_report(child)]
    component = getattr(error, "component", "config" if type(error).__name__ == "ConfigError" else "startup")
    hints = {"state": "检查私有目录权限、本人绑定、账本版本及消费者锁。",
             "host": "检查 iTerm2 已打开、Python API 已启用及脚本授权。",
             "agent": "检查原生连接、版本、当前会话及 Codex home；不要重复提交未知任务。",
             "agent_discovery": "先在普通终端检查 codex app-server daemon version；也可明确指定既有 socket 和原生可执行文件。",
             "config": "检查项目配置 JSON 和已注册项目目录。",
             "channel_receive": "检查微信本人绑定、登录状态及网络；认证失效需本人重新扫码，不自动迁移。",
             "channel_send": "检查发送状态与微信连接；unknown 可能已送达，不自动重试。",
             "maintenance": "检查原生连接和私有账本；重启后先核对未知状态。",
             "lifecycle": "检查私有实例记录权限；可在原前台终端按 Ctrl+C 退出。"}
    return [{"component": component, "error_type": getattr(error, "error_type", type(error).__name__),
             "message": hints.get(component, "请运行 doctor 和 status 核对组件。")}]


async def poll(controller, api, *, emit=None):
    state = controller.state
    jobs = set()
    try:
        while True:
            cursor = await state.cursor()
            try:
                response = await api.updates(state.credentials, cursor)
            except TransportError:
                if emit:
                    emit({"status": "receive_disconnected", "cursor_preserved": True})
                await asyncio.sleep(1)
                continue
            batch = await state.accept_batch(response, phase="runtime")
            for message in batch["accepted"]:
                completed = {job for job in jobs if job.done()}
                for job in completed:
                    jobs.remove(job)
                    job.result()
                # Do not stop receiving controls behind a full set of pending
                # submissions. Reject overload before prepare can reserve a
                # selection; static queries do not depend on native I/O.
                try:
                    name = parse_command(message.text).name if not getattr(message, "content", ()) else "message"
                except CommandError:
                    name = "invalid"
                static = name in {"help", "projects", "status"} or name == "project" and parse_command(message.text).argument.strip() in {"", "list", "check"}
                urgent = name in {"stop", "approve", "deny", "answer"}
                if not static and len(jobs) >= (40 if urgent else 32):
                    await controller.reply(message, "当前待处理命令已达上限，本条操作未接收，请稍后重试。", priority=0)
                    await state.handled(message.message_id)
                    continue
                try:
                    work = controller.prepare(message)
                except (CommandError, RouteError) as exc:
                    await controller.reply(message, str(exc), priority=0)
                    await state.handled(message.message_id)
                else:
                    if static:
                        await work
                    else:
                        jobs.add(asyncio.create_task(work))
            completed = {job for job in jobs if job.done()}
            for job in completed:
                jobs.remove(job)
                job.result()
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


async def serve(projects, state_dir: Path, socket: Path, executable: Path, codex_home: Path, *, emit=None, config_path=None):
    host = state = http = instance = project_server = None
    stage = "state"
    try:
        root = private_directory(state_dir.expanduser().absolute())
        credentials = load_credentials(root / "credentials.json")
        codex_home = codex_home.resolve(strict=True)
        with private_lease(root / "project-edit.lock"):
            state = await RuntimeState.open(root / "runtime.sqlite3", credentials)
            instance = ForegroundInstance(root)
            if config_path is not None:
                from .project_registry import ProjectStore
                project_store = ProjectStore(config_path, root)
                projects = project_store.config.projects
        host = HostLifecycle()
        starter = VisibleStarter(LaunchRegistry(root / "launches"), ItermWindowStarter(lifecycle=host))
        last_health = None

        def runtime_emit(report):
            nonlocal last_health
            if report.get("status") == "capabilities":
                health = {key: report[key] for key in ("host", "native")}
                if health == last_health:
                    return
                instance.health(health)
                last_health = health
            if emit:
                emit(report)

        runtime = BridgeRuntime(projects, state, starter, host, socket, executable, codex_home, emit=runtime_emit)
        if config_path is not None:
            from .project_registry import ProjectManager
            from .project_control import ProjectServer
            runtime.project_manager = ProjectManager(project_store, runtime)
            project_server = ProjectServer(runtime.project_manager, instance)
            await project_server.start()
        await runtime.initialize()
        runtime_emit({"status": "capabilities", **runtime.report()})
        http = WeixinHttp()
        api = WechatApi(http)
        if emit:
            emit({"status": "foreground_ready", "project_count": len(projects),
                  "owner_only": True, "dependencies_recovering": True})
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(component_task("channel_receive", poll(runtime, api, emit=emit)))
                tasks.create_task(component_task("channel_send", Sender(state, api, emit=emit).run()))
                tasks.create_task(component_task("agent", runtime.run()))
                tasks.create_task(component_task("host", runtime.watch_host()))
                tasks.create_task(component_task("lifecycle", instance.watch_stop()))
                if runtime.project_manager is not None:
                    tasks.create_task(component_task("project_registry", runtime.project_manager.watch_failure()))
        except* StopRequested:
            pass
    except (ComponentError, ExceptionGroup, UpgradeRequired):
        raise
    except Exception as exc:
        raise ComponentError(stage, exc) from None
    finally:
        if project_server:
            await project_server.close()
        if http:
            await http.close()
        if state:
            try:
                if instance:
                    instance.close()
            finally:
                await state.close()
        if host:
            await host.close()
