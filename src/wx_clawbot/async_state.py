"""Durable async supplement intents in the runtime ledger's single writer."""

import hashlib
import json
import time
import uuid


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def user_text(item):
    content = item.get('content')
    if (not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict)
            or content[0].get('type') != 'text' or not isinstance(content[0].get('text'), str)):
        return None
    return content[0]['text']


class AsyncQuestionStore:
    def _async_rows(self, where, args=()):
        cursor = self.db.execute('SELECT * FROM async_questions WHERE ' + where + ' ORDER BY rowid LIMIT 257', args)
        keys = [c[0] for c in cursor.description]
        rows = [dict(zip(keys, row)) for row in cursor]
        if len(rows) > 256:
            raise ValueError('Async question query exceeds its bound')
        for row in rows:
            row['questions'] = json.loads(row['questions'])
            row['target'] = json.loads(row['target'])
        return rows

    async def async_rows(self, *, public_id=None, task_id=None, thread_turn=None, active=False):
        if public_id is not None:
            where, args = 'public_id=?', (public_id,)
        elif thread_turn is not None:
            where, args = 'thread_id=? AND turn_id=?', thread_turn
        elif task_id is not None:
            where, args = 'task_id=?', (task_id,)
        elif active:
            where, args = 'closed_at IS NULL', ()
        else:
            raise ValueError('An exact async identity or bounded active query required')
        return await self._call(self._async_rows, where, args)

    def _async_close(self, row, reason, *, conflict=False):
        state = ('conflict' if conflict else 'stale') if row['answer_client'] else 'stale'
        if row['answer_client'] and not conflict:
            state = 'unknown' if row['state'] == 'sending' else row['state']
        self.db.execute('UPDATE async_questions SET state=?,reason=?,closed_at=?,updated_at=? WHERE public_id=?',
                        (state, reason, time.time(), time.time(), row['public_id']))
        self.db.execute("UPDATE outbox SET state='superseded' WHERE state='pending' AND id GLOB ?",
                        (row['public_id'] + '-prompt*',))

    async def async_budget(self):
        def read():
            count, size = self.db.execute("""SELECT count(*),COALESCE(sum(length(CAST(params AS BLOB))),0)
                FROM interactions WHERE state NOT IN ('resolved','stale')""").fetchone()
            n, b = self.db.execute("""SELECT count(*),COALESCE(sum(length(CAST(questions AS BLOB))+
                length(CAST(target AS BLOB))+COALESCE(length(CAST(answer_text AS BLOB)),0)),0)
                FROM async_questions WHERE closed_at IS NULL OR state='unknown'""").fetchone()
            return count + n, size + b
        return await self._call(read)

    async def async_register(self, record, chunks):
        def save():
            self.db.execute('BEGIN IMMEDIATE')
            try:
                existing = self._async_rows('source=? AND thread_id=? AND turn_id=? AND item_id=?',
                    tuple(record[k] for k in ('source','thread_id','turn_id','item_id')))
                if existing:
                    row = existing[0]
                    if row['question_sha256'] != record['question_sha256']:
                        self._async_close(row, 'question_changed', conflict=bool(row['answer_client']))
                        self.db.execute('UPDATE async_questions SET revision=revision+1 WHERE public_id=?', (row['public_id'],))
                        self._queue_reply(row['public_id'] + '-changed',
                            f"异步问题内容已变化：{row['public_id']}；旧入口不再接收答案，请在原终端核对。", 0)
                    self.db.execute('COMMIT')
                    return row, False
                count, size = self.db.execute("""SELECT count(*),COALESCE(sum(length(CAST(params AS BLOB))),0)
                    FROM interactions WHERE state NOT IN ('resolved','stale')""").fetchone()
                turn_count = self.db.execute('SELECT count(*) FROM async_questions WHERE thread_id=? AND turn_id=?',
                                             (record['thread_id'], record['turn_id'])).fetchone()[0]
                if turn_count >= 256:
                    raise ValueError('Per-turn retained question bound exceeded')
                n, b = self.db.execute("""SELECT count(*),COALESCE(sum(length(CAST(questions AS BLOB))+
                    length(CAST(target AS BLOB))+COALESCE(length(CAST(answer_text AS BLOB)),0)),0)
                    FROM async_questions WHERE closed_at IS NULL OR state='unknown'""").fetchone()
                questions = json.dumps(record['questions'], ensure_ascii=False, separators=(',', ':'))
                target = json.dumps(record['target'], ensure_ascii=False, sort_keys=True)
                if count + n >= 256 or size + b + len((questions + target).encode()) > 16 * 1024 * 1024:
                    raise ValueError('Shared interaction capacity exceeded')
                now = time.time()
                self.db.execute('''INSERT INTO async_questions(public_id,source,thread_id,turn_id,item_id,
                    revision,questions,question_sha256,target,task_id,generation,state,reason,expires_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,1,?,?,?,?,?,'pending','',?,?,?)''',
                    (*[record[k] for k in ('public_id','source','thread_id','turn_id','item_id')], questions,
                     record['question_sha256'], target, record['task_id'], record['generation'], record['expires_at'], now, now))
                for index, chunk in enumerate(chunks):
                    key = record['public_id'] + '-prompt' + (f'-part-{index}' if len(chunks) > 1 else '')
                    self._queue_reply(key, chunk.text, 0, record['task_id'], 'async_question')
                self.db.execute('COMMIT')
                return record, True
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK')
                raise
        return await self._call(save, wake=True)

    async def async_intent(self, public_id, generation, revision, text):
        def save():
            if not isinstance(text, str) or not text.strip() or len(text) > 32000:
                raise ValueError('Bounded answer text required')
            size = self.db.execute("""SELECT COALESCE(sum(length(CAST(params AS BLOB))),0)
                FROM interactions WHERE state NOT IN ('resolved','stale')""").fetchone()[0]
            size += self.db.execute("""SELECT COALESCE(sum(length(CAST(questions AS BLOB))+
                length(CAST(target AS BLOB))+COALESCE(length(CAST(answer_text AS BLOB)),0)),0)
                FROM async_questions WHERE closed_at IS NULL OR state='unknown'""").fetchone()[0]
            if size + len(text.encode()) > 16 * 1024 * 1024:
                raise ValueError('Shared answer storage budget exceeded')
            client = 'wx-answer-' + uuid.uuid4().hex
            cursor = self.db.execute("""UPDATE async_questions SET state='sending',answer_client=?,
                answer_text=?,answer_sha256=?,updated_at=? WHERE public_id=? AND generation=?
                AND revision=? AND state='pending' AND closed_at IS NULL AND expires_at>?""",
                (client, text, digest(text), time.time(), public_id, generation, revision, time.time()))
            if cursor.rowcount != 1:
                raise ValueError('Question is stale or already has an answer intent')
            return self._async_rows('public_id=?', (public_id,))[0]
        return await self._call(save)

    async def async_result(self, public_id, outcome):
        if outcome not in {'accepted','refused','unknown'}:
            raise ValueError('Explicit native answer outcome required')
        def save():
            # Concurrent observed/closed/conflict evidence wins over a late ACK.
            self.db.execute("""UPDATE async_questions SET state=?,reason=?,updated_at=?
                WHERE public_id=? AND state='sending' AND closed_at IS NULL""",
                (outcome, 'native_' + outcome, time.time(), public_id))
            return self._async_rows('public_id=?', (public_id,))[0]
        return await self._call(save)

    async def async_close(self, *, generation=None, thread_turn=None, public_id=None, reason, pending_only=False):
        def close():
            self.db.execute('BEGIN IMMEDIATE')
            try:
                if public_id:
                    rows = self._async_rows('public_id=?' +
                        (" AND state='pending' AND closed_at IS NULL" if pending_only else ''), (public_id,))
                elif thread_turn:
                    rows = self._async_rows('thread_id=? AND turn_id=? AND closed_at IS NULL', thread_turn)
                else:
                    rows = self._async_rows('generation=? AND closed_at IS NULL', (generation,))
                for row in rows:
                    self._async_close(row, reason)
                self.db.execute('COMMIT')
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK')
                raise
        return await self._call(close, wake=True)

    def _async_restart(self):
        self.db.execute("""UPDATE async_questions SET state=CASE WHEN state='pending' THEN 'stale'
            WHEN state='sending' THEN 'unknown' ELSE state END,reason='restart',
            closed_at=COALESCE(closed_at,?),updated_at=? WHERE closed_at IS NULL""", (time.time(), time.time()))
        self.db.execute("UPDATE outbox SET state='superseded' WHERE state='pending' AND id GLOB 'q-*-prompt*'")

    async def async_user(self, thread_id, turn_id, user):
        """Classify a single event and retain explicit foreign-input evidence."""
        def observe():
            rows = self._async_rows('thread_id=? AND turn_id=?', (thread_id, turn_id))
            client, text = user.get('clientId'), user_text(user)
            own = [r for r in rows if r['answer_client'] and r['answer_client'] == client]
            if own and text is not None and digest(text) == own[0]['answer_sha256']:
                self.db.execute("""UPDATE async_questions SET state='observed',updated_at=?
                    WHERE public_id=? AND state IN ('sending','accepted','unknown')""", (time.time(), own[0]['public_id']))
                return True
            for row in rows:
                task = self.db.execute('SELECT client_id,target FROM tasks WHERE id=?', (row['task_id'],)).fetchone()
                if task:
                    target = json.loads(task[1])
                    original = target.get('native_client_id') if target.get('source') == 'external' else task[0]
                    if client and client == original:
                        continue
                if ((row['closed_at'] is not None and not row['answer_client'])
                        or row['state'] in {'stale','refused','conflict'}):
                    continue
                self._async_close(row, 'foreign_input', conflict=bool(row['answer_client']))
                self._queue_reply(row['public_id'] + '-foreign',
                    (f"异步答复发生跨端输入冲突：{row['public_id']}；两端可能均被接受，请在原终端核对，桥接不重试。"
                     if row['answer_client'] else f"本轮已观察到其他输入：{row['public_id']}；旧答复入口已失效，请在原终端核对。"), 0)
            return False
        # Both state and conflict notification must commit together.
        def transaction():
            self.db.execute('BEGIN IMMEDIATE')
            try:
                result = observe()
                self.db.execute('COMMIT')
                return result
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        return await self._call(transaction, wake=True)

    async def async_business_users(self, thread_id, turn_id, users, task=None):
        rows = await self.async_rows(thread_turn=(thread_id, turn_id))
        allowed = {r['answer_client']: r for r in rows if r['answer_client']
                   and r['state'] in {'sending','accepted','observed','unknown','conflict'}}
        clients = [u.get('clientId') for u in users]
        if any(c and clients.count(c) != 1 for c in clients):
            return users  # Never hide duplicate inputs or ambiguous client identities.
        # A persisted answer only belongs to the task whose original client is
        # actually present in this turn, including external native client IDs.
        anchors = {}
        for row in allowed.values():
            if row['task_id'] not in anchors:
                original_task = await self.tasks(task_id=row['task_id']) if row['task_id'] else None
                if original_task:
                    target = original_task['target']
                    anchors[row['task_id']] = (target.get('native_client_id')
                        if target.get('source') == 'external' else original_task['client_id'])
                else:
                    anchors[row['task_id']] = None
        business = []
        for user in users:
            row = allowed.get(user.get('clientId'))
            text = user_text(user)
            if (row is not None and text is not None and digest(text) == row['answer_sha256']
                    and anchors.get(row['task_id']) in clients and anchors.get(row['task_id']) is not None
                    and (task is None or row['task_id'] == task['id'])):
                continue
            business.append(user)
        # At least one original business input must remain; answer-only turns cannot be adopted.
        return business if business else users
