"""Durable admission ownership; unknown execution results remain independent."""

import hashlib
import json
import math
import time
from datetime import datetime, timedelta, timezone

from .channels.http import ProtocolError
from .output import render_in_worker, render_segments


ACTIVE_FROM = "task_occupancy o INDEXED BY occupancy_active JOIN tasks t ON t.id=o.task_id"
ACTIVE_WHERE = "o.state IN ('waiting','holding')"
TASK_COLUMNS = "id,source_message_id,client_id,target,thread_id,input,state,queue_id,turn_id,input_items"
CHECK_REASONS = {
    'legacy_unverified':'旧任务尚未取得结束证据',
    'native_unverified':'连接中断，等待重新核验',
    'native_query_unavailable':'原生查询暂不可用，程序会自动重新核验',
    'native_still_active':'原生线程仍有活动',
    'native_history_still_active':'原生历史中仍有执行中的轮次',
    'native_queue_not_empty_or_incomplete':'原生队列未排空或队列核验不完整',
    'native_queue_changed':'核验期间原生队列发生变化',
    'known_tool_still_running':'发现原生工具仍在运行',
    'missing_terminal_identity':'缺少准确原生轮次关联，尚不能安全解除',
    'original_turn_not_found':'当前有界查询尚未找到准确原轮次',
    'history_bound_exceeded':'原轮次超出本次有界核验范围',
    'duplicate_client_history':'发现重复提交关联，仍需核对',
    'submission_inflight':'原生提交仍在进行，尚不能解除',
    'native_generation_changed':'原生连接已变化，等待重新核验',
    'occupancy_revision_changed':'任务占用记录已变化，等待重新核验',
    'late_native_activity':'收到迟到的原生活动，已恢复占用保护',
}


def transition(db, task_id, state, reason, evidence=None):
    if not db.in_transaction:
        raise ProtocolError("Occupancy transition requires its task transaction")
    encoded = json.dumps(evidence or {}, sort_keys=True, allow_nan=False)
    if state not in {"waiting", "holding", "released"} or len(encoded) > 16384:
        raise ValueError("Bounded explicit occupancy evidence required")
    row = db.execute("SELECT state,revision FROM task_occupancy WHERE task_id=?", (task_id,)).fetchone()
    revision = row[1] + 1 if row else 0
    now = time.time()
    db.execute("""INSERT INTO task_occupancy VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(task_id) DO UPDATE SET state=excluded.state,revision=excluded.revision,
        reason=excluded.reason,evidence=excluded.evidence,checked_at=excluded.checked_at,updated_at=excluded.updated_at""",
        (task_id, state, revision, reason, encoded, now if evidence else None, now))
    db.execute("INSERT INTO occupancy_audit(task_id,revision,state,reason,evidence,created_at) VALUES(?,?,?,?,?,?)",
                    (task_id, revision, state, reason, encoded, now))


def release_rows(db, expected, evidence, *, reason="native_terminal"):
    if (not isinstance(expected, list) or not 1 <= len(expected) <= 128
            or len({t['id'] for t in expected}) != len(expected)
            or not isinstance(evidence, dict) or evidence.get("kind") != "native_terminal"
            or evidence.get("queue_empty") is not True or not isinstance(evidence.get('turns'),dict) or not evidence['turns']
            or any(not isinstance(k,str) or not k or v not in {'completed','failed','interrupted'} for k,v in evidence['turns'].items())
            or not isinstance(evidence.get("generation"), str) or not evidence['generation']):
        raise ValueError("Exact snapshots and native terminal/queue evidence required")
    db.execute("BEGIN IMMEDIATE")
    try:
        for task in expected:
            row = db.execute("""SELECT t.state,t.thread_id,t.turn_id,o.state,o.revision FROM tasks t
                JOIN task_occupancy o ON o.task_id=t.id WHERE t.id=?""", (task["id"],)).fetchone()
            if row != ("unknown", task["thread_id"], task["turn_id"], "holding", task["occupancy"]["revision"]):
                raise ProtocolError("Occupancy evidence became stale")
            if evidence.get("thread_id") != task["thread_id"] or task["turn_id"] not in evidence["turns"]:
                raise ProtocolError("Native terminal evidence escaped its original turn")
        for task in expected:
            transition(db, task["id"], "released", reason, evidence)
        db.execute("COMMIT")
        return True
    except BaseException:
        db.execute("ROLLBACK")
        raise


class OccupancyStore:
    """Uses RuntimeState's single worker/connection and existing transaction owner."""

    def _occupancy_transition(self, task_id, state, reason, evidence=None):
        transition(self.db, task_id, state, reason, evidence)

    def _active_count(self):
        return self.db.execute(f"SELECT count(*) FROM {ACTIVE_FROM} WHERE {ACTIVE_WHERE}").fetchone()[0]

    async def occupancy_snapshot(self, *, task_id=None, holding_only=False):
        def read():
            where, args = ("o.task_id=?", (task_id,)) if task_id else (
                "o.state='holding'" if holding_only else ACTIVE_WHERE, ())
            query = f"SELECT {','.join('t.'+c for c in TASK_COLUMNS.split(','))},o.state,o.revision,o.reason,o.evidence,o.checked_at FROM task_occupancy o JOIN tasks t ON t.id=o.task_id WHERE {where} ORDER BY o.rowid LIMIT 129"
            rows = list(self.db.execute(query, args))
            if len(rows) > 128:
                raise ProtocolError("Occupancy bound exceeded; incomplete view cannot grant admission")
            result = []
            for row in rows:
                task = self._task(row[:10])
                task["occupancy"] = dict(zip(("state", "revision", "reason", "evidence", "checked_at"), row[10:]))
                task["occupancy"]["evidence"] = json.loads(task["occupancy"]["evidence"])
                result.append(task)
            return result
        return await self._call(read)

    async def release_occupancies(self, expected, evidence, *, reason="native_terminal"):
        return await self._call(lambda: release_rows(self.db, expected, evidence, reason=reason))

    async def record_occupancy_check(self, snapshots, reason):
        def record():
            now = time.time()
            self.db.executemany("UPDATE task_occupancy SET checked_at=?,reason=? WHERE task_id=? AND revision=? AND state='holding'",
                [(now, reason, t["id"], t["occupancy"]["revision"]) for t in snapshots])
        await self._call(record)

    async def reactivate_occupancy(self, thread_id, turn_id):
        def mark():
            self.db.execute('BEGIN IMMEDIATE')
            try:
                rows = list(self.db.execute("""SELECT t.id FROM tasks t INDEXED BY task_native_turn
                    JOIN task_occupancy o ON o.task_id=t.id WHERE t.thread_id=? AND t.turn_id=?
                    AND t.state='unknown' AND o.state='released' LIMIT 129""", (thread_id, turn_id)))
                if len(rows)>128:
                    raise ProtocolError('Late native activity exceeds the bounded ownership view')
                for (identity,) in rows:
                    self._occupancy_transition(identity,'holding','late_native_activity')
                self.db.execute('COMMIT')
                return bool(rows)
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        return await self._call(mark)

    async def occupancy_history(self, *, after="", limit=20):
        if not isinstance(after, str) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Bounded occupancy history cursor required")
        def read():
            return [dict(zip(("task_id", "state", "revision", "reason", "checked_at"), row)) for row in self.db.execute(
                "SELECT task_id,state,revision,reason,checked_at FROM task_occupancy INDEXED BY occupancy_history WHERE state='released' AND task_id>? ORDER BY task_id LIMIT ?", (after, limit))]
        return await self._call(read)

    async def unknown_history_page(self, *, after='', limit=20):
        if not isinstance(after,str) or type(limit) is not int or not 1<=limit<=100:
            raise ValueError('Bounded unknown-result cursor required')
        return await self._call(lambda:[self._task(row) for row in self.db.execute(
            f"SELECT {TASK_COLUMNS} FROM tasks INDEXED BY task_unknown_history WHERE state='unknown' AND id>? ORDER BY id LIMIT ?",(after,limit))])

    async def admission_wait(self, task, reason, blockers, *, now=None):
        now = time.time() if now is None else now
        if type(now) not in (int,float) or not math.isfinite(now):
            raise ValueError('Finite admission observation clock required')
        blockers = sorted(set(blockers))[:128]
        encoded = json.dumps(blockers)
        old = await self.admission_wait_status(task['id'])
        if old and (old['escalated'] or now - old['first_at'] < 60):
            await self._call(lambda: self.db.execute(
                "UPDATE admission_waits SET reason=?,blockers=?,checked_at=? WHERE task_id=?", (reason, encoded, now, task['id'])))
            return
        text = f"任务已接收，等待准入：{task['id']}。{reason}；尚未进入原生队列。"
        if blockers:
            text += "\n阻塞任务：" + "、".join(blockers) + "。"
        text += f"\n可用 /status {task['id']} 查询，或 /stop {task['id']} 撤销本次未提交任务。"
        chunks = await render_in_worker(text, renderer=render_segments, slots=self.render_slots)
        def record():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                current = self.db.execute("SELECT state FROM tasks WHERE id=?", (task["id"],)).fetchone()
                if current != ("received",):
                    return
                old = self.db.execute("SELECT first_at,escalated,reason,blockers FROM admission_waits WHERE task_id=?", (task["id"],)).fetchone()
                first, escalated = (old[0], old[1]) if old else (now, 0)
                upgrade = bool(old and not escalated and now - first >= 60)
                self.db.execute("""INSERT INTO admission_waits VALUES(?,?,?,?,?,?) ON CONFLICT(task_id)
                    DO UPDATE SET reason=excluded.reason,blockers=excluded.blockers,checked_at=excluded.checked_at,escalated=excluded.escalated""",
                    (task["id"], reason, encoded, first, now, int(escalated or upgrade)))
                if old is None or upgrade:
                    event = task["id"] + ("-waiting-60" if upgrade else "-waiting")
                    for i, chunk in enumerate(chunks):
                        self._queue_reply(event + (f"-part-{i}" if len(chunks) > 1 else ""),
                            ("准入等待仍未解除。\n" if upgrade else "") + chunk.text, 2, task["id"], "progress")
                self.db.execute("COMMIT")
            finally:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
        await self._call(record, wake=True)

    async def admission_wait_status(self, task_id):
        def read():
            row = self.db.execute("SELECT reason,blockers,first_at,checked_at,escalated FROM admission_waits WHERE task_id=?", (task_id,)).fetchone()
            return dict(zip(("reason", "blockers", "first_at", "checked_at", "escalated"), row)) if row else None
        return await self._call(read)

    async def occupancy_counts(self):
        def read():
            counts = dict(self.db.execute("SELECT state,count(*) FROM task_occupancy GROUP BY state"))
            counts['released_unknown'] = self.db.execute("SELECT count(*) FROM task_occupancy o JOIN tasks t ON t.id=o.task_id WHERE o.state='released' AND t.state='unknown'").fetchone()[0]
            return counts
        return await self._call(read)

    async def describe_admission(self, task):
        rows = await self.occupancy_snapshot(task_id=task['id'])
        if not rows:
            return ''
        hold = rows[0]['occupancy']
        state = {'waiting':'尚未提交，等待准入','holding':'仓库占用仍保留','released':'仓库占用已释放'}[hold['state']]
        text = f"{state}。"
        if task['state'] == 'unknown':
            text += '历史执行结果仍未知，不会自动重跑。'
            if hold['state']=='holding':
                text += '\n占用核验说明：'+CHECK_REASONS.get(hold['reason'],'准确原生结束证据尚不完整')+'。'
        if hold['checked_at']:
            checked = datetime.fromtimestamp(hold['checked_at'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
            text += f'\n最后占用核验：{checked}（北京时间）。'
        wait = await self.admission_wait_status(task['id']) if task['state']=='received' else None
        if wait:
            text += '\n等待原因：'+wait['reason']+'。'
            blockers = json.loads(wait['blockers'])
            if blockers:
                text += '\n阻塞任务：'+'、'.join(blockers)+'。'
            checked=datetime.fromtimestamp(wait['checked_at'],timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
            text += f'\n最后准入检查：{checked}（北京时间）。'
        return text


def report_digest(rows):
    values = [(t["id"], t["state"], t["target"], t["thread_id"], t["turn_id"], t["occupancy"]["state"], t["occupancy"]["revision"]) for t in rows]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
