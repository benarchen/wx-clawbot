"""User-only local IPC for project management; never a general command socket."""

import asyncio
import ctypes
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import uuid

from .channels.private import private_directory, private_lease, read_json, write_json
from .config import ConfigError, forbidden
from .operations import consumer_busy, live_instance
from .project_registry import ProjectError, ProjectStore, encoded, stopped_blockers


async def close_writer(writer):
    writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionError, OSError):
        pass  # A peer disconnect must not replace the operation's result or error.


def peer_uid(sock):
    if sys.platform == "darwin":
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise ProjectError("本机项目连接身份不可核验。")
        return uid.value
    return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]


def peer_pid(sock):
    if sys.platform == "darwin":
        # sys/un.h: SOL_LOCAL=0, LOCAL_PEERPID=0x002 (not exposed by Python).
        return sock.getsockopt(0, 0x002)
    return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]


def validate_request(value):
    if (not isinstance(value, dict) or set(value) != {"generation", "config", "operation", "arguments"}
            or not isinstance(value["generation"], str) or not isinstance(value["config"], str)
            or not isinstance(value["operation"], str) or value["operation"] not in {"init", "list", "check", "add", "remove"}
            or not isinstance(value["arguments"], dict)):
        raise ProjectError("本机项目请求格式无效。")
    args = value["arguments"]
    if (set(args) - {"name", "alias", "root", "apply", "confirm", "request"}
            or any(not isinstance(v, str) or len(v) > 4096 or "\0" in v for k, v in args.items() if k != "apply")
            or "apply" in args and type(args["apply"]) is not bool):
        raise ProjectError("本机项目参数无效。")
    allowed = {"list": set(), "check": {"request"}, "add": {"name", "alias", "request"},
               "remove": {"name", "request"}, "init": {"root", "apply", "confirm", "request"}}
    if set(args) - allowed[value["operation"]]:
        raise ProjectError("项目操作不接受这些参数。")
    return value


class ProjectServer:
    def __init__(self, manager, instance):
        self.manager, self.instance = manager, instance
        self.root = manager.store.root
        self.path = self.root / "project-control.sock"
        self.record_path = self.root / "project-control.json"
        self.server = None
        self.jobs = set()
        self.inode = None
        self.closing = False

    async def start(self):
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise ProjectError("旧项目 socket 不是本人私有端点。")
            # Called only while owning the sole bridge consumer.
            self.path.unlink()
        self.server = await asyncio.start_unix_server(self.accept, path=self.path, limit=65537)
        self.path.chmod(0o600)
        self.inode = self.path.stat().st_ino
        write_json(self.record_path, {"version": 1, "generation": self.instance.record["generation"],
                   "config": str(self.manager.store.path)}, replace=self.record_path.exists())

    async def accept(self, reader, writer):
        job = asyncio.current_task()
        if self.closing or len(self.jobs) >= 16:
            await close_writer(writer)
            return
        self.jobs.add(job)
        try:
            payload = await self.response(reader, writer)
            raw = encoded(payload)
            if len(raw) > 65535:
                raw = encoded({"ok": False, "error": "项目结果超过上限，请缩小初始化范围。"})
            writer.write(raw + b"\n")
            await writer.drain()
        except (ConnectionError, OSError):
            pass  # A disconnected caller never replays a management mutation.
        finally:
            try:
                await close_writer(writer)
            finally:
                self.jobs.discard(job)

    async def response(self, reader, writer):
        try:
            if peer_uid(writer.get_extra_info("socket")) != os.getuid():
                raise ProjectError("本机项目连接不属于当前用户。")
            async with asyncio.timeout(5):
                raw = await reader.readline()
            if len(raw) > 65536 or not raw.endswith(b"\n"):
                raise ProjectError("本机项目请求超过上限或不完整。")
            value = validate_request(json.loads(raw))
            if (value["generation"] != self.instance.record["generation"]
                    or value["config"] != str(self.manager.store.path)):
                raise ProjectError("项目实例代次或配置路径不匹配。")
            async with asyncio.timeout(30):
                result = await self.manager.execute(value["operation"], **value["arguments"])
            payload = {"ok": True, "result": result}
        except (ProjectError, ConfigError) as exc:
            payload = {"ok": False, "error": str(exc)}
        except (ValueError, OSError, TimeoutError, asyncio.LimitOverrunError):
            payload = {"ok": False, "error": "项目操作未确认，请核对请求记录，不要自动重试。"}
        return payload

    async def close(self):
        self.closing = True
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        jobs = tuple(self.jobs)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        if self.inode is not None and self.path.exists() and self.path.lstat().st_ino == self.inode:
            self.path.unlink()
        if self.record_path.exists() and read_json(self.record_path).get("generation") == self.instance.record["generation"]:
            self.record_path.unlink()


async def remote_operation(root, config, operation, arguments, instance):
    record = read_json(root / "project-control.json")
    if record != {"version": 1, "generation": instance["generation"], "config": str(config)}:
        raise ProjectError("运行实例不支持项目管理或配置路径不匹配。")
    path = root / "project-control.sock"
    info = path.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ProjectError("项目 socket 权限或归属无效。")
    writer = None
    try:
        async with asyncio.timeout(5):
            reader, writer = await asyncio.open_unix_connection(path, limit=65537)
        if peer_uid(writer.get_extra_info("socket")) != os.getuid():
            raise ProjectError("项目服务身份不可核验。")
        if peer_pid(writer.get_extra_info("socket")) != instance["process"]["pid"]:
            raise ProjectError("项目 socket 不属于准确桥接进程，未发送。")
        current = live_instance(root)
        if current is None or current["generation"] != instance["generation"]:
            raise ProjectError("项目实例代次已变化，未发送。")
        writer.write(encoded({"generation": instance["generation"], "config": str(config),
                              "operation": operation, "arguments": arguments}) + b"\n")
        await writer.drain()
        async with asyncio.timeout(32):
            raw = await reader.readline()
        if len(raw) > 65536:
            raise ProjectError("项目响应超过上限。")
        reply = json.loads(raw)
        if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
            raise ProjectError("项目服务响应无效。")
        if not reply["ok"]:
            raise ProjectError(reply.get("error", "项目操作失败。"))
        return reply["result"]
    except (OSError, ValueError, TimeoutError) as exc:
        if isinstance(exc, ProjectError):
            raise
        raise ProjectError("项目操作未确认；请用 check --request 核对，不要自动重试。\n请求：" + arguments.get("request", "无")) from None
    finally:
        if writer:
            await close_writer(writer)


async def project_operation(config, state_root, operation, **arguments):
    if forbidden(Path(state_root).expanduser().absolute()) or forbidden(Path(config).expanduser().absolute()):
        raise ProjectError("该配置或状态目录不在允许范围内。")
    root = private_directory(Path(state_root).expanduser().absolute())
    config = Path(config).expanduser().absolute()
    if operation not in {"list", "check"}:
        arguments.setdefault("request", "prj-" + uuid.uuid4().hex)
    try:
        instance = live_instance(root)
        if instance is not None:
            return await remote_operation(root, config, operation, arguments, instance)
        if consumer_busy(root):
            raise ProjectError("消费者忙但实例身份未确认，未修改配置。")
        # Startup takes this lock before opening its channel consumer.
        with private_lease(root / "project-edit.lock"), private_lease(root / "channel-consumer.lock"):
            if live_instance(root) is not None:
                raise ProjectError("桥接刚刚启动，请重新核对实例。")
            store = ProjectStore(config, root)
            result, payload = store.plan(operation, **arguments)
            if payload is not None:
                if operation == "remove":
                    blockers = stopped_blockers(root, arguments.get("name", ""))
                    if blockers:
                        raise ProjectError("不能取消注册：" + "、".join(sorted(blockers)) + "；请先正常处理。")
                store.commit(payload)
            return result
    except (OSError, ConfigError) as exc:
        raise ProjectError("项目配置或本机控制入口不可用，请核对状态。") from exc
