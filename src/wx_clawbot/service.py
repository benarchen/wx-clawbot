"""Explicit foreground bridge; closing this process leaves native terminals running."""

import asyncio
from pathlib import Path

from .agents.codex import CodexConnection
from .catalog import SessionCatalog
from .channels.http import TransportError, WeixinHttp
from .channels.private import load_credentials, private_directory
from .channels.wechat import WechatApi
from .commands import CommandError
from .controller import Controller
from .delivery import Sender
from .execution import Execution
from .hosts.connection import close_connection
from .hosts.discovery import ItermDirectory
from .hosts.launch import native_tui_command
from .hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter
from .routing import RouteError
from .runtime_state import RuntimeState
from .operations import ForegroundInstance, StopRequested
from .schema import UpgradeRequired


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
                # Bound command concurrency; native model execution does not occupy a job.
                if len(jobs) >= 32:
                    done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                    for job in done:
                        jobs.remove(job)
                        job.result()
                try:
                    work = controller.prepare(message)
                except (CommandError, RouteError) as exc:
                    await controller.reply(message, str(exc), priority=0)
                    await state.handled(message.message_id)
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


async def serve(projects, state_dir: Path, socket: Path, executable: Path, codex_home: Path, *, emit=None):
    import iterm2

    native = host = state = http = instance = None
    stage = "state"
    try:
        root = private_directory(state_dir.expanduser().absolute())
        credentials = load_credentials(root / "credentials.json")
        stage = "agent"
        executable, codex_home = executable.resolve(strict=True), codex_home.resolve(strict=True)
        native_tui_command(executable, codex_home, projects[0].root)
        native = await CodexConnection.connect(socket)
        if Path(native.server_info["codexHome"]).resolve(strict=True) != codex_home:
            raise ValueError("Native runtime belongs to another Codex home")
        stage = "host"
        host = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        directory = ItermDirectory(host)
        catalog = SessionCatalog(projects, directory, native)
        starter = VisibleStarter(LaunchRegistry(root / "launches"), ItermWindowStarter(host))
        stage = "state"
        state = await RuntimeState.open(root / "runtime.sqlite3", credentials)
        instance = ForegroundInstance(root)
        stage = "agent"
        controller = Controller(projects, catalog, state, starter, executable, codex_home)
        engine = Execution(controller)
        await controller.restore()
        if not catalog.sessions:
            await controller._refresh()
        await engine.reconcile()
        http = WeixinHttp()
        api = WechatApi(http)
        if emit:
            emit({"status": "foreground_ready", "project_count": len(projects),
                  "server_version": native.server_version, "owner_only": True})
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(component_task("channel_receive", poll(controller, api, emit=emit)))
                tasks.create_task(component_task("channel_send", Sender(state, api, emit=emit).run()))
                tasks.create_task(component_task("agent", engine.run()))
                tasks.create_task(component_task("maintenance", engine.maintain()))
                tasks.create_task(component_task("lifecycle", instance.watch_stop()))
        except* StopRequested:
            pass
    except (ComponentError, ExceptionGroup, UpgradeRequired):
        raise
    except Exception as exc:
        raise ComponentError(stage, exc) from None
    finally:
        if http:
            await http.close()
        if state:
            try:
                if instance:
                    instance.close()
            finally:
                await state.close()
        if host:
            await close_connection(host)
        if native:
            await native.close()
