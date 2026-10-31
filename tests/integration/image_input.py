"""Explicit IMG01 inspection and one-shot desktop prompt preparation in owned fixtures.

Never polls WeChat, answers approvals, changes model/settings or replays tasks.
Real phone input must arrive through the normal foreground bridge.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from wx_clawbot import schema
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import load_credentials, private_directory, private_file, write_json
from wx_clawbot.config import load_projects
from wx_clawbot.hosts.connection import close_connection
from wx_clawbot.hosts.discovery import ItermDirectory
from wx_clawbot.runtime_discovery import discover_runtime


async def run(args):
    import iterm2
    credentials = load_credentials(args.state_dir / 'credentials.json')
    path = args.state_dir / 'runtime.sqlite3'
    private_file(path)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        schema.validate(db, credentials, versions=(schema.VERSION,))
        row = db.execute('SELECT target,thread_id,client_id,state,turn_id,source_message_id FROM tasks WHERE id=?', (args.task_id,)).fetchone()
        if row is None:
            raise ValueError('Accurate task ID required')
        target, thread_id, client_id, state, turn_id, source = row
        target = json.loads(target)
        inbox = db.execute('SELECT content FROM inbox WHERE message_id=?', (source,)).fetchone()
        replies = dict(db.execute('SELECT state,count(*) FROM outbox WHERE task_id=? GROUP BY state', (args.task_id,)))
        attachments = db.execute('SELECT state,sha256 FROM attachments WHERE task_id=? ORDER BY item_index', (args.task_id,)).fetchall()
    fixture = Path(target['cwd']).resolve(strict=True)
    if not fixture.is_relative_to((Path(__file__).resolve().parents[2] / '.tmp').resolve()):
        raise ValueError('Acceptance is restricted to task-owned temporary projects')
    projects = load_projects(args.config)
    socket, _ = discover_runtime(args.codex_home)
    native = await CodexConnection.connect(socket)
    host = None
    try:
        host = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        catalog = SessionCatalog(projects, ItermDirectory(host), native)
        found = await catalog.discover()
        matches = [s for s in found if s.target.session_id == target['session_id'] and s.binding.thread_id == thread_id and s.target.cwd == fixture]
        if len(matches) != 1:
            raise ValueError('Original visible fixture identity is not uniquely verified')
        session = matches[0]
        await catalog.require(session.target)
        report_dir = private_directory(args.state_dir / 'acceptance/image-input/reports')
        if args.action == 'desktop-followup':
            if state != 'completed' or (await native.inspect(thread_id))['status']['type'] != 'idle':
                raise ValueError('Original image task must be completed and fixture idle')
            intent = report_dir / (args.task_id + '-desktop-intent.json')
            write_json(intent, {'task_id': args.task_id, 'thread_id': thread_id, 'state': 'sending'})
            app = await iterm2.async_get_app(host)
            terminal = app.get_session_by_id(session.binding.endpoint.terminal_id)
            await asyncio.wait_for(terminal.async_send_text(
                '仅根据刚才图片和对话，复述主要视觉特征及已有分析结论。只回答，不运行工具、不读取或修改文件。',
                suppress_broadcast=True), 5)
            write_json(intent, {'task_id': args.task_id, 'thread_id': thread_id, 'state': 'awaiting_owner_enter'}, replace=True)
            return {'status': 'desktop_prompt_prepared_owner_enter_required', 'target_reverified': True,
                    'native_submission_confirmed': False}
        turns, cursor, seen = [], None, set()
        for _ in range(50):
            params = {'threadId': thread_id, 'limit': 1, 'itemsView': 'full', 'sortDirection': 'desc'}
            if cursor:
                params['cursor'] = cursor
            page = await native.rpc.request('thread/turns/list', params)
            for turn in page.get('data', []):
                if any(i.get('type') == 'userMessage' and i.get('clientId') == client_id for i in turn.get('items', [])):
                    turns.append(turn)
            cursor = page.get('nextCursor')
            if cursor is None:
                break
            if cursor in seen:
                raise ValueError('Repeated history cursor')
            seen.add(cursor)
        if len(turns) > 1:
            raise ValueError('Duplicate client in original native history')
        report = {'status': 'inspected_not_automatic_acceptance', 'target_reverified': True,
                  'ledger_task_state': state, 'native_matches': len(turns), 'reply_counts': replies,
                  'attachment_states': [r[0] for r in attachments],
                  'inbound_item_types': [i['type'] for i in json.loads(inbox[0])] if inbox else [],
                  'runtime_version': native.server_version}
        private_excerpt = {'report': report}
        if turns:
            turn = turns[0]
            users = [i for i in turn.get('items', []) if i.get('type') == 'userMessage']
            images = [c for u in users for c in u.get('content', []) if c.get('type') in {'image', 'localImage'}]
            report.update(native_status=turn['status'], user_messages=len(users), native_image_items=len(images),
                          tool_item_types=sorted({i['type'] for i in turn.get('items', []) if i.get('type') not in {'userMessage', 'agentMessage', 'reasoning', 'plan'}}))
            if len(images) == 1 and images[0].get('url', '').startswith('data:image/'):
                encoded = images[0]['url'].partition(',')[2]
                digest = hashlib.sha256()
                for index in range(0, len(encoded), 65536):
                    digest.update(base64.b64decode(encoded[index:index + 65536], validate=True))
                report['native_image_matches_attachment'] = any(r[1] == digest.hexdigest() for r in attachments)
            private_excerpt['native_identity'] = {'thread_id': thread_id, 'client_id': client_id, 'turn_id': turn['id']}
            private_excerpt['answer_excerpt'] = '\n'.join(i.get('text', '') for i in turn.get('items', []) if i.get('type') == 'agentMessage')[:8000]
        write_json(report_dir / (args.task_id + '-inspection.json'), private_excerpt, replace=(report_dir / (args.task_id + '-inspection.json')).exists())
        return report
    finally:
        await native.close()
        if host:
            await close_connection(host)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'desktop-followup'])
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, default=Path.home() / 'Library/Application Support/wx-clawbot')
    parser.add_argument('--codex-home', type=Path, default=Path.home() / '.codex')
    args = parser.parse_args()
    if not args.task_id.startswith('t-') or len(args.task_id) != 34 or any(c not in '0123456789abcdef' for c in args.task_id[2:]):
        parser.error('Accurate bridge task ID required')
    try:
        print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({'status': 'not_confirmed', 'error_type': type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
