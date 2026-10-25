"""Private foreground ledger; native execution and delivery have separate outcomes."""

import json
import sqlite3
import time
import uuid
from contextlib import closing

from .channels.http import ProtocolError
from .channels.private import private_file
from .channels.state import ChannelState


class RuntimeState(ChannelState):
    APPLICATION_ID = 0x57585254

    def _open(self):
        new = self._open_database()
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
        if (self.db.execute("PRAGMA application_id").fetchone()[0] != self.APPLICATION_ID
                or self.db.execute("PRAGMA user_version").fetchone()[0] != 1):
            raise ProtocolError("Database is not a compatible runtime ledger")
        if self.db.execute("SELECT bot,owner FROM channel WHERE id=1").fetchone() != (
                self.credentials.bot_id, self.credentials.owner_id):
            raise ProtocolError("Runtime ledger belongs to another binding")
        # No task, inbound command or uncertain HTTP send is replayed on restart.
        self.db.execute("UPDATE tasks SET state='unknown' WHERE state IN ('prepared','dispatching','queued','running','stopping')")
        self.db.execute("UPDATE outbox SET state='unknown' WHERE state='sending'")
        self.db.execute("UPDATE inbox SET phase='stale' WHERE phase='runtime'")

    async def handled(self, message_id):
        await self._call(lambda: self.db.execute("UPDATE inbox SET phase='handled' WHERE message_id=?", (message_id,)))

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
            now = time.time()
            self.db.execute("INSERT INTO tasks(id,source_message_id,client_id,target,thread_id,input,state,created_at,updated_at) VALUES(?,?,?,?,?,?,'prepared',?,?)",
                            (task_id, message_id, client_id, encoded, target["thread_id"], text, now, now))
            return {"id": task_id, "client_id": client_id, "target": target, "state": "prepared"}
        return await self._call(insert)

    async def task_update(self, task_id, state, *, queue_id=None, turn_id=None):
        if state not in {"dispatching", "queued", "running", "stopping", "unknown"}:
            raise ValueError("Explicit nonterminal native task state required")
        def update():
            previous = self.db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
            if previous and ((state == "queued" and previous[0] in {"running", "stopping"})
                             or (state == "running" and previous[0] == "stopping")):
                return  # A delayed queue ACK must not regress an observed native turn.
            result = self.db.execute("""UPDATE tasks SET state=?,queue_id=COALESCE(?,queue_id),
                turn_id=COALESCE(?,turn_id),updated_at=? WHERE id=? AND state NOT IN ('completed','failed','interrupted','cancelled')""",
                                     (state, queue_id, turn_id, time.time(), task_id))
            if result.rowcount != 1:
                raise ProtocolError("Task is missing or already terminal")
        await self._call(update)

    @staticmethod
    def _task(row):
        if row is None:
            return None
        keys = ("id", "source_message_id", "client_id", "target", "thread_id", "input", "state", "queue_id", "turn_id")
        result = dict(zip(keys, row))
        result["target"] = json.loads(result["target"])
        return result

    async def tasks(self, *, task_id=None, client_id=None):
        def read():
            query = "SELECT id,source_message_id,client_id,target,thread_id,input,state,queue_id,turn_id FROM tasks"
            if task_id is not None:
                return self._task(self.db.execute(query + " WHERE id=?", (task_id,)).fetchone())
            if client_id is not None:
                return self._task(self.db.execute(query + " WHERE client_id=?", (client_id,)).fetchone())
            return [self._task(row) for row in self.db.execute(query + " ORDER BY created_at DESC LIMIT 100")]
        return await self._call(read)

    def _queue_reply(self, event_id, text, priority, task_id=None, kind="reply"):
        if (not isinstance(event_id, str) or not event_id or len(event_id) > 128
                or not isinstance(text, str) or not text.strip() or len(text) > 8000
                or type(priority) is not int or not 0 <= priority <= 10):
            raise ValueError("Bounded stable reply identity and text required")
        existing = self.db.execute("SELECT text FROM outbox WHERE id=?", (event_id,)).fetchone()
        if existing:
            if existing[0] != text:
                raise ProtocolError("Reply identity cannot be reused for different content")
            return False
        if task_id and kind in {"accepted", "progress"}:
            task = self.db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task[0] in {"completed", "failed", "interrupted", "cancelled"}:
                return False
        self.db.execute("INSERT INTO outbox(id,text,priority,state,task_id,kind,created_at) VALUES(?,?,?,'pending',?,?,?)",
                        (event_id, text, priority, task_id, kind, time.time()))
        return True

    async def queue_reply(self, event_id, text, *, priority=5, task_id=None, kind="reply"):
        return await self._call(self._queue_reply, event_id, text, priority, task_id, kind)

    async def task_finish(self, task_id, state, text, *, turn_id=None):
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
                self.db.execute("UPDATE tasks SET state=?,turn_id=COALESCE(?,turn_id),updated_at=? WHERE id=?",
                                (state, turn_id, time.time(), task_id))
                self.db.execute("UPDATE outbox SET state='superseded' WHERE task_id=? AND state='pending' AND kind IN ('accepted','progress')", (task_id,))
                chunks = [text[i:i + 7000] for i in range(0, len(text), 7000)]
                for index, chunk in enumerate(chunks, 1):
                    prefix = f"〔{index}/{len(chunks)}〕\n" if len(chunks) > 1 else ""
                    self._queue_reply(f"{task_id}-final-{index}", prefix + chunk, 0, task_id, "final")
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
            row = self.db.execute("SELECT id,text FROM outbox WHERE state='pending' ORDER BY priority,created_at LIMIT 1").fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE outbox SET state='sending',context=? WHERE id=?", (context[0], row[0]))
            client_id = "wx-reply-" + uuid.uuid5(uuid.NAMESPACE_URL, self.credentials.bot_id + "\0" + row[0]).hex
            return {"id": row[0], "text": row[1], "context": context[0], "client_id": client_id}
        return await self._call(claim)

    async def finish_reply(self, event_id, state, server_id=None):
        if state not in {"accepted", "unknown", "rejected"}:
            raise ValueError("Explicit send outcome required")
        def finish():
            result = self.db.execute("UPDATE outbox SET state=?,server_id=? WHERE id=? AND state='sending'",
                                     (state, str(server_id) if server_id is not None else None, event_id))
            if result.rowcount != 1:
                raise ProtocolError("Send is absent or already terminal")
        await self._call(finish)

    async def delivery_counts(self):
        return await self._call(lambda: dict(self.db.execute("SELECT state,count(*) FROM outbox GROUP BY state")))

    async def supersede_reply(self, event_id):
        await self._call(lambda: self.db.execute("UPDATE outbox SET state='superseded' WHERE id=? AND state='pending'", (event_id,)))
