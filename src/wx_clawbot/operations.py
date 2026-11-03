"""Local operator actions; never import or invoke native execution here."""

import asyncio
import fcntl
import json
import os
import sqlite3
import stat
import uuid
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from . import schema
from .channels.http import ProtocolError
from .channels.private import load_credentials, private_file, private_lease, read_json, write_json
from .hosts.process import read_process
from .runtime_state import prepare_reply_retry


def existing_root(root):
    root = root.expanduser().absolute()
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProtocolError("Existing user-owned private directory with mode 0700 required")
    return root


def consumer_busy(root):
    path = root / "channel-consumer.lock"
    if not path.exists():
        return False
    private_file(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
    finally:
        os.close(fd)


def live_instance(root):
    path = root / "foreground.json"
    if not path.exists():
        return None
    record = read_json(path)
    identity = record.get("process")
    if not isinstance(identity, dict) or record.get("version") != 1:
        return None
    current = read_process(identity.get("pid"))
    if (current is None or json.loads(json.dumps(asdict(current))) != identity
            or record.get("root") != str(root.resolve())
            or not isinstance(record.get("generation"), str) or len(record["generation"]) != 32):
        return None
    return record if consumer_busy(root) else None


class StopRequested(Exception):
    pass


class ForegroundInstance:
    """Created only after the runtime consumer lock is acquired; no process signals."""

    def __init__(self, root):
        self.root = root
        process = read_process(os.getpid())
        if process is None or not consumer_busy(root):
            raise ProtocolError("Cannot establish foreground identity")
        self.record = {"version": 1, "root": str(root.resolve()),
                       "generation": uuid.uuid4().hex, "process": asdict(process)}
        path = root / "foreground.json"
        write_json(path, self.record, replace=path.exists())

    def health(self, components):
        self.record["components"] = components
        write_json(self.root / "foreground.json", self.record, replace=True)

    async def watch_stop(self):
        while True:
            path = self.root / "foreground-stop.json"
            if path.exists() and read_json(path).get("generation") == self.record["generation"]:
                raise StopRequested()
            await asyncio.sleep(0.25)

    def close(self):
        for name in ("foreground.json", "foreground-stop.json"):
            path = self.root / name
            if path.exists() and read_json(path).get("generation") == self.record["generation"]:
                path.unlink()


def request_stop(root):
    root = existing_root(root)
    record = live_instance(root)
    if record is None:
        return {"status": "no_verified_foreground", "message": "没有可核验的前台实例；旧入口请在原终端按 Ctrl+C。"}
    path = root / "foreground-stop.json"
    write_json(path, {"generation": record["generation"]}, replace=path.exists())
    return {"status": "stop_requested", "message": "已请求桥接自行退出；用 status 核对完成，原生终端保留。"}


def status(root):
    root = existing_root(root)
    credentials = load_credentials(root / "credentials.json")
    busy, instance = consumer_busy(root), live_instance(root)
    report = {"status": "running" if instance else ("consumer_unverified" if busy else "stopped"),
              "private_directory_mode": "0700", "credentials_mode": "0600", "consumer_busy": busy}
    managed_path = root / "managed.json"
    if managed_path.exists():
        try:
            managed = read_json(managed_path)
            if (managed.get("version") != 1 or not isinstance(managed.get("state"), str)
                    or managed["state"] not in {"running", "exited"}):
                raise ProtocolError("Invalid managed record")
            current = bool(instance and managed.get("process") == instance["process"])
            report["supervision"] = {
                "state": "running" if current and managed["state"] == "running" else
                         ("exited" if managed["state"] == "exited" else "previous_exit_unobserved"),
                "previous_exit_unobserved": managed.get("previous_exit_unobserved") is True,
                "last_exit_code": managed.get("exit_code") if type(managed.get("exit_code")) is int
                                  and 0 <= managed["exit_code"] <= 255 else None,
            }
        except (OSError, ProtocolError):
            report["supervision"] = {"state": "unavailable"}
    if instance:
        # Return only the small known state vocabulary, never arbitrary private
        # instance fields. running describes the consumer, not its dependencies.
        components = instance.get("components", {})
        report["components"] = {}
        for name in ("host", "native"):
            value = components.get(name, {})
            state = value.get("state")
            phase = value.get("phase")
            allowed = {"not_running", "connecting", "verifying", "ready", "unavailable", "stopped"}
            report["components"][name] = {"state": state if state in allowed else "unknown"}
            if name == "host" and phase in allowed | {"launch", "authentication", "discover", "changed", "rpc", "reader", "process", "connect"}:
                report["components"][name]["phase"] = phase
    path = root / "runtime.sqlite3"
    if not path.exists():
        report["ledger"] = "not_initialized"
        return report
    private_file(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.execute("BEGIN")
        report["schema_version"] = schema.validate(db, credentials)
        if report["schema_version"] >= 5:
            report["occupancy"] = dict(db.execute("SELECT state,count(*) FROM task_occupancy GROUP BY state"))
        report["tasks"] = dict(db.execute("SELECT state,count(*) FROM tasks GROUP BY state"))
        report["replies"] = dict(db.execute("SELECT state,count(*) FROM outbox GROUP BY state"))
        report["unsettled_reply_ids"] = [row[0] for row in db.execute(
            "SELECT id FROM outbox WHERE state IN ('unknown','rejected') ORDER BY rowid LIMIT 100")]
        report["unsettled_ids_truncated"] = sum(report["replies"].get(x, 0) for x in ("unknown", "rejected")) > 100
        report["runtime_file_mode"] = "0600"
    return report


def retry_delivery(root, event_id, *, apply=False, confirm_unknown=False):
    root = existing_root(root)
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise ValueError("Bounded event identity required")
    credentials = load_credentials(root / "credentials.json")
    path = root / "runtime.sqlite3"
    private_file(path)
    # Default inspection never opens RuntimeState: that would mutate unrelated
    # lifecycle states and stale pending interactions even without a retry.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        schema.validate(db, credentials, versions=(2, schema.VERSION))
        row = db.execute("SELECT state,kind,task_id FROM outbox WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise ProtocolError("Delivery event is absent")
        count = db.execute("SELECT count(*) FROM delivery_attempts WHERE outbox_id=?", (event_id,)).fetchone()[0]
    report = {"status": "retry_plan", "event_id": event_id, "delivery_state": row[0],
              "kind": row[1], "attempt_count": count, "possible_duplicate": row[0] == "unknown", "applied": False}
    if apply:
        with private_lease(root / "channel-consumer.lock"), closing(sqlite3.connect(path, isolation_level=None, timeout=1)) as db:
            schema.validate(db, credentials, versions=(2, schema.VERSION))
            number = prepare_reply_retry(db, credentials, event_id, confirm_unknown)
        report.update(status="retry_prepared", applied=True, next_attempt=number,
                      message="仅准备再次投递；启动前台后发送，不重新执行任务。")
    return report
