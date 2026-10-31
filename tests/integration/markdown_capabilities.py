"""Explicit owner-only raw Markdown probes; no polling, native tasks or ledger edits.

The existing text-only WechatApi sends frozen artificial fixtures verbatim, so
G01 measures the client independently of the old renderer. Private intent/outcome
records are durable before every send; an uncertain or partial batch is not replayed.
"""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from wx_clawbot import schema
from wx_clawbot.channels.http import WeixinHttp
from wx_clawbot.channels.private import load_credentials, private_file, write_json
from wx_clawbot.channels.wechat import BusinessError, WechatApi

PROJECT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT / 'tests/fixtures/wechat-markdown-probes.json'


def load_samples(path=FIXTURE):
    data = json.loads(path.read_text())
    samples = data['samples']
    if data['schema'] != 1 or [s['id'] for s in samples] != ['P01', 'P02', 'P03']:
        raise ValueError('Only the three reviewed MD01 probes may be sent')
    for sample in samples:
        text = sample['text']
        if not isinstance(text, str) or not text.startswith('MD01 排版样例 ' + sample['id']) or not 0 < len(text) <= 8000:
            raise ValueError('Invalid bounded artificial probe')
    return samples


async def send_once(case, save, api, credentials, context):
    if case['phase'] != 'prepared' or any(s['state'] != 'prepared' for s in case['samples']):
        raise ValueError('Existing intent/outcome must not be replayed')
    for sample in case['samples']:
        if hashlib.sha256(sample['text'].encode()).hexdigest() != sample['sha256']:
            raise ValueError('Frozen probe content changed')
    case['phase'] = 'sending'
    save(case)
    for sample in case['samples']:
        sample.update(state='sending', intent_at=time.time())
        save(case)
        try:
            reply = await api.send_text(credentials, peer=credentials.owner_id, text=sample['text'],
                                        context_token=context, client_id=sample['client_id'])
        except BaseException as exc:
            sample['state'] = 'rejected' if isinstance(exc, BusinessError) else 'unknown'
            sample['error_type'] = type(exc).__name__
            case['phase'] = sample['state']
            save(case)
            raise
        sample.update(state='accepted', server_id=reply.get('message_id'), finished_at=time.time())
        save(case)
    case['phase'] = 'accepted'
    save(case)


def current_context(root, credentials):
    path = root / 'runtime.sqlite3'
    private_file(path)
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        schema.validate(db, credentials)
        row = db.execute('SELECT token,created_ms,seq FROM reply_context WHERE id=1').fetchone()
    if row is None or not row[0] or type(row[1]) is not int or not 0 < row[1] <= time.time() * 1000:
        raise ValueError('An existing real owner reply context is required; no send attempted')
    return row


async def run(action):
    root = Path.home() / 'Library/Application Support/wx-clawbot'
    path = root / 'md01-capability-case.json'
    credentials = load_credentials(root / 'credentials.json')
    if action == 'prepare':
        if path.exists():
            raise ValueError('Existing case must be reviewed, never replaced')
        _, created_ms, seq = current_context(root, credentials)
        samples = load_samples()
        case = {'phase': 'prepared', 'created_at': time.time(), 'owner_context_seq': seq,
                'owner_context_created_ms': created_ms,
                'credential_sha256': hashlib.sha256((root / 'credentials.json').read_bytes()).hexdigest(),
                'samples': [{**s, 'sha256': hashlib.sha256(s['text'].encode()).hexdigest(),
                             'client_id': 'md01-probe-' + uuid.uuid4().hex, 'state': 'prepared'} for s in samples]}
        write_json(path, case)
    else:
        private_file(path)
        case = json.loads(path.read_text())
        if action == 'send':
            if hashlib.sha256((root / 'credentials.json').read_bytes()).hexdigest() != case['credential_sha256']:
                raise ValueError('Binding changed; do not send')
            context, _, _ = current_context(root, credentials)
            # Freeze was prepared from the reviewed fixture; no runtime renderer runs here.
            reviewed = load_samples()
            if [(s['id'], s['text']) for s in reviewed] != [(s['id'], s['text']) for s in case['samples']]:
                raise ValueError('Fixture changed after freezing')
            await send_once(case, lambda c: write_json(path, c, replace=True), WechatApi(WeixinHttp()), credentials, context)
    return {'phase': case['phase'], 'samples': [{'id': s['id'], 'state': s['state'], 'chars': len(s['text']),
                                               'utf8_bytes': len(s['text'].encode())} for s in case['samples']],
            'native_tasks_submitted': 0, 'production_ledger_edits': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'send', 'report'])
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.action)), ensure_ascii=False))
