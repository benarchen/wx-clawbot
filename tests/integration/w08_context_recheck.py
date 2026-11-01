"""Explicit immediate owner-only observation; never revives an expired schedule."""
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

import w08_context as observation
from wx_clawbot import schema
from wx_clawbot.channels.private import load_credentials, private_directory, private_lease, read_json, write_json


PROJECT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_root(args):
    path = args.report_dir.absolute()
    if not path.resolve().is_relative_to(PROJECT / '.tmp'):
        raise ValueError('Observation records must remain in this project .tmp')
    return private_directory(path)


def source_check(plan, state_dir):
    if (digest(Path(plan['source_case'])) != plan['source_case_sha256']
            or digest(Path(plan['source_plan'])) != plan['source_plan_sha256']
            or digest(state_dir / 'credentials.json') != plan['credential_file_sha256']):
        raise ValueError('Frozen source or credentials changed; no send')
    account = load_credentials(state_dir / 'credentials.json')
    if plan['binding'] != [account.bot_id, account.owner_id]:
        raise ValueError('Owner binding changed; no send')


def prepare(args):
    if not args.confirm_owner_once:
        raise ValueError('Explicit immediate owner-only authorization required')
    if args.source_dir is None:
        raise ValueError('The frozen original observation directory is required')
    root = report_root(args)
    with private_lease(root / 'recheck.lock'):
        if (root / 'plan.json').exists() or (root / 'case.json').exists():
            raise ValueError('Existing intent must be inspected, never overwritten')
        source = args.source_dir.resolve(strict=True)
        old, scheduled = read_json(source / 'case.json'), read_json(source / 'followup-plan.json')
        account = load_credentials(args.state_dir / 'credentials.json')
        if (old['phase'] != 'no_rejection_observed_within_schedule' or len(old['attempts']) != 3
                or any(a['state'] != 'accepted' for a in old['attempts'])
                or scheduled['phase'] != 'waiting' or scheduled.get('attempts') != 0
                or 'send_intent_at' in scheduled or (source / 'fourth-observation-response.json').exists()
                or old['binding'] != [account.bot_id, account.owner_id]
                or digest(args.state_dir / 'credentials.json') != scheduled['credential_file_sha256']
                or old['created_ms'] != scheduled['source_created_ms']
                or hashlib.sha256(old['old_context'].encode()).hexdigest() != scheduled['old_context_sha256']):
            raise ValueError('Original record, allowance or binding changed; no send')
        try:
            os.kill(scheduled['waiting_pid'], 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError('An old waiter may still exist; inspect instead of sending')
        now = time.time()
        if now < old['created_ms'] / 1000 + 168 * 3600:
            raise ValueError('Old context has not reached seven days; no wait is started')
        case = {'phase': 'prepared', 'binding': old['binding'], 'old_context': old['old_context'],
                'created_ms': old['created_ms'], 'probe_hours': [168], 'attempts': [],
                'case_id': uuid.uuid4().hex[:10].upper()}
        write_json(root / 'case.json', case)
        plan = {'phase': 'prepared', 'authorized_immediate_owner_once': True,
                'old_attempt_limit': 1, 'fresh_attempt_limit': 1, 'binding': old['binding'],
                'source_case': str(source / 'case.json'), 'source_plan': str(source / 'followup-plan.json'),
                'source_case_sha256': digest(source / 'case.json'),
                'source_plan_sha256': digest(source / 'followup-plan.json'),
                'credential_file_sha256': digest(args.state_dir / 'credentials.json'),
                'prepared_case_sha256': digest(root / 'case.json'),
                'not_before': now, 'not_after': now + 1800,
                'new_authorization_not_late_retry': True}
        write_json(root / 'plan.json', plan)
        return summary(root)


def summary(root):
    plan, case = read_json(root / 'plan.json'), read_json(root / 'case.json')
    return {'phase': plan['phase'], 'case_phase': case['phase'], 'attempts': len(case['attempts']),
            'results': [{'state': a['state'], 'source': a.get('source'),
                         'actual_age_hours': round(a['observation_age_hours'], 3),
                         'error_code': a.get('error_code')} for a in case['attempts']],
            'source_records_unchanged': digest(Path(plan['source_case'])) == plan['source_case_sha256']
                and digest(Path(plan['source_plan'])) == plan['source_plan_sha256'],
            'native_calls': 0, 'production_ledger_writes': 0, 'natural_expiry_proven': False}


def require_fresh_context(state_dir, case, account):
    path = state_dir / 'runtime.sqlite3'
    with closing(sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True)) as db:
        schema.validate(db, account)
        row = db.execute('SELECT token,created_ms FROM reply_context WHERE id=1').fetchone()
    if not row or row[0] == case['old_context'] or row[1] / 1000 <= case['rejected_at']:
        raise ValueError('A distinct actual owner message after rejection is required')


async def execute(args):
    if not args.confirm_owner_once:
        raise ValueError('Explicit immediate owner-only authorization required')
    root = report_root(args)
    with private_lease(root / 'recheck.lock'):
        plan, case = read_json(root / 'plan.json'), read_json(root / 'case.json')
        source_check(plan, args.state_dir)
        if args.action == 'observe':
            if plan['phase'] != 'prepared' or case['phase'] != 'prepared' or case['attempts']:
                raise ValueError('Existing observation intent/outcome cannot be retried')
            if digest(root / 'case.json') != plan['prepared_case_sha256']:
                raise ValueError('Prepared observation changed; no send')
            if not plan['not_before'] <= time.time() <= plan['not_after']:
                plan['phase'] = 'missed_immediate_window_no_send'
                write_json(root / 'plan.json', plan, replace=True)
                return summary(root)
            intent, action = 'old_send_intent', 'run'
        elif args.action == 'recover':
            if (plan['phase'] != 'old_context_rejected' or case['phase'] != 'old_context_rejected'
                    or len(case['attempts']) != 1 or case['attempts'][0]['state'] != 'rejected'):
                raise ValueError('Only one fresh recovery after actual non-account rejection is allowed')
            require_fresh_context(args.state_dir, case, load_credentials(args.state_dir / 'credentials.json'))
            intent, action = 'fresh_send_intent', 'recover'
        else:
            raise ValueError('Explicit observe or recover action required')
        plan.update(phase=intent, intent_at=time.time())
        write_json(root / 'plan.json', plan, replace=True)
        request = argparse.Namespace(report_dir=root, state_dir=args.state_dir, action=action, wait=False)
        try:
            await observation.run(request)
        except BaseException:
            plan['phase'] = 'stopped_after_intent_no_retry'
            write_json(root / 'plan.json', plan, replace=True)
            raise
        case = read_json(root / 'case.json')
        plan.update(phase=case['phase'], finished_at=time.time())
        write_json(root / 'plan.json', plan, replace=True)
        return summary(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'report', 'observe', 'recover'))
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--state-dir', type=Path, default=Path.home() / 'Library/Application Support/wx-clawbot')
    parser.add_argument('--confirm-owner-once', action='store_true')
    args = parser.parse_args()
    result = prepare(args) if args.action == 'prepare' else summary(report_root(args)) if args.action == 'report' else asyncio.run(execute(args))
    print(json.dumps(result, ensure_ascii=False))
