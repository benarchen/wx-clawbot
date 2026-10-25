"""Explicit maintenance of this application's settled records; no automatic deletion."""

import math
import sqlite3
import time
from contextlib import closing

from . import schema
from .channels.http import ProtocolError
from .channels.private import private_file, private_lease


TERMINAL = "('completed','failed','interrupted','cancelled')"
SETTLED = "('accepted','superseded')"
SAFE_TASK = f"state IN {TERMINAL} AND NOT EXISTS(SELECT 1 FROM outbox WHERE task_id=tasks.id AND state NOT IN {SETTLED})"


def operations(now):
    body, summary = now - 7 * 86400, now - 30 * 86400
    return (
        ("inbox_bodies", "inbox", f"received_at<? AND phase IN ('handled','stale') AND (text<>'' OR context IS NOT NULL) AND NOT EXISTS(SELECT 1 FROM tasks WHERE source_message_id=inbox.message_id AND NOT ({SAFE_TASK}))", body, "UPDATE inbox SET text='',context=NULL"),
        ("task_inputs", "tasks", f"updated_at<? AND input<>'' AND {SAFE_TASK}", body, "UPDATE tasks SET input=''"),
        ("settled_reply_bodies", "outbox", f"created_at<? AND state IN {SETTLED} AND (text<>'' OR context IS NOT NULL)", body, "UPDATE outbox SET text='',context=NULL"),
        ("handled_interaction_bodies", "interactions", "updated_at<? AND state IN ('resolved','stale') AND (params<>'{}' OR target<>'{}')", body, "UPDATE interactions SET params='{}',target='{}'"),
        ("settled_reply_summaries", "outbox", f"created_at<? AND state IN {SETTLED} AND NOT EXISTS(SELECT 1 FROM tasks WHERE tasks.id=outbox.task_id AND tasks.state NOT IN {TERMINAL})", summary, "DELETE FROM outbox"),
        ("terminal_task_summaries", "tasks", f"updated_at<? AND {SAFE_TASK}", summary, "DELETE FROM tasks"),
        ("handled_interaction_summaries", "interactions", "updated_at<? AND state IN ('resolved','stale')", summary, "DELETE FROM interactions"),
    )


def maintain(root, credentials, *, apply=False, now=None):
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or now <= 0:
        raise ValueError("A finite positive retention clock required")
    root = root.expanduser().absolute()
    private_file(root / "runtime.sqlite3")
    if not apply:
        with closing(sqlite3.connect((root / "runtime.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
            schema.validate(db, credentials, versions=(2,))
            counts = {label: db.execute(f"SELECT count(*) FROM {table} WHERE {where}", (cutoff,)).fetchone()[0]
                      for label, table, where, cutoff, _ in operations(now)}
        return {"status": "maintenance_plan", "eligible_rows": counts, "body_days": 7, "summary_days": 30,
                "inbox_deduplication_tombstones_preserved": True, "applied": False}
    with private_lease(root / "channel-consumer.lock"), closing(sqlite3.connect(root / "runtime.sqlite3", isolation_level=None)) as db:
        schema.validate(db, credentials, versions=(2,))
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        changed = {}
        try:
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ProtocolError("Runtime integrity check failed before maintenance")
            for label, _, where, cutoff, action in operations(now):
                changed[label] = db.execute(action + " WHERE " + where, (cutoff,)).rowcount
            # Attempt contexts belong to settled replies only; uncertain deliveries
            # retain the original context and content for operator inspection.
            db.execute(f"""UPDATE delivery_attempts SET context='' WHERE outbox_id IN
                (SELECT id FROM outbox WHERE created_at<? AND state IN {SETTLED})""", (now - 7 * 86400,))
            schema.validate(db, credentials, versions=(2,))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return {"status": "maintenance_applied", "changed_rows": changed,
            "inbox_deduplication_tombstones_preserved": True, "applied": True}
