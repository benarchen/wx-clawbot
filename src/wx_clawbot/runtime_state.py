"""Private foreground ledger; native execution and delivery have separate outcomes."""

import json
import hashlib
import math
import sqlite3
import time
import uuid
from contextlib import closing

from .channels.http import ProtocolError
from .channels.private import private_file
from .channels.state import ChannelState
from . import schema
from .output import display_text, display_segments, LINE_BREAK


class RuntimeState(ChannelState):
    APPLICATION_ID = schema.APPLICATION_ID

    def _open(self):
        new = self._open_database()
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        if new:
            cursor, context = "", None
            diagnostic = self.path.parent / "state.sqlite3"
            if diagnostic.exists():
                private_file(diagnostic)
                with closing(sqlite3.connect(diagnostic.as_uri() + "?mode=ro", uri=True)) as previous:
                    if previous.execute("PRAGMA application_id").fetchone()[0] != ChannelState.APPLICATION_ID:
                        raise ProtocolError("Diagnostic cursor source is not owned by this application")
                    row = previous.execute("SELECT bot,owner,cursor FROM channel WHERE id=1").fetchone()
                    if row is None or row[:2] != (self.credentials.bot_id, self.credentials.owner_id):
                        raise ProtocolError("Diagnostic cursor belongs to another binding")
                    cursor = row[2]
                    context = previous.execute("SELECT token,created_ms,seq FROM reply_context WHERE id=1").fetchone()
            self.db.executescript(f"""
                PRAGMA application_id={self.APPLICATION_ID};
                PRAGMA user_version=1;
                PRAGMA journal_mode=WAL;
                CREATE TABLE channel (id INTEGER PRIMARY KEY CHECK(id=1),bot TEXT NOT NULL,
                    owner TEXT NOT NULL,cursor TEXT NOT NULL DEFAULT '');
                CREATE TABLE inbox (message_id TEXT PRIMARY KEY,text TEXT NOT NULL,context TEXT,
                    created_ms INTEGER NOT NULL,seq INTEGER NOT NULL,received_at REAL NOT NULL,
                    phase TEXT NOT NULL,conflict INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE reply_context (id INTEGER PRIMARY KEY CHECK(id=1),token TEXT NOT NULL,
                    created_ms INTEGER NOT NULL,seq INTEGER NOT NULL);
                CREATE TABLE tasks (id TEXT PRIMARY KEY,source_message_id TEXT UNIQUE,client_id TEXT UNIQUE,
                    target TEXT NOT NULL,thread_id TEXT NOT NULL,input TEXT NOT NULL,state TEXT NOT NULL,
                    queue_id TEXT,turn_id TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);
                CREATE TABLE outbox (id TEXT PRIMARY KEY,text TEXT NOT NULL,priority INTEGER NOT NULL,
                    state TEXT NOT NULL,context TEXT,server_id TEXT,task_id TEXT,kind TEXT NOT NULL,
                    created_at REAL NOT NULL);
            """)
            self.db.execute("INSERT INTO channel VALUES(1,?,?,?)",
                            (self.credentials.bot_id, self.credentials.owner_id, cursor))
            if context:
                self.db.execute("INSERT INTO reply_context VALUES(1,?,?,?)", context)
            # Only the brand-new file created by this call may be initialized here.
            self.db.execute("BEGIN IMMEDIATE")
            try:
                schema.apply_steps(self.db, self.credentials)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        if schema.validate(self.db, self.credentials) != schema.VERSION:
            raise schema.UpgradeRequired("Runtime schema 1 requires an explicitly authorized upgrade")
        # No task, inbound command or uncertain HTTP send is replayed on restart.
        self.db.execute("UPDATE tasks SET state='unknown' WHERE state IN ('prepared','dispatching','queued','running','waiting_interaction','stopping')")
        self.db.execute("UPDATE outbox SET state='unknown' WHERE state='sending'")
        self.db.execute("UPDATE delivery_attempts SET state='unknown' WHERE state='sending'")
        self.db.execute("UPDATE inbox SET phase='stale' WHERE phase='runtime'")
        self._stale_interactions()

    def _prior_matches(self, message):
        row = self.db.execute("SELECT body_sha256 FROM inbox WHERE message_id=?", (message.message_id,)).fetchone()
        return None if row is None else row[0] == hashlib.sha256(message.text.encode()).hexdigest()

    def _insert_message(self, message, phase):
        self.db.execute("""INSERT INTO inbox(message_id,text,context,created_ms,seq,received_at,phase,body_sha256)
            VALUES(?,?,?,?,?,?,?,?)""", (message.message_id, message.text, message.context_token,
                message.created_ms, message.sequence, time.time(), phase, hashlib.sha256(message.text.encode()).hexdigest()))

    async def handled(self, message_id):
        await self._call(lambda: self.db.execute("UPDATE inbox SET phase='handled' WHERE message_id=?", (message_id,)))

    async def admission_budget(self):
        def read():
            count, size = self.db.execute("""SELECT count(*),COALESCE(sum(length(CAST(text AS BLOB))),0)
                FROM outbox WHERE state IN ('pending','sending','unknown','rejected')""").fetchone()
            return {"allowed": count < 1000 and size < 8 * 1024 * 1024,
                    "unsettled_replies": count, "unsettled_bytes": size}
        return await self._call(read)

    async def save_routes(self, snapshot):
        if not isinstance(snapshot, dict):
            raise ValueError("Explicit route snapshot required")
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Route snapshot exceeds its bound")
        await self._call(lambda: self.db.execute("""INSERT INTO routes VALUES(1,?,?)
            ON CONFLICT(id) DO UPDATE SET snapshot=excluded.snapshot,updated_at=excluded.updated_at""", (encoded, time.time())))

    async def load_routes(self):
        def read():
            row = self.db.execute("SELECT snapshot FROM routes WHERE id=1").fetchone()
            if row is None:
                return None
            value = json.loads(row[0])
            if not isinstance(value, dict):
                raise ProtocolError("Stored route snapshot is invalid")
            return value
        return await self._call(read)

    async def record_interaction(self, record, *, generation, target, expires_at):
        if (any(not isinstance(getattr(record, key, None), str) or not getattr(record, key)
                or len(getattr(record, key)) > 128 for key in ("public_id", "thread_id", "turn_id", "method"))
                or any(char in record.public_id for char in "*?[]")
                or type(record.native_id) not in (int, str) or not isinstance(generation, str) or not 1 <= len(generation) <= 128
                or not isinstance(target, dict) or target.get("thread_id") != record.thread_id
                or type(expires_at) not in (int, float) or not math.isfinite(expires_at) or expires_at <= 0
                or record.state not in {"pending", "sending", "awaiting_native", "resolved", "stale", "unknown"}):
            raise ValueError("Connection, target and bounded interaction state required")
        key = json.dumps(["int" if type(record.native_id) is int else "str", record.native_id], ensure_ascii=False)
        params = json.dumps(record.params, ensure_ascii=False, sort_keys=True, allow_nan=False)
        destination = json.dumps(target, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(params.encode()) > 1024 * 1024 or len(destination.encode()) > 65536:
            raise ValueError("Interaction payload exceeds its bound")
        identity = (key, generation, record.thread_id, record.turn_id, record.method, params, destination, expires_at)
        public_id, state = record.public_id, record.state
        def save():
            existing = self.db.execute("""SELECT native_key,generation,thread_id,turn_id,method,params,target,deadline,state
                FROM interactions WHERE public_id=?""", (public_id,)).fetchone()
            if existing:
                if existing[:8] != identity:
                    raise ProtocolError("Interaction identity or displayed operation changed")
                if existing[8] == "resolved" or existing[8] == "stale" and state != "resolved":
                    return existing[8]  # A late write cannot revive a handled/stale request.
                if existing[8] == "unknown" and state in {"pending", "sending", "awaiting_native"}:
                    return "unknown"
                self.db.execute("UPDATE interactions SET state=?,updated_at=? WHERE public_id=?",
                                (state, time.time(), public_id))
            else:
                now = time.time()
                self.db.execute("""INSERT INTO interactions(public_id,native_key,generation,thread_id,turn_id,method,
                    params,target,deadline,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (public_id, *identity, state, now, now))
            return state
        return await self._call(save)

    async def interaction_rows(self, *, generation=None):
        def read():
            query = "SELECT public_id,generation,thread_id,turn_id,method,target,deadline,state FROM interactions"
            values = ()
            if generation is not None:
                query += " WHERE generation=?"
                values = (generation,)
            keys = ("public_id", "generation", "thread_id", "turn_id", "method", "target", "deadline", "state")
            result = []
            for row in self.db.execute(query + " ORDER BY created_at DESC LIMIT 256", values):
                item = dict(zip(keys, row));item["target"] = json.loads(item["target"]);result.append(item)
            return result
        return await self._call(read)

    def _stale_interactions(self, generation=None):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            clause = "state NOT IN ('resolved','stale')"
            args = ()
            if generation is not None:
                clause += " AND generation=?"
                args = (generation,)
                public_ids = [row[0] for row in self.db.execute("SELECT public_id FROM interactions WHERE generation=?", args)]
            self.db.execute("UPDATE interactions SET state='stale',updated_at=? WHERE " + clause, (time.time(), *args))
            # v1 prompts had no interaction table. Their generated IDs still identify
            # them, and the old connection cannot accept a reply after reopening.
            if generation is None:
                self.db.execute("""UPDATE outbox SET state='superseded' WHERE state='pending'
                    AND id GLOB 'r-[0-9a-f]*-prompt*'""")
            else:
                for public_id in public_ids:
                    self.db.execute("UPDATE outbox SET state='superseded' WHERE state='pending' AND id GLOB ?", (public_id + "-prompt*",))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    async def stale_interactions(self, generation=None):
        await self._call(self._stale_interactions, generation)

    async def task_intent(self, message_id, target: dict, text: str):
        if (not isinstance(message_id, str) or not message_id or not isinstance(target, dict)
                or not isinstance(target.get("thread_id"), str) or not target["thread_id"]
                or not isinstance(text, str) or not text.strip() or len(text) > 32000):
            raise ValueError("Stable message, target and bounded task required")
        identity = uuid.uuid5(uuid.NAMESPACE_URL, self.credentials.bot_id + "\0" + message_id).hex
        task_id, client_id = "t-" + identity, "wx-task-" + identity
        encoded = json.dumps(target, ensure_ascii=False, sort_keys=True, allow_nan=False)
        def insert():
            existing = self.db.execute("SELECT target,input FROM tasks WHERE source_message_id=?", (message_id,)).fetchone()
            if existing:
                if existing != (encoded, text):
                    raise ProtocolError("Source message cannot be retargeted or rewritten")
                return None
            row = self.db.execute("SELECT conflict,phase FROM inbox WHERE message_id=?", (message_id,)).fetchone()
            if row != (0, "runtime"):
                raise ProtocolError("Task must originate from a fresh validated runtime message")
            if self.db.execute("SELECT count(*) FROM tasks WHERE state NOT IN ('completed','failed','interrupted','cancelled')").fetchone()[0] >= 128:
                raise ProtocolError("Unresolved task admission bound reached")
            now = time.time()
            self.db.execute("INSERT INTO tasks(id,source_message_id,client_id,target,thread_id,input,state,created_at,updated_at) VALUES(?,?,?,?,?,?,'prepared',?,?)",
                            (task_id, message_id, client_id, encoded, target["thread_id"], text, now, now))
            return {"id": task_id, "client_id": client_id, "target": target, "state": "prepared"}
        return await self._call(insert)

    async def task_update(self, task_id, state, *, queue_id=None, turn_id=None):
        if state not in {"received", "dispatching", "queued", "running", "waiting_interaction", "stopping", "unknown"}:
            raise ValueError("Explicit nonterminal native task state required")
        def update():
            previous = self.db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
            if previous and previous[0] in {"completed", "failed", "interrupted", "cancelled"}:
                return False
            if previous and ((state == "queued" and previous[0] in {"running", "waiting_interaction", "stopping"})
                             or (state in {"running", "waiting_interaction"} and previous[0] == "stopping")):
                return False  # A delayed queue ACK must not regress an observed native turn.
            result = self.db.execute("""UPDATE tasks SET state=?,queue_id=COALESCE(?,queue_id),
                turn_id=COALESCE(?,turn_id),updated_at=? WHERE id=? AND state NOT IN ('completed','failed','interrupted','cancelled')""",
                                     (state, queue_id, turn_id, time.time(), task_id))
            if result.rowcount != 1:
                raise ProtocolError("Task is missing or already terminal")
            return True
        return await self._call(update)

    async def external_task(self, target, turn_id, *, native_client_id=None):
        if not isinstance(target, dict) or not target.get("thread_id") or not isinstance(turn_id, str) or not turn_id:
            raise ValueError("Verified original thread and exact native turn required")
        identity = uuid.uuid5(uuid.NAMESPACE_URL, target["thread_id"] + "\0" + turn_id).hex
        destination = dict(target, source="external", native_client_id=native_client_id)
        encoded = json.dumps(destination, ensure_ascii=False, sort_keys=True, allow_nan=False)
        def insert():
            row = self.db.execute("SELECT target FROM tasks WHERE id=?", ("e-" + identity,)).fetchone()
            if row:
                if json.loads(row[0]) != destination:
                    raise ProtocolError("External native turn identity changed")
                return "e-" + identity
            if self.db.execute("SELECT count(*) FROM tasks WHERE state NOT IN ('completed','failed','interrupted','cancelled')").fetchone()[0] >= 128:
                raise ProtocolError("Unresolved task bound prevents adopting another external turn")
            now = time.time()
            # client_id is explicitly local for this external row, not a claimed
            # native submission receipt. No fabricated inbox or task text is stored.
            self.db.execute("""INSERT INTO tasks(id,client_id,target,thread_id,input,state,turn_id,created_at,updated_at)
                VALUES(?,?,?,?,'','running',?,?,?)""", ("e-" + identity, "wx-external-" + identity,
                    encoded, target["thread_id"], turn_id, now, now))
            return "e-" + identity
        task_id = await self._call(insert)
        return await self.tasks(task_id=task_id)

    @staticmethod
    def _task(row):
        if row is None:
            return None
        keys = ("id", "source_message_id", "client_id", "target", "thread_id", "input", "state", "queue_id", "turn_id")
        result = dict(zip(keys, row))
        result["target"] = json.loads(result["target"])
        return result

    async def tasks(self, *, task_id=None, client_id=None, active_only=False, native_turn=None):
        def read():
            query = "SELECT id,source_message_id,client_id,target,thread_id,input,state,queue_id,turn_id FROM tasks"
            if task_id is not None:
                return self._task(self.db.execute(query + " WHERE id=?", (task_id,)).fetchone())
            if client_id is not None:
                return self._task(self.db.execute(query + " WHERE client_id=?", (client_id,)).fetchone())
            if native_turn is not None:
                rows = self.db.execute(query + " WHERE thread_id=? AND turn_id=?", native_turn).fetchall()
                if len(rows) > 1:
                    raise ProtocolError("Native turn has multiple local task associations")
                return self._task(rows[0]) if rows else None
            if active_only:
                rows = list(self.db.execute(query + " WHERE state NOT IN ('completed','failed','interrupted','cancelled') ORDER BY rowid LIMIT 129"))
                if len(rows) > 128:
                    raise ProtocolError("Unresolved task bound exceeded; do not use a partial admission view")
                return [self._task(row) for row in rows]
            return [self._task(row) for row in self.db.execute(query + " ORDER BY created_at DESC LIMIT 100")]
        return await self._call(read)

    def _queue_reply(self, event_id, text, priority, task_id=None, kind="reply"):
        if (not isinstance(event_id, str) or not event_id or len(event_id) > 128
                or not isinstance(text, str) or not text.strip() or len(text) > 8000
                or type(priority) is not int or not 0 <= priority <= 10):
            raise ValueError("Bounded stable reply identity and text required")
        digest = hashlib.sha256(text.encode()).hexdigest()
        existing = self.db.execute("SELECT body_sha256 FROM outbox WHERE id=?", (event_id,)).fetchone()
        if existing:
            if existing[0] != digest:
                raise ProtocolError("Reply identity cannot be reused for different content")
            return False
        if task_id and kind in {"accepted", "progress"}:
            task = self.db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task[0] in {"completed", "failed", "interrupted", "cancelled"}:
                return False
            if task[0] == "stopping" or kind == "accepted" and task[0] in {"running", "waiting_interaction"}:
                return False
            if kind == "progress":
                self.db.execute("UPDATE outbox SET state='superseded' WHERE task_id=? AND state='pending' AND kind IN ('accepted','progress')", (task_id,))
        self.db.execute("INSERT INTO outbox(id,text,priority,state,task_id,kind,created_at,body_sha256) VALUES(?,?,?,'pending',?,?,?,?)",
                        (event_id, text, priority, task_id, kind, time.time(), digest))
        return True

    async def queue_reply(self, event_id, text, *, priority=5, task_id=None, kind="reply"):
        text = display_text(text)
        def queue():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                result = self._queue_reply(event_id, text, priority, task_id, kind)
                self.db.execute("COMMIT")
                return result
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return await self._call(queue)

    async def task_finish(self, task_id, state, text, *, turn_id=None, only_if=None, deliver=True, reply_priority=1):
        if state not in {"completed", "failed", "interrupted", "cancelled"}:
            raise ValueError("Explicit terminal native task state required")
        if not isinstance(text, str) or not text.strip() or len(text) > 512000:
            raise ValueError("Bounded native result required")
        def finish():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    raise ProtocolError("Task identity is missing")
                if row[0] in {"completed", "failed", "interrupted", "cancelled"}:
                    return False
                if only_if is not None and row[0] not in only_if:
                    return False
                self.db.execute("UPDATE tasks SET state=?,turn_id=COALESCE(?,turn_id),updated_at=? WHERE id=?",
                                (state, turn_id, time.time(), task_id))
                self.db.execute("UPDATE outbox SET state='superseded' WHERE task_id=? AND state='pending' AND kind IN ('accepted','progress')", (task_id,))
                chunks = display_segments(text) if deliver else []
                for index, chunk in enumerate(chunks, 1):
                    prefix = f"〔{index}/{len(chunks)}〕{task_id}{LINE_BREAK}" if len(chunks) > 1 else ""
                    self._queue_reply(f"{task_id}-final-{index}", display_text(prefix + chunk), reply_priority, task_id, "final")
                self.db.execute("COMMIT")
                return True
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            finally:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
        return await self._call(finish)

    async def claim_reply(self):
        def claim():
            context = self.db.execute("SELECT token FROM reply_context WHERE id=1").fetchone()
            if not context:
                return None
            row = self.db.execute("""SELECT o.id,o.text FROM outbox o WHERE o.state='pending'
                AND (o.kind!='final' OR NOT EXISTS(SELECT 1 FROM outbox earlier
                    WHERE earlier.task_id=o.task_id AND earlier.kind='final' AND earlier.rowid<o.rowid
                    AND earlier.state NOT IN ('accepted','superseded')))
                ORDER BY o.priority,o.rowid LIMIT 1""").fetchone()
            if row is None:
                return None
            self.db.execute("BEGIN IMMEDIATE")
            try:
                attempt = self.db.execute("""SELECT number,client_id,state FROM delivery_attempts
                    WHERE outbox_id=? ORDER BY number DESC LIMIT 1""", (row[0],)).fetchone()
                if attempt is None:
                    number = 0
                    client_id = "wx-reply-" + uuid.uuid5(uuid.NAMESPACE_URL, self.credentials.bot_id + "\0" + row[0]).hex
                    self.db.execute("""INSERT INTO delivery_attempts(outbox_id,number,client_id,context,state,started_at,provenance)
                        VALUES(?,?,?,?,'sending',?,'runtime-v2')""", (row[0], number, client_id, context[0], time.time()))
                else:
                    number, client_id, state = attempt
                    if state != "prepared":
                        raise ProtocolError("Previous delivery outcome requires explicit retry authorization")
                    self.db.execute("""UPDATE delivery_attempts SET state='sending',context=?,started_at=?
                        WHERE outbox_id=? AND number=?""", (context[0], time.time(), row[0], number))
                self.db.execute("UPDATE outbox SET state='sending',context=? WHERE id=?", (context[0], row[0]))
                self.db.execute("COMMIT")
                return {"id": row[0], "text": row[1], "context": context[0], "client_id": client_id, "attempt": number}
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return await self._call(claim)

    async def finish_reply(self, event_id, state, server_id=None, *, error_code=None):
        if state not in {"accepted", "unknown", "rejected"}:
            raise ValueError("Explicit send outcome required")
        def finish():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                native_id = str(server_id) if server_id is not None else None
                result = self.db.execute("UPDATE outbox SET state=?,server_id=? WHERE id=? AND state='sending'",
                                         (state, native_id, event_id))
                attempt = self.db.execute("""UPDATE delivery_attempts SET state=?,server_id=?,finished_at=?,error_code=?
                    WHERE outbox_id=? AND state='sending'""", (state, native_id, time.time(), str(error_code) if error_code is not None else None, event_id))
                if result.rowcount != 1 or attempt.rowcount != 1:
                    raise ProtocolError("Send attempt is absent or already terminal")
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        await self._call(finish)

    async def retry_reply(self, event_id, *, confirm_unknown=False):
        """Operator-only action; never called automatically by the sender."""
        return await self._call(prepare_reply_retry, self.db, self.credentials, event_id, confirm_unknown)

    async def delivery_attempts(self, event_id):
        def read():
            keys = ("number", "state", "client_id", "started_at", "finished_at", "authorization", "provenance")
            return [dict(zip(keys, row)) for row in self.db.execute("""SELECT number,state,client_id,started_at,finished_at,
                authorization,provenance FROM delivery_attempts WHERE outbox_id=? ORDER BY number""", (event_id,))]
        return await self._call(read)

    async def delivery_counts(self):
        return await self._call(lambda: dict(self.db.execute("SELECT state,count(*) FROM outbox GROUP BY state")))

    async def supersede_reply(self, event_id):
        await self._call(lambda: self.db.execute("UPDATE outbox SET state='superseded' WHERE id=? AND state='pending'", (event_id,)))


def prepare_reply_retry(db, credentials, event_id, confirm_unknown=False):
    """One shared transaction for foreground tests and stopped operator maintenance."""
    if type(confirm_unknown) is not bool:
        raise ValueError("Explicit unknown-delivery decision required")
    def prepare():
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT state FROM outbox WHERE id=?", (event_id,)).fetchone()
            if row is None or row[0] not in {"rejected", "unknown"}:
                raise ProtocolError("Only a recorded rejected or uncertain delivery can be retried")
            if row[0] == "unknown" and not confirm_unknown:
                raise ProtocolError("Unknown delivery may already be on the phone; explicit confirmation required")
            last = db.execute("SELECT number FROM delivery_attempts WHERE outbox_id=? ORDER BY number DESC LIMIT 1", (event_id,)).fetchone()
            if last is None or last[0] >= 2:
                raise ProtocolError("Delivery attempt bound reached or previous attempt is missing")
            number = last[0] + 1
            base = "wx-reply-" + uuid.uuid5(uuid.NAMESPACE_URL, credentials.bot_id + "\0" + event_id).hex
            authorization = "operator_confirmed_possible_duplicate" if row[0] == "unknown" else "operator_retry_rejected"
            db.execute("""INSERT INTO delivery_attempts(outbox_id,number,client_id,context,state,authorization,provenance)
                VALUES(?,?,?,'','prepared',?,'runtime-v2')""", (event_id, number, base + "-" + str(number), authorization))
            db.execute("UPDATE outbox SET state='pending' WHERE id=?", (event_id,))
            db.execute("COMMIT")
            return number
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return prepare()
