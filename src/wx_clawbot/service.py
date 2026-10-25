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
                    await controller.reply(message, str(exc))
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

    root = private_directory(state_dir.expanduser().absolute())
    credentials = load_credentials(root / "credentials.json")
    executable, codex_home = executable.resolve(strict=True), codex_home.resolve(strict=True)
    native_tui_command(executable, codex_home, projects[0].root)
    native = host = state = http = None
    try:
        native = await CodexConnection.connect(socket)
        if Path(native.server_info["codexHome"]).resolve(strict=True) != codex_home:
            raise ValueError("Native runtime belongs to another Codex home")
        host = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        directory = ItermDirectory(host)
        catalog = SessionCatalog(projects, directory, native)
        starter = VisibleStarter(LaunchRegistry(root / "launches"), ItermWindowStarter(host))
        state = await RuntimeState.open(root / "runtime.sqlite3", credentials)
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
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(poll(controller, api, emit=emit))
            tasks.create_task(Sender(state, api, emit=emit).run())
            tasks.create_task(engine.run())
            tasks.create_task(engine.maintain())
    finally:
        if http:
            await http.close()
        if state:
            await state.close()
        if host:
            await close_connection(host)
        if native:
            await native.close()
