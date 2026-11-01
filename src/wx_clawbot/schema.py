"""Explicit, backed-up upgrade of this application's ledger; never auto-migrate data."""

import hashlib
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from .channels.http import ProtocolError
from .channels.private import private_directory, private_file, private_lease


APPLICATION_ID = 0x57585254
VERSION = 4
V1_COLUMNS = {
    "channel": {"id", "bot", "owner", "cursor"},
    "inbox": {"message_id", "text", "context", "created_ms", "seq", "received_at", "phase", "conflict"},
    "reply_context": {"id", "token", "created_ms", "seq"},
    "tasks": {"id", "source_message_id", "client_id", "target", "thread_id", "input", "state", "queue_id", "turn_id", "created_at", "updated_at"},
    "outbox": {"id", "text", "priority", "state", "context", "server_id", "task_id", "kind", "created_at"},
}
UPGRADE = (
    "ALTER TABLE inbox ADD COLUMN body_sha256 TEXT",
    "ALTER TABLE outbox ADD COLUMN body_sha256 TEXT",
    """CREATE TABLE routes (id INTEGER PRIMARY KEY CHECK(id=1),snapshot TEXT NOT NULL,
        updated_at REAL NOT NULL,FOREIGN KEY(id) REFERENCES channel(id))""",
    """CREATE TABLE interactions (public_id TEXT PRIMARY KEY,native_key TEXT NOT NULL,
        generation TEXT NOT NULL,thread_id TEXT NOT NULL,turn_id TEXT NOT NULL,method TEXT NOT NULL,
        params TEXT NOT NULL,target TEXT NOT NULL,deadline REAL NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL,
        updated_at REAL NOT NULL,UNIQUE(generation,native_key))""",
    """CREATE TABLE delivery_attempts (outbox_id TEXT NOT NULL,number INTEGER NOT NULL,
        client_id TEXT NOT NULL,context TEXT NOT NULL,state TEXT NOT NULL,server_id TEXT,
        started_at REAL,finished_at REAL,error_code TEXT,authorization TEXT,
        provenance TEXT NOT NULL CHECK(provenance IN ('legacy-v1','runtime-v2')),
        PRIMARY KEY(outbox_id,number),FOREIGN KEY(outbox_id) REFERENCES outbox(id) ON DELETE CASCADE)""",
    "CREATE UNIQUE INDEX delivery_active ON delivery_attempts(outbox_id) WHERE state='sending'",
    "CREATE INDEX task_native_client ON tasks(thread_id,client_id)",
    "CREATE INDEX delivery_pending ON outbox(state,priority)",
)
V2_COLUMNS = {
    "routes": {"id", "snapshot", "updated_at"},
    "interactions": {"public_id", "native_key", "generation", "thread_id", "turn_id", "method", "params", "target", "deadline", "state", "created_at", "updated_at"},
    "delivery_attempts": {"outbox_id", "number", "client_id", "context", "state", "server_id", "started_at", "finished_at", "error_code", "authorization", "provenance"},
}
V3_COLUMNS = {
    "attachments": {"id", "message_id", "item_index", "task_id", "media", "state", "filename",
                    "sha256", "byte_size", "format", "width", "height", "error_code", "created_at", "updated_at"},
}
IMAGE_UPGRADE = (
    "ALTER TABLE inbox ADD COLUMN content TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE tasks ADD COLUMN input_items TEXT NOT NULL DEFAULT '[]'",
    """CREATE TABLE attachments (id TEXT PRIMARY KEY,message_id TEXT NOT NULL,item_index INTEGER NOT NULL,
        task_id TEXT,media TEXT NOT NULL,state TEXT NOT NULL,filename TEXT,sha256 TEXT,byte_size INTEGER,
        format TEXT,width INTEGER,height INTEGER,error_code TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL,
        UNIQUE(message_id,item_index),FOREIGN KEY(message_id) REFERENCES inbox(message_id),
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL)""",
    "CREATE INDEX attachment_task ON attachments(task_id,state)",
)
PERFORMANCE_UPGRADE = (
    "CREATE INDEX reply_task_kind ON outbox(task_id,kind)",
    "CREATE INDEX task_native_turn ON tasks(thread_id,turn_id)",
    "CREATE INDEX task_active ON tasks(state) WHERE state NOT IN ('completed','failed','interrupted','cancelled')",
)


class UpgradeRequired(ProtocolError):
    pass


def validate(db, credentials, *, versions=(1, 2, 3, VERSION)):
    if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ProtocolError("Database is not this application's runtime ledger")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in versions:
        raise ProtocolError("Unsupported runtime schema version")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    columns_by_table = V1_COLUMNS | (V2_COLUMNS if version >= 2 else {}) | (V3_COLUMNS if version >= 3 else {})
    expected = set(columns_by_table)
    if tables != expected:
        raise ProtocolError("Runtime tables differ from the verified schema")
    for table, columns in columns_by_table.items():
        actual = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        required = columns | ({"body_sha256"} if table in {"inbox", "outbox"} and version >= 2 else set())
        if version >= 3:
            required = required | ({"content"} if table == "inbox" else {"input_items"} if table == "tasks" else set())
        if actual != required:
            raise ProtocolError("Runtime columns differ from the verified schema")
    if db.execute("SELECT bot,owner FROM channel WHERE id=1").fetchone() != (credentials.bot_id, credentials.owner_id):
        raise ProtocolError("Runtime ledger belongs to another binding")
    if version >= 2:
        for table in ("inbox", "outbox"):
            if db.execute(f"SELECT 1 FROM {table} WHERE body_sha256 IS NULL OR length(body_sha256)<>64 LIMIT 1").fetchone():
                raise ProtocolError("Runtime message digest is missing")
    if version >= 4:
        indexes = {row[0]: row[1] for row in db.execute("SELECT name,sql FROM sqlite_master WHERE type='index'")}
        for statement in PERFORMANCE_UPGRADE:
            name = statement.split()[2]
            if indexes.get(name) != statement:
                raise ProtocolError("Runtime performance index differs from the verified schema")
    return version


def _text_steps(db, credentials):
    for statement in UPGRADE:
        db.execute(statement)
    for table, key in (("inbox", "message_id"), ("outbox", "id")):
        for identity, text in db.execute(f"SELECT {key},text FROM {table}"):
            db.execute(f"UPDATE {table} SET body_sha256=? WHERE {key}=?", (hashlib.sha256(text.encode()).hexdigest(), identity))
    # Preserve the old observation as a legacy attempt. Exact HTTP start/end times
    # were not recorded in v1 and must not be reconstructed from creation time.
    for event_id, context, state, server_id in db.execute(
        "SELECT id,context,state,server_id FROM outbox WHERE state IN ('sending','accepted','unknown','rejected')"
    ):
        if not context:
            raise ProtocolError("Legacy send has no recorded context")
        client_id = "wx-reply-" + uuid.uuid5(uuid.NAMESPACE_URL, credentials.bot_id + "\0" + event_id).hex
        db.execute("""INSERT INTO delivery_attempts(outbox_id,number,client_id,context,state,server_id,provenance)
            VALUES(?,0,?,?,?,?, 'legacy-v1')""", (event_id, client_id, context, state, server_id))
    db.execute("PRAGMA user_version=2")
    validate(db, credentials, versions=(2,))


def apply_steps(db, credentials):
    """Caller owns the transaction and has either a new file or a verified backup."""
    version = validate(db, credentials)
    if version not in (1, 2, 3) or not db.in_transaction:
        raise ProtocolError("A supported older schema and an explicit transaction required")
    if version == 1:
        _text_steps(db, credentials)
    for statement in IMAGE_UPGRADE if version < 3 else ():
        db.execute(statement)
    for statement in PERFORMANCE_UPGRADE:
        db.execute(statement)
    db.execute("ANALYZE tasks")
    db.execute("ANALYZE outbox")
    db.execute(f"PRAGMA user_version={VERSION}")
    validate(db, credentials, versions=(VERSION,))


def _root(root):
    if not root.is_dir():
        raise ProtocolError("Existing private state directory required")
    root = private_directory(root)
    private_file(root / "runtime.sqlite3")
    return root


def inspect(root: Path, credentials):
    root = _root(root)
    with closing(sqlite3.connect((root / "runtime.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        version = validate(db, credentials)
        tables = V1_COLUMNS | (V2_COLUMNS if version >= 2 else {}) | (V3_COLUMNS if version >= 3 else {})
        counts = {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in tables}
    return {"status": "current" if version == VERSION else "upgrade_available", "from_version": version,
            "to_version": VERSION, "row_counts": counts, "requires_stopped_consumer": True,
            "add_tables": (["routes", "interactions", "delivery_attempts"] if version == 1 else []) + (["attachments"] if version < 3 else []),
            "add_columns": (["inbox.body_sha256", "outbox.body_sha256"] if version == 1 else [])
                           + (["inbox.content", "tasks.input_items"] if version < 3 else []),
            "add_indexes": [s.split()[2] for s in PERFORMANCE_UPGRADE] if version < VERSION else [],
            "data_deleted": False}


def upgrade(root: Path, credentials):
    root = _root(root)
    with private_lease(root / "channel-consumer.lock"), closing(sqlite3.connect(root / "runtime.sqlite3", isolation_level=None, timeout=1)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        source_version = validate(db, credentials)
        if source_version == VERSION:
            return {"status": "current", "version": VERSION, "data_deleted": False}
        db.execute("BEGIN IMMEDIATE")
        backup = None
        try:
            validate(db, credentials, versions=(source_version,))
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ProtocolError("Runtime integrity check failed before upgrade")
            folder = private_directory(root / "backups")
            backup = folder / (f"runtime-v{source_version}-" + uuid.uuid4().hex + ".sqlite3")
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            deadline = time.monotonic() + 10
            def progress(*_):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Backup did not complete within its bound")
            # A separate reader sees the committed snapshot while this writer
            # prevents another schema/data writer from changing it during backup.
            with closing(sqlite3.connect((root / "runtime.sqlite3").as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target, pages=100, progress=progress, sleep=.01)
                if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ProtocolError("Backup integrity check failed")
                validate(target, credentials, versions=(source_version,))
                tables = V1_COLUMNS | (V2_COLUMNS if source_version >= 2 else {}) | (V3_COLUMNS if source_version >= 3 else {})
                for name in tables:
                    if target.execute(f"SELECT count(*) FROM {name}").fetchone() != db.execute(f"SELECT count(*) FROM {name}").fetchone():
                        raise ProtocolError("Backup row count differs from frozen source")
            private_file(backup)
            apply_steps(db, credentials)
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        return {"status": "upgraded", "from_version": source_version, "to_version": VERSION,
                "backup": str(backup.relative_to(root)), "backup_verified": True, "data_deleted": False}
