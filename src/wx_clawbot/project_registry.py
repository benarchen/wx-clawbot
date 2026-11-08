"""One private project registry: bounded discovery, atomic edits and reference checks."""

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
from contextlib import closing

from .channels.private import private_directory, private_file, private_lease
from .config import ConfigError, Project, available, forbidden, load_config, valid_alias


class ProjectError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def request_identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ProjectError("项目请求 ID 无效。")
    return value


def directory_identity(path):
    if forbidden(path):
        raise ProjectError("该目录不在允许范围内。")
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_mode]


def direct_child(workspace, name):
    if (not isinstance(name, str) or not name or len(name) > 255 or name in {".", ".."}
            or "/" in name or "\0" in name or forbidden(Path(name))):
        raise ProjectError("请指定总目录下的直接子目录名。")
    if not available(workspace):
        raise ProjectError("项目总目录不可访问或路径已变化。")
    path = workspace / name
    try:
        real = path.resolve(strict=True)
        if forbidden(real) or real.parent != workspace or not available(real):
            raise ProjectError("目录不可访问或不在总目录直接子层。")
        return real
    except (OSError, ValueError) as exc:
        if isinstance(exc, ProjectError):
            raise
        raise ProjectError("目录不可访问或链接无效。") from None


def project_rows(config):
    return [{"alias": p.alias, "root": str(p.root), "available": available(p.root)} for p in config.projects]


def ledger_blockers(db, alias):
    """Read bridge ownership only; never change a task or inspect native history."""
    result = set()
    row = db.execute("SELECT snapshot FROM routes WHERE id=1").fetchone()
    if row:
        value = json.loads(row[0])
        for role, label in (("target", "输入目标"), ("observer", "观察订阅")):
            if (value.get(role) or {}).get("project_alias") == alias:
                result.add(label)
    queries = [
        ("任务或占用", "SELECT t.target FROM tasks t LEFT JOIN task_occupancy o ON o.task_id=t.id "
         "WHERE t.state NOT IN ('completed','failed','interrupted','cancelled','unknown') "
         "OR o.state IN ('waiting','holding')"),
        ("未完成交互", "SELECT target FROM interactions WHERE state IN ('pending','sending','awaiting_native')"),
        ("未完成追问", "SELECT target FROM async_questions WHERE closed_at IS NULL AND expires_at>" + str(time.time())),
    ]
    for label, query in queries:
        rows = db.execute(query + " LIMIT 4097").fetchall()
        if len(rows) > 4096:
            raise ProjectError("项目引用超过核验上限，未取消注册。")
        if any(json.loads(row[0]).get("project_alias") == alias for row in rows):
            result.add(label)
    return result


def stopped_blockers(root, alias):
    result = set()
    database = root / "runtime.sqlite3"
    if database.exists():
        private_file(database)
        try:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("BEGIN")
                result |= ledger_blockers(db, alias)
        except (sqlite3.Error, ValueError):
            raise ProjectError("无法完整核验项目账本，未取消注册。") from None
    launches = root / "launches"
    if launches.exists():
        from .channels.private import read_json
        names = list(launches.glob("*.json"))
        if len(names) > 4096:
            raise ProjectError("启动记录超过核验上限，未取消注册。")
        for path in names:
            value = read_json(path)
            if value.get("project_alias") == alias and value.get("phase") in {"prepared", "starting", "handshaking", "unknown"}:
                result.add("尚未结束的可见创建")
    return result


def sanitize_routes(snapshot, config):
    """A remove/re-add never revives pre-removal routing authority, even after a crash."""
    if snapshot is None:
        return None
    result = copy.deepcopy(snapshot)
    revision = result.get("registry_revision", 0)
    if type(revision) is not int or revision < 0 or revision > config.revision:
        raise ProjectError("会话快照的项目修订无效。")
    floor = min((v["revision"] for v in config.operations), default=1)
    revoked = {v["removed"] for v in config.operations if v["revision"] > revision and v["removed"]}
    projects = {p.alias for p in config.projects}
    uncertain = revision < floor - 1
    def allowed(record):
        return (isinstance(record, dict) and not uncertain and record.get("project_alias") in projects
                and record.get("project_alias") not in revoked)
    for role in ("target", "observer"):
        if result.get(role) is not None and not allowed(result[role]):
            result[role] = None
    result["last_managed"] = [r for r in result.get("last_managed", []) if allowed(r)]
    if result.get("unrestored_selection"):
        for role in ("target", "observer"):
            if not allowed(result["unrestored_selection"].get(role)):
                result["unrestored_selection"][role] = None
    if result.get("project") not in projects or result.get("project") in revoked or uncertain:
        result["project"] = result["cwd"] = None
    if result.get("target") is None:
        result["mode"] = "unbound"
    result["registry_revision"] = config.revision
    return result


class ProjectStore:
    def __init__(self, config_path, state_root):
        self.path = Path(config_path).expanduser().absolute()
        if forbidden(self.path) or forbidden(Path(state_root).expanduser().absolute()):
            raise ProjectError("该配置或状态目录不在允许范围内。")
        self.root = private_directory(Path(state_root).expanduser().absolute())
        if self.path.parent.resolve() != self.path.parent or self.path.is_symlink():
            raise ProjectError("项目配置须使用真实私有路径。")
        self.config = load_config(self.path, missing=True)

    def current(self):
        config = load_config(self.path, missing=True)
        if config.digest != self.config.digest:
            raise ProjectError("配置已被外部修改；请停止桥接并校验后重新启动，未覆盖。")
        return config

    def preview(self, root, *, stamp=None):
        current = self.current()
        path = Path(root).expanduser()
        if not path.is_absolute() or forbidden(path):
            raise ProjectError("总目录须为允许的绝对路径。")
        try:
            path = path.resolve(strict=True)
            if not available(path):
                raise ProjectError("项目总目录不可访问。")
            if current.workspace_root is not None and path != current.workspace_root:
                raise ProjectError("当前不支持更换已设置的项目总目录。")
            root_identity = directory_identity(path)
            entries = []
            with os.scandir(path) as scan:
                for item in scan:
                    if len(entries) >= 1024:
                        raise ProjectError("总目录超过 1024 个目录项，未生成完整预览。")
                    # Exclude before following links, statting or opening contents.
                    if forbidden(Path(item.name)):
                        entries.append({"name": item.name, "skip": "禁止范围"})
                        continue
                    info = item.stat(follow_symlinks=False)
                    row = {"name": item.name, "identity": [info.st_dev, info.st_ino, info.st_mode]}
                    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                        row["skip"] = "非目录"
                    else:
                        try:
                            real = direct_child(path, item.name)
                            row.update(root=str(real), real_identity=directory_identity(real))
                        except ProjectError as exc:
                            row["skip"] = str(exc)
                    entries.append(row)
        except (OSError, RuntimeError):
            raise ProjectError("总目录扫描失败或路径变化，未生成完整预览。") from None
        projects, added, skipped = list(current.projects), [], []
        aliases, roots = {p.alias for p in projects}, {p.root for p in projects}
        for row in sorted(entries, key=lambda r: r["name"]):
            name = row["name"]
            if "skip" in row:
                skipped.append({"name": name, "reason": row["skip"]})
                continue
            real = Path(row["root"])
            if real in roots:
                skipped.append({"name": name, "reason": "已注册，保留原项"})
            elif not valid_alias(name) or len(name) > 128 or name in aliases:
                skipped.append({"name": name, "reason": "别名无效或冲突，请用 add --alias"})
            else:
                projects.append(Project(name, real)); roots.add(real); aliases.add(name)
                added.append({"alias": name, "root": str(real)})
        if len(projects) > 256:
            raise ProjectError("注册项目超过 256 项，未生成可提交清单。")
        stamp = int(time.time()) if stamp is None else stamp
        identity = {"digest": current.digest, "root": str(path), "root_identity": root_identity,
                    "entries": sorted(entries, key=lambda r: r["name"]), "stamp": stamp}
        confirm = str(stamp) + "-" + fingerprint(identity)
        return {"status": "preview", "workspace_root": str(path), "confirm": confirm,
                "added": added, "skipped": skipped, "projects": [{"alias": p.alias, "root": str(p.root)} for p in projects]}

    def plan(self, action, *, name="", alias="", root="", apply=False, confirm="", request=""):
        current = self.current()
        if action in {"list", "check"}:
            rows = project_rows(current)
            problems = [r["alias"] + "：目录不可访问或路径已变化。" for r in rows if not r["available"]]
            if current.workspace_root is None:
                problems.insert(0, "尚未初始化项目总目录；旧注册项仍保留。")
            elif not available(current.workspace_root):
                problems.insert(0, "项目总目录不可访问或路径已变化。")
            result = {"status": "ok", "action": action, "revision": current.revision,
                      "workspace_root": str(current.workspace_root) if current.workspace_root else None,
                      "projects": rows, "problems": problems if action == "check" else []}
            if request:
                request_identity(request)
                record = next((v for v in current.operations if v["id"] == request), None)
                result["request"] = record or {"id": request, "state": "not_in_recent_records"}
            return result, None
        request_identity(request)
        args = dict(action=action, name=name, alias=alias, root=root, apply=apply, confirm=confirm)
        mark = fingerprint(args)
        previous = next((v for v in current.operations if v["id"] == request), None)
        if previous:
            if previous["fingerprint"] != mark:
                raise ProjectError("项目请求 ID 已用于不同操作。")
            return {"status": "already_committed", "action": action, "request_id": request,
                    "revision": previous["revision"]}, None
        projects, workspace = list(current.projects), current.workspace_root
        if action == "init":
            if not apply:
                return self.preview(root), None
            try:
                stamp_text, _ = confirm.split("-", 1)
                stamp = int(stamp_text)
                if not 0 <= time.time() - stamp <= 600:
                    raise ValueError
            except (ValueError, TypeError):
                raise ProjectError("初始化确认已过期或无效，请重新预览。") from None
            preview = self.preview(root, stamp=stamp)
            if preview["confirm"] != confirm:
                raise ProjectError("目录或配置已变化，请重新预览后确认。")
            workspace = Path(preview["workspace_root"])
            projects = [Project(v["alias"], Path(v["root"])) for v in preview["projects"]]
        elif action == "add":
            if workspace is None:
                raise ProjectError("请先在本机初始化项目总目录。")
            real = direct_child(workspace, name)
            alias = alias or name
            if not valid_alias(alias) or len(alias) > 128:
                raise ProjectError("请用 --alias 指定字母、数字、连字符或下划线别名。")
            existing = next((p for p in projects if p.alias == alias or p.root == real), None)
            if existing:
                if existing == Project(alias, real):
                    return {"status": "already_registered", "action": action, "alias": alias,
                            "revision": current.revision}, None
                raise ProjectError("项目别名或真实目录已被注册，未替换。")
            if len(projects) >= 256:
                raise ProjectError("注册项目已达 256 项上限。")
            projects.append(Project(alias, real))
        elif action == "remove":
            if not valid_alias(name):
                raise ProjectError("请指定准确项目别名。")
            if not any(p.alias == name for p in projects):
                return {"status": "not_registered", "action": action, "alias": name,
                        "revision": current.revision}, None
            if workspace is None:
                raise ProjectError("请先初始化总目录后管理旧注册项。")
            projects = [p for p in projects if p.alias != name]
        else:
            raise ProjectError("未知项目操作。")
        revision = current.revision + 1
        operations = (list(current.operations) + [{"id": request, "fingerprint": mark, "revision": revision,
                                                  "removed": name if action == "remove" else ""}])[-128:]
        payload = {"version": 1, "workspace_root": str(workspace), "revision": revision,
                   "projects": [{"alias": p.alias, "root": str(p.root)} for p in projects], "operations": operations}
        result = {"status": "committed", "action": action, "request_id": request, "revision": revision}
        return result, payload

    def commit(self, payload):
        before = self.current()
        raw = encoded(payload)
        if len(raw) > 65536:
            raise ProjectError("项目配置超过 64 KiB，未写入。")
        private_directory(self.path.parent)
        if self.path.exists():
            private_file(self.path)
            backups = private_directory(self.root / "project-backups")
            backup = backups / (before.digest + ".json")
            if backup.exists():
                private_file(backup)
                if hashlib.sha256(backup.read_bytes()).hexdigest() != before.digest:
                    raise ProjectError("配置备份摘要不一致，未写入。")
            else:
                # Preserve exact bytes, not a reserialized old representation.
                with backup.open("xb") as stream:
                    os.chmod(backup, 0o600)
                    stream.write(self.path.read_bytes()); stream.flush(); os.fsync(stream.fileno())
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".projects-", delete=False) as stream:
                name = Path(stream.name)
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            self.current()  # Detect a manual edit during backup/preparation.
            os.replace(name, self.path)
            parent = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            self.config = load_config(self.path)
        finally:
            if name is not None:
                name.unlink(missing_ok=True)
        return self.config


def describe(result):
    status, action = result["status"], result.get("action")
    if status == "preview":
        return "初始化预览（未写入）：\n" + json.dumps(result, ensure_ascii=False)
    if action in {"list", "check"}:
        rows = result["projects"]
        text = "已注册项目：\n" + ("\n\n".join(
            f"{r['alias']}：{'可用' if r['available'] else '不可访问'}\n{r['root']}" for r in rows) or "暂无已注册项目。")
        if action == "check":
            text += "\n\n检查：" + ("\n".join(result["problems"]) or "注册清单与目录检查通过。")
            if "request" in result:
                text += "\n请求记录：" + json.dumps(result["request"], ensure_ascii=False)
        return text
    label = {"committed": "项目注册变更已生效", "already_committed": "该项目请求已提交，请核对当前清单",
             "already_registered": "项目已注册，未重复修改", "not_registered": "项目未注册，未修改"}[status]
    return label + "。" + ("\n请求：" + result["request_id"] if "request_id" in result else "")


class ProjectManager:
    def __init__(self, store, runtime):
        self.store, self.runtime = store, runtime
        self.gate = asyncio.Lock()
        self.failed = False
        self.failure = asyncio.Event()
        self.install(store.config)

    @property
    def revision(self):
        return self.store.config.digest

    def install(self, config):
        runtime = self.runtime
        runtime.projects = config.projects
        controller = runtime.controller
        projects = {p.alias: p for p in config.projects}
        routes, catalog = controller.routes, controller.catalog
        routes.projects = dict(projects)
        routes.list = None
        if routes.project and routes.project.alias not in projects:
            routes.project = routes.cwd = None
        catalog.projects = dict(projects)
        catalog.directories = {p.root for p in config.projects} | {
            p for p in catalog.directories if catalog.project_for(p) is not None}
        removed_threads = {s.binding.thread_id for s in catalog.sessions.values() if s.target.project_alias not in projects}
        catalog.managed_threads.difference_update(removed_threads)
        catalog.sessions = {k: s for k, s in catalog.sessions.items() if s.target.project_alias in projects}
        catalog.legacy_targets = {k: s for k, s in catalog.legacy_targets.items() if s.target.project_alias in projects}
        controller.last_managed = {k: t for k, t in controller.last_managed.items() if t.project_alias in projects}
        controller.project_manager = self

    async def blockers(self, alias):
        controller = self.runtime.controller
        result = set()
        if alias in controller.project_reservations.values():
            result.add("尚未结束的接收／选择／创建意图")
        for field, label in (("target", "输入目标"), ("observer", "观察订阅")):
            target = getattr(controller.routes, field)
            if target and target.project_alias == alias:
                result.add(label)
        if any(s.target.project_alias == alias and controller.subscriptions.roles.get(k)
               for k, s in controller.subscriptions.bound.items()):
            result.add("仍有原生订阅引用")
        result |= await controller.state._call(ledger_blockers, controller.state.db, alias)
        result |= stopped_blockers(self.store.root, alias)
        return result

    async def execute(self, action, **kwargs):
        if self.failed and action not in {"list", "check"}:
            raise ProjectError("注册状态尚未收敛，已停止新派发；请核对后重启。")
        async with self.gate:
            async with self.runtime.transition:
                async with self.runtime.controller.changes:
                    with private_lease(self.store.root / "project-edit.lock"):
                        result, payload = self.store.plan(action, **kwargs)
                        if payload is None:
                            return result
                        if action == "remove":
                            blockers = await self.blockers(kwargs.get("name", ""))
                            if blockers:
                                raise ProjectError("不能取消注册：" + "、".join(sorted(blockers)) + "；请先正常处理。")
                        before = self.store.config.digest
                        try:
                            config = self.store.commit(payload)
                            self.install(config)
                            snapshot = await self.runtime.state.load_routes()
                            if snapshot is not None:
                                await self.runtime.state.save_routes(sanitize_routes(snapshot, config))
                        except BaseException:
                            # A failure after replace must never leave the old runtime authoritative.
                            try:
                                unchanged = load_config(self.store.path, missing=True).digest == before
                            except (OSError, ConfigError):
                                unchanged = False
                            if not unchanged:
                                try:
                                    config = load_config(self.store.path)
                                    self.store.config = config
                                    self.install(config)
                                    snapshot = await self.runtime.state.load_routes()
                                    if snapshot is not None:
                                        await self.runtime.state.save_routes(sanitize_routes(snapshot, config))
                                except BaseException:
                                    self.failed = True
                                    self.runtime.controller.native_ready = False
                                    self.failure.set()
                            raise
                        return result

    async def watch_failure(self):
        await self.failure.wait()
        raise ProjectError("注册持久化与运行态未收敛，停止桥接并保留现有数据。")
