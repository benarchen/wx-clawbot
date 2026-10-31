"""One authorized owner-only MD01 reminder; no UI, polling or native tasks."""
import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from wx_clawbot import schema
from wx_clawbot.channels.http import WeixinHttp
from wx_clawbot.channels.private import load_credentials, private_file, private_lease, read_json, write_json
from wx_clawbot.channels.wechat import BusinessError, WechatApi
from wx_clawbot.hosts.process import ProcessIdentity, read_process

TARGET = '2026-10-30T20:00:00+08:00'
TEXT = ('主人，已到北京时间 20:00，请回来继续 MD01 的 Mac 微信手动验收。\n\n'
        '请由你自行打开样例对话，提供显示截图和指定代码的复制结果；我不会操作微信客户端。'
        '当前施工进度见本会话。')


async def send_due(record, save, api, credentials, context, now):
    if record['phase'] != 'scheduled' or record.get('attempt'):
        raise ValueError('Existing reminder intent/outcome cannot be replayed')
    if record['binding'] != [credentials.bot_id, credentials.owner_id]:
        raise ValueError('Owner binding changed')
    if hashlib.sha256(record['text'].encode()).hexdigest() != record['text_sha256']:
        raise ValueError('Frozen reminder changed')
    if now < record['target_timestamp']:
        raise ValueError('Reminder is not due')
    if now > record['expires_timestamp']:
        record['phase'] = 'expired_no_send'
        save(record)
        return
    record['phase'] = 'send_intent'
    record['attempt'] = {'started_at': now, 'client_id': record['client_id'], 'state': 'sending'}
    save(record)
    try:
        result = await api.send_text(credentials, peer=credentials.owner_id, text=record['text'],
                                     context_token=context, client_id=record['client_id'])
    except BaseException as exc:
        record['phase'] = 'rejected_no_retry' if isinstance(exc, BusinessError) else 'unknown_no_retry'
        record['attempt'].update(state='rejected' if isinstance(exc, BusinessError) else 'unknown',
                                 error_type=type(exc).__name__)
        save(record)
        raise
    record['phase'] = 'accepted'
    record['attempt'].update(state='accepted', server_message_id=result.get('message_id'), finished_at=time.time())
    save(record)


async def run(root):
    path = root / 'md01-mac-reminder.json'
    with private_lease(root / 'md01-mac-reminder.lock'):
        record = read_json(path)
        if record['phase'] != 'scheduled' or record.get('attempt'):
            raise ValueError('Reminder worker cannot be restarted after an intent/outcome')
        identity = read_process(os.getpid())
        if identity is None:
            raise ValueError('Cannot identify reminder worker')
        record['process'] = asdict(identity)
        record['worker_started_at'] = time.time()
        write_json(path, record, replace=True)
        while time.time() < record['target_timestamp']:
            await asyncio.sleep(min(30, record['target_timestamp'] - time.time()))
            record = read_json(path)
            if record['phase'] != 'scheduled':
                return
        now = time.time()
        if now > record['expires_timestamp']:
            record['phase'] = 'expired_no_send'
            write_json(path, record, replace=True)
            return
        credentials = load_credentials(root / 'credentials.json')
        ledger = root / 'runtime.sqlite3'
        private_file(ledger)
        with sqlite3.connect(ledger.as_uri() + '?mode=ro', uri=True) as db:
            schema.validate(db, credentials)
            row = db.execute('SELECT token FROM reply_context WHERE id=1').fetchone()
        if row is None or not row[0]:
            record['phase'] = 'missing_context_no_send'
            write_json(path, record, replace=True)
            return
        http = WeixinHttp()
        try:
            await send_due(record, lambda value: write_json(path, value, replace=True), WechatApi(http),
                           credentials, row[0], now)
        finally:
            await http.close()


def main(action):
    root = Path.home() / 'Library/Application Support/wx-clawbot'
    path = root / 'md01-mac-reminder.json'
    if action == 'prepare':
        target = datetime.fromisoformat(TARGET).timestamp()
        if not time.time() < target:
            raise ValueError('Do not schedule a past reminder')
        credentials = load_credentials(root / 'credentials.json')
        write_json(path, {'phase': 'scheduled', 'target': TARGET, 'target_timestamp': target,
                         'expires_timestamp': target + 300, 'binding': [credentials.bot_id, credentials.owner_id],
                         'text': TEXT, 'text_sha256': hashlib.sha256(TEXT.encode()).hexdigest(),
                         'client_id': 'md01-mac-reminder-' + uuid.uuid4().hex, 'attempt': None})
    elif action == 'run':
        asyncio.run(run(root))
    record = read_json(path)
    identity = record.get('process')
    alive = False
    if identity:
        identity = dict(identity)
        identity['started'] = tuple(identity['started'])
        expected = ProcessIdentity(**identity)
        alive = read_process(expected.pid) == expected
    print(json.dumps({'phase': record['phase'], 'target': record['target'], 'process_alive': alive,
                      'send_attempts': int(record.get('attempt') is not None), 'native_tasks': 0,
                      'client_ui_operations': 0}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'report'])
    main(parser.parse_args().action)
