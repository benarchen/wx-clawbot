"""Explicit maintenance actions; reports never connect to native or send messages."""

import asyncio
import json
import re
import sqlite3
import uuid
from contextlib import closing

from . import schema
from .admission_recovery import terminal_evidence
from .agents.codex import CodexConnection
from .channels.http import ProtocolError
from .channels.private import load_credentials, private_file, private_lease
from .occupancy import TASK_COLUMNS, release_rows, report_digest
from .operations import existing_root
from .runtime_discovery import discover_runtime


def snapshots(db, task_id):
    selected = db.execute("SELECT thread_id FROM tasks WHERE id=?", (task_id,)).fetchone()
    if selected is None:
        raise ProtocolError("Exact task is absent")
    query = f"SELECT {','.join('t.'+c for c in TASK_COLUMNS.split(','))},o.state,o.revision,o.reason,o.evidence,o.checked_at FROM task_occupancy o JOIN tasks t ON t.id=o.task_id WHERE o.task_id=? OR (t.thread_id=? AND o.state='holding') ORDER BY o.rowid LIMIT 129"
    rows = list(db.execute(query, (task_id, selected[0])))
    if not rows or len(rows) > 128:
        raise ProtocolError("Complete bounded occupancy view required")
    result = []
    for row in rows:
        task = dict(zip(TASK_COLUMNS.split(','), row[:10]))
        task['target'] = json.loads(task['target'])
        task['input_items'] = json.loads(task['input_items'])
        task['occupancy'] = dict(zip(('state','revision','reason','evidence','checked_at'), row[10:]))
        task['occupancy']['evidence'] = json.loads(task['occupancy']['evidence'])
        result.append(task)
    return result


def report(root, task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r'[te]-[0-9a-f]{32}', task_id):
        raise ValueError("Exact local task id required")
    root = existing_root(root)
    private_file(root / 'runtime.sqlite3')
    credentials = load_credentials(root / 'credentials.json')
    with closing(sqlite3.connect((root / 'runtime.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        schema.validate(db, credentials, versions=(schema.VERSION,))
        rows = snapshots(db, task_id)
    return {'status':'admission_report','task_id':task_id,'confirm_report':report_digest(rows),
            'occupancies':[{'task_id':t['id'],'execution_state':t['state'],
                'occupancy':t['occupancy']['state'],'revision':t['occupancy']['revision'],
                'reason':t['occupancy']['reason'],'checked_at':t['occupancy']['checked_at']} for t in rows],
            'applied':False,'requires_stopped_consumer':True,'requires_native_terminal_evidence':True}


async def release(root, task_id, *, apply=False, confirm_report=None, reason=None, socket=None, codex_home=None):
    planned = report(root, task_id)
    if not apply:
        return planned
    if (not isinstance(confirm_report, str) or not re.fullmatch(r'[0-9a-f]{64}', confirm_report)
            or not isinstance(reason, str) or not reason.strip() or len(reason) > 512):
        raise ValueError("Explicit report digest and bounded operator reason required")
    root = existing_root(root)
    credentials = load_credentials(root/'credentials.json')
    with private_lease(root/'channel-consumer.lock'), closing(sqlite3.connect(root/'runtime.sqlite3',isolation_level=None,timeout=1)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        schema.validate(db, credentials, versions=(schema.VERSION,))
        rows = snapshots(db, task_id)
        selected = next(t for t in rows if t['id']==task_id)
        if selected['occupancy']['state']=='released':
            return {'status':'already_released','task_id':task_id,'applied':False}
        if report_digest(rows) != confirm_report:
            raise ProtocolError('Operator report became stale')
        if socket is None:
            socket, _ = await asyncio.to_thread(discover_runtime, codex_home)
        native = await CodexConnection.connect(socket)
        try:
            async with asyncio.timeout(5):
                evidence = await terminal_evidence(native, rows, uuid.uuid4().hex)
            evidence['operator_reason'] = reason
            evidence['operator_report'] = confirm_report
            release_rows(db, rows, evidence, reason='operator_verified_terminal')
        finally:
            await native.close()
    return {'status':'released','task_id':task_id,'task_ids':[t['id'] for t in rows],
            'execution_state':'unknown','applied':True,'native_submissions':0,'messages_sent':0}
