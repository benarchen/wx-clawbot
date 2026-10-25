"""Single-worker SQLite inbox/cursor and diagnostic delivery state."""

import asyncio
import fcntl
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .http import ChannelError, ProtocolError
from .messages import parse_text
from .private import private_directory, private_file
from .wechat import validate_updates


class ChannelState:
    APPLICATION_ID = 0x57584342

    def __init__(self, path: Path, credentials):
        self.path, self.credentials = path, credentials
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wx-state")
        self.slot = asyncio.Semaphore(1)
        self.closed = False
        self.db = None
        self.lock_fd = None

    @classmethod
    async def open(cls, path, credentials):
        state = cls(path, credentials)
        try:
            await state._call(state._open)
            return state
        except BaseException:
            await state.close()
            raise

    async def _call(self, fn, *args, closing=False):
        await self.slot.acquire()
        if self.closed and not closing:
            self.slot.release()
            raise ChannelError("Channel state is closed")
        future = asyncio.get_running_loop().run_in_executor(self.worker, fn, *args)

        def done(completed):
            self.slot.release()
            if not completed.cancelled():
                completed.exception()

        future.add_done_callback(done)
        return await asyncio.shield(future)

    def _open_database(self):
        private_directory(self.path.parent)
        lock_path = self.path.parent / "channel-consumer.lock"
        self.lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        private_file(lock_path)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProtocolError("Another process already owns this channel state") from None
        new = not self.path.exists()
        if new:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        private_file(self.path)
        self.db = sqlite3.connect(self.path, timeout=1, isolation_level=None)
        return new

    def _open(self):
        new = self._open_database()
        if new:
            self.db.executescript(f"""
                PRAGMA application_id={self.APPLICATION_ID};
                PRAGMA user_version=1;
                PRAGMA journal_mode=WAL;
                CREATE TABLE channel (id INTEGER PRIMARY KEY CHECK(id=1), bot TEXT NOT NULL,
                    owner TEXT NOT NULL, cursor TEXT NOT NULL DEFAULT '');
                CREATE TABLE inbox (message_id TEXT PRIMARY KEY, text TEXT NOT NULL, context TEXT,
                    created_ms INTEGER NOT NULL, seq INTEGER NOT NULL, received_at REAL NOT NULL,
                    phase TEXT NOT NULL, conflict INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE reply_context (id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL,
                    created_ms INTEGER NOT NULL, seq INTEGER NOT NULL);
                CREATE TABLE channel_outgoing (client_id TEXT PRIMARY KEY, reply_to TEXT NOT NULL UNIQUE,
                    text TEXT NOT NULL, context TEXT NOT NULL, state TEXT NOT NULL,
                    server_id TEXT, created_at REAL NOT NULL);
            """)
            self.db.execute("INSERT INTO channel(id,bot,owner) VALUES(1,?,?)",
                            (self.credentials.bot_id, self.credentials.owner_id))
        if (self.db.execute("PRAGMA application_id").fetchone()[0] != self.APPLICATION_ID
                or self.db.execute("PRAGMA user_version").fetchone()[0] != 1):
            raise ProtocolError("Database is not a compatible wx-clawbot channel store")
        row = self.db.execute("SELECT bot,owner FROM channel WHERE id=1").fetchone()
        if row != (self.credentials.bot_id, self.credentials.owner_id):
            raise ProtocolError("Channel database belongs to a different binding")

    async def cursor(self):
        return await self._call(lambda: self.db.execute("SELECT cursor FROM channel WHERE id=1").fetchone()[0])

    async def accept_batch(self, response, *, phase="diagnostic"):
        if phase not in {"diagnostic", "runtime"}:
            raise ValueError("Explicit receive phase required")
        return await self._call(self._accept_batch, response, phase)

    def _accept_batch(self, response, phase):
        validate_updates(response)
        messages = response.get("msgs", [])
        cursor = response.get("get_updates_buf")
        accepted, rejected, duplicates, conflicts = [], {}, 0, 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for raw in messages:
                message, reason = parse_text(raw, self.credentials)
                if message is None:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    continue
                prior = self.db.execute("SELECT text FROM inbox WHERE message_id=?", (message.message_id,)).fetchone()
                if prior:
                    duplicates += 1
                    if prior[0] != message.text:
                        conflicts += 1
                        self.db.execute("UPDATE inbox SET conflict=1 WHERE message_id=?", (message.message_id,))
                    continue
                self.db.execute("INSERT INTO inbox(message_id,text,context,created_ms,seq,received_at,phase) VALUES(?,?,?,?,?,?,?)",
                                (message.message_id, message.text, message.context_token, message.created_ms,
                                 message.sequence, time.time(), phase))
                accepted.append(message)
                if message.context_token:
                    self.db.execute("""INSERT INTO reply_context VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        token=excluded.token,created_ms=excluded.created_ms,seq=excluded.seq
                        WHERE (excluded.created_ms,excluded.seq) >= (reply_context.created_ms,reply_context.seq)""",
                                    (message.context_token, message.created_ms, message.sequence))
            if cursor:
                self.db.execute("UPDATE channel SET cursor=? WHERE id=1", (cursor,))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return {"accepted": accepted, "rejected": rejected, "duplicates": duplicates, "conflicts": conflicts}

    async def latest_context(self):
        def read():
            row = self.db.execute("SELECT token FROM reply_context WHERE id=1").fetchone()
            return row[0] if row else None
        return await self._call(read)

    async def begin_send(self, client_id, message, text):
        if (not isinstance(client_id, str) or not client_id or len(client_id) > 128
                or not isinstance(text, str) or not text.strip() or len(text) > 8000):
            raise ValueError("Bounded stable delivery identity and text required")
        return await self._call(self._begin_send, client_id, message, text)

    def _begin_send(self, client_id, message, text):
        stored = self.db.execute("SELECT context,conflict FROM inbox WHERE message_id=?", (message.message_id,)).fetchone()
        if not stored or stored[1] or not message.context_token or stored[0] != message.context_token:
            raise ProtocolError("Outbound context does not belong to a valid stored inbound message")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = self.db.execute("""INSERT INTO channel_outgoing(client_id,reply_to,text,context,state,created_at)
                VALUES(?,?,?,?,'sending',?) ON CONFLICT DO NOTHING""",
                                     (client_id, message.message_id, text, message.context_token, time.time()))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return result.rowcount == 1

    async def finish_send(self, client_id, state, server_id=None):
        if state not in {"accepted", "unknown", "rejected"}:
            raise ValueError("Explicit delivery outcome required")
        def update():
            result = self.db.execute("UPDATE channel_outgoing SET state=?,server_id=? WHERE client_id=? AND state='sending'",
                                     (state, str(server_id) if server_id is not None else None, client_id))
            if result.rowcount != 1:
                raise ProtocolError("Delivery is absent or already terminal")
        await self._call(update)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            def finish():
                if self.db is not None:
                    self.db.close()
                if self.lock_fd is not None:
                    os.close(self.lock_fd)
                    self.lock_fd = None
            await self._call(finish, closing=True)
        finally:
            self.worker.shutdown(wait=False, cancel_futures=True)
