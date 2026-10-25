"""Owner commands compose verified sessions; asynchronous work keeps frozen targets."""

import asyncio
import copy
import hashlib
import os
from dataclasses import asdict
from pathlib import Path

from .commands import CommandError, parse_command
from .hosts.visible import LaunchPending, reconcile_launch
from .routing import RouteError, Routes, Target
from .sessions import SessionUnbound
from .subscriptions import Subscriptions
from .output import display_segments


HELP = ("/projects：项目列表\n/cd <别名或目录>：选择或创建受管会话\n"
        "/new [标题]：当前目录新建可见会话\n/sessions [关键词]：列出会话并退出输入聚焦\n"
        "/focus <序号>：选择普通消息目标\n/unfocus：退出输入聚焦\n"
        "/send <序号> <指令>：向列表会话提交一次任务\n"
        "/attach <序号>：独立观察桌面任务\n/detach：只取消观察\n"
        "/status [任务 ID]：状态\n/stop [任务 ID]：取消或请求中断\n"
        "/approve <请求 ID>、/deny <请求 ID>：一次性审批\n/answer <请求 ID> <回答>：追问答复")

SELECTIONS = {"cd", "new", "sessions", "focus", "unfocus"}


class RouteCommitFailed(RuntimeError):
    """Stop foreground processing when a durable route cannot be committed."""


def target_record(session):
    value = asdict(session.target)
    value["cwd"] = str(session.target.cwd)
    value["thread_id"] = session.binding.thread_id
    return value


class Controller:
    def __init__(self, projects, catalog, state, starter, executable, codex_home, *, launch_timeout=120):
        self.routes = Routes(projects)
        self.catalog, self.state, self.starter = catalog, state, starter
        self.executable, self.codex_home = executable, codex_home
        self.subscriptions = Subscriptions(catalog)
        self.engine = None  # Filled before polling starts; avoids a second native event consumer.
        self.selection_pending = 0
        self.changes = asyncio.Lock()
        self.launch_timeout = launch_timeout
        self.last_managed = {}

    def prepare(self, message):
        """Run at receive order, before any task awaits a network operation."""
        command = parse_command(message.text)
        revision, snapshot = self.routes.revision, self.routes.list
        dispatch, target = None, None
        if command.name in {"focus", "attach", "send"}:
            target = self.routes.select(command.index, snapshot=snapshot)
        if command.name in {"message", "send"}:
            if self.selection_pending:
                raise RouteError("会话选择尚在处理中，请等待明确回执后再发送任务。")
            dispatch = self.routes.freeze(command.text, target=target)
        destination = None
        if command.name == "cd":
            destination = self.routes.resolve_cd(command.argument)
        elif command.name == "new":
            if self.routes.project is None or self.routes.cwd is None:
                raise RouteError("请先通过 /cd 选择项目和目录。")
            destination = (self.routes.project, self.routes.cwd)
        if command.name in SELECTIONS:
            self.selection_pending += 1
        return self.execute(message, command, revision, target, dispatch, destination)

    async def reply(self, message, text, *, priority=2):
        key = hashlib.sha256(message.message_id.encode()).hexdigest()[:32]
        chunks = display_segments(text)
        for index, chunk in enumerate(chunks, 1):
            prefix = f"〔命令回执 {index}/{len(chunks)}〕\n" if len(chunks) > 1 else ""
            await self.state.queue_reply(f"command-{key}-{index - 1}", prefix + chunk, priority=priority,
                                         kind="control" if priority == 0 else "reply")

    async def execute(self, message, command, revision, target, dispatch, destination):
        try:
            name = command.name
            if dispatch:
                await self.engine.submit(message.message_id, dispatch)
                return
            if name in {"status", "stop", "approve", "deny", "answer"}:
                text = await self.engine.control(command)
            elif name == "projects":
                rows = []
                for project in self.routes.projects.values():
                    available = (project.root.is_dir() and project.root.resolve() == project.root
                                 and os.access(project.root, os.R_OK | os.X_OK))
                    rows.append(f"{project.alias}：{'可用' if available else '不可访问'}\n{project.root}")
                text = "已注册项目：\n" + "\n".join(rows)
            elif name == "help":
                text = HELP
            else:
                async with self.changes:
                    old, managed = self.routes, self.last_managed.copy()
                    candidate = copy.copy(old)
                    try:
                        text = await self._change(command, revision, target, destination, message.message_id, candidate)
                        try:
                            await self.state.save_routes(self._snapshot(candidate))
                        except BaseException as exc:
                            raise RouteCommitFailed("Route persistence failed; restart and revalidate") from exc
                    except BaseException:
                        self.last_managed = managed
                        await self._restore_roles(old)
                        raise
                    self.routes = candidate
            await self.reply(message, text, priority=0 if name in {"status", "stop", "approve", "deny", "answer"} else 2)
        except RouteCommitFailed:
            raise  # No new input may use an uncommitted selection.
        except (CommandError, RouteError) as exc:
            await self.reply(message, str(exc), priority=0)
        except (SessionUnbound, LaunchPending):
            await self.reply(message, "会话身份或启动就绪尚未确认，请检查终端后用 /sessions 刷新；不会重复创建或执行。", priority=0)
        except Exception as exc:
            # Never put native error bodies, credentials or full task content in transport errors.
            await self.reply(message, f"操作未确认（{type(exc).__name__}）；请查询状态，不要盲目重发任务。", priority=0)
        finally:
            if command.name in SELECTIONS:
                self.selection_pending -= 1
            if command.name in {"cd", "new"}:
                launch_id = hashlib.sha256((self.state.credentials.bot_id + "\0" + message.message_id).encode()).hexdigest()[:32]
                await self.state.supersede_reply(launch_id + "-starting")
            await self.state.handled(message.message_id)

    async def _refresh(self, keyword=""):
        registry = self.starter.registry
        for filename in registry.root.glob("*.json"):
            if filename.name.endswith(".boot.json"):
                continue
            record = registry.load(filename.stem)
            project = self.routes.projects.get(record.get("project_alias"))
            if project is None or record.get("project_root") != str(project.root):
                continue
            self.routes.validate_target(Target("launch-" + filename.stem, project.alias, Path(record["cwd"]), "managed"))
            if record["phase"] in {"starting", "handshaking", "unknown", "ready"}:
                try:
                    binding = await reconcile_launch(registry, filename.stem, self.catalog.directory, self.catalog.agent)
                except (SessionUnbound, LaunchPending):
                    continue
                self.catalog.managed_threads.add(binding.thread_id)
        return await self.catalog.discover(keyword)

    def _snapshot(self, routes):
        def encode(target):
            if target is None:
                return None
            session = self.catalog.sessions.get(target.session_id) or self.subscriptions.bound.get(target.session_id)
            if session is None or session.target != target:
                raise RouteCommitFailed("Durable selection has no verified identity record")
            return target_record(session)
        return {"version": 1, "revision": routes.revision, "mode": routes.mode,
                "project": routes.project.alias if routes.project else None,
                "cwd": str(routes.cwd) if routes.cwd else None,
                "target": encode(routes.target), "observer": encode(routes.observer),
                "last_managed": [encode(t) for t in self.last_managed.values()
                                 if t.session_id in self.catalog.sessions][-100:]}

    async def _restore_roles(self, routes):
        # Restore only selection leases; task/interaction leases can change concurrently.
        try:
            for role, target in (("route", routes.target), ("observer", routes.observer)):
                if target and not self.subscriptions.has(target, role):
                    await self.subscriptions.acquire(target, role)
                for session in tuple(self.subscriptions.bound.values()):
                    if session.target != target:
                        await self.subscriptions.release(session.target, role)
        except BaseException as exc:
            raise RouteCommitFailed("Selection subscription rollback could not be confirmed") from exc

    async def restore(self):
        snapshot = await self.state.load_routes()
        if snapshot is None:
            return
        if snapshot.get("version") != 1 or type(snapshot.get("revision")) is not int or snapshot["revision"] < 0:
            raise RouteCommitFailed("Invalid durable route version or revision")
        await self._refresh()
        routes = Routes(tuple(self.routes.projects.values()))
        routes.revision = snapshot["revision"] + 1
        stale = False

        async def verified(record):
            nonlocal stale
            if record is None:
                return None
            if not isinstance(record, dict):
                raise RouteCommitFailed("Invalid durable route target")
            session = self.catalog.sessions.get(record.get("session_id"))
            if session is None or target_record(session) != record:
                stale = True
                return None
            try:
                routes.validate_target(session.target)
                await self.catalog.require(session.target)
            except (SessionUnbound, RouteError):
                stale = True
                return None
            return session.target

        project = routes.projects.get(snapshot.get("project"))
        if project and isinstance(snapshot.get("cwd"), str):
            try:
                chosen_project, cwd = routes.resolve_cd(snapshot["cwd"])
                if chosen_project == project:
                    routes.project, routes.cwd = project, cwd
            except RouteError:
                stale = True
        target = await verified(snapshot.get("target"))
        observer = await verified(snapshot.get("observer"))
        mode = snapshot.get("mode")
        if mode not in {"focused", "managed", "unbound"} or (mode == "managed" and target and target.origin != "managed"):
            raise RouteCommitFailed("Invalid durable route mode")
        if target and mode != "unbound":
            await self.subscriptions.acquire(target, "route")
            routes.target, routes.mode = target, mode
            routes.project, routes.cwd = routes.projects[target.project_alias], target.cwd
        if observer:
            await self.subscriptions.acquire(observer, "observer")
            routes.observer = observer
        history = snapshot.get("last_managed", [])
        if not isinstance(history, list) or len(history) > 100:
            raise RouteCommitFailed("Invalid managed route history")
        for record in history:
            target = await verified(record)
            if target and target.origin == "managed":
                self.last_managed[(target.project_alias, target.cwd)] = target
        # Old numeric lists never survive a restart, even when targets remain valid.
        await self.state.save_routes(self._snapshot(routes))
        self.routes = routes
        if stale:
            await self.state.queue_reply(f"route-recovery-{routes.revision}",
                "部分旧会话已无法核验，未恢复对应选择；请用 /sessions 刷新。未知任务不会重放。", priority=0)

    async def _set_focus(self, target, expected, routes, *, managed=False):
        previous = routes.target
        await self.subscriptions.acquire(target, "route")
        if self.engine:
            await self.engine.sync_external(target)
        try:
            if previous is not None and previous != target:
                await self.subscriptions.release(previous, "route")
            if managed:
                routes.managed(target, expected=expected)
            else:
                routes.focus(target, expected=expected)
            if target.origin == "managed":
                self.last_managed.pop((target.project_alias, target.cwd), None)
                self.last_managed[(target.project_alias, target.cwd)] = target
                if len(self.last_managed) > 100:
                    self.last_managed.pop(next(iter(self.last_managed)))
        except BaseException:
            if previous != target:
                await self.subscriptions.release(target, "route")
            raise

    async def _change(self, command, revision, target, destination, message_id, routes):
        name = command.name
        routes._check_revision(revision)
        if name == "sessions":
            sessions = await self._refresh(command.argument)
            previous = routes.target
            if previous:
                await self.subscriptions.release(previous, "route")
            snapshot = routes.snapshot(tuple(s.target for s in sessions))
            rows = [f"{i}．{s.target.project_alias}｜{s.title}｜{'受管会话' if s.target.origin == 'managed' else '原终端'}\n会话：{s.target.session_id}\n目录：{s.target.cwd}"
                    for i, s in enumerate(sessions, 1)]
            missing = len(self.catalog.unverified)
            return ("会话列表（10 分钟有效；已退出输入聚焦）：\n" + ("\n".join(rows) or "暂无已核验会话。")
                    + (f"\n另有 {missing} 个端点未通过当前会话 ID 核验。" if missing else "")
                    + f"\n列表：{snapshot.list_id}")
        if name == "focus":
            await self._set_focus(target, revision, routes)
            return f"执行目标：{target.project_alias}｜{target.session_id}\n目录：{target.cwd}"
        if name == "unfocus":
            previous = routes.target
            if previous:
                await self.subscriptions.release(previous, "route")
            routes.unfocus()
            return "已退出输入聚焦；观察订阅及已接收任务保留。"
        if name == "attach":
            previous = routes.observer
            await self.subscriptions.acquire(target, "observer")
            try:
                if previous and previous != target:
                    await self.subscriptions.release(previous, "observer")
                routes.attach_confirmed(target, expected=revision)
            except BaseException:
                if previous != target:
                    await self.subscriptions.release(target, "observer")
                raise
            if previous and previous != target:
                return (f"观察订阅已从 {previous.project_alias}｜{previous.session_id} 替换为 "
                        f"{target.project_alias}｜{target.session_id}；执行目标未改变。")
            return f"观察订阅：{target.project_alias}｜{target.session_id}；执行目标未改变。"
        if name == "detach":
            previous = routes.observer
            if previous:
                await self.subscriptions.release(previous, "observer")
            routes.detach_confirmed(expected=revision)
            return "已取消观察订阅；执行目标及已接收任务保留。"
        if name in {"cd", "new"}:
            project, cwd = destination
            if name == "cd":
                sessions = await self._refresh()
                matches = [s for s in sessions if s.target.project_alias == project.alias
                           and s.target.cwd == cwd and s.target.origin == "managed"]
                preferred = self.last_managed.get((project.alias, cwd))
                if preferred:
                    matches = sorted(matches, key=lambda s: s.target != preferred)
                if matches and (len(matches) == 1 or matches[0].target == preferred):
                    chosen = matches[0].target
                    await self._set_focus(chosen, revision, routes, managed=True)
                    return f"执行目标：{project.alias}｜{chosen.session_id}（复用受管会话）\n目录：{cwd}"
                if matches:
                    raise RouteError("该目录有多个受管会话，请用 /sessions 和 /focus 明确选择。")
            # Stable source native ID maps one launch request to at most one visible terminal.
            launch_id = hashlib.sha256((self.state.credentials.bot_id + "\0" + message_id).encode()).hexdigest()[:32]
            await self.state.queue_reply(launch_id + "-starting",
                f"已接收可见启动请求：{project.alias}。正在核验启动，尚未就绪。", priority=2)
            await self.starter.start(launch_id, project, cwd, self.executable, self.codex_home, command.argument if name == "new" else "")
            deadline = asyncio.get_running_loop().time() + self.launch_timeout
            while True:
                try:
                    binding = await reconcile_launch(self.starter.registry, launch_id, self.catalog.directory, self.catalog.agent)
                    break
                except LaunchPending:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise
                    await asyncio.sleep(.5)
            self.catalog.managed_threads.add(binding.thread_id)
            sessions = await self.catalog.discover()
            matches = [s for s in sessions if s.binding.thread_id == binding.thread_id]
            if len(matches) != 1:
                raise SessionUnbound("Ready launch is not uniquely discoverable")
            chosen = matches[0].target
            await self._set_focus(chosen, revision, routes, managed=True)
            self.last_managed[(project.alias, cwd)] = chosen
            await self.state.supersede_reply(launch_id + "-starting")
            return f"可见会话已就绪，执行目标：{project.alias}｜{chosen.session_id}\n目录：{cwd}"
        raise CommandError("未知命令，请使用 /help。")
