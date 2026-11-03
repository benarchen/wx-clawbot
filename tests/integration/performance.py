"""Offline PERF01 baseline/candidate comparison. Never contacts a real service."""
import argparse
import ast
import asyncio
import hashlib
import inspect
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
BASELINE = '720cb073f62ee490d4c7fa53cdd00948d6f268f3'


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def stats(values):
    return {'samples': values, 'median': statistics.median(values),
            'p95': sorted(values)[math.ceil(len(values)*.95)-1], 'max': max(values)}


def output_path(value):
    path = Path(value).absolute()
    allowed = [PROJECT / '.tmp']
    cwd = Path.cwd()
    if (cwd/'pyproject.toml').exists() and 'name = "wx-clawbot"' in (cwd/'pyproject.toml').read_text():
        allowed.append(cwd/'.tmp')
    if not any(path.resolve().is_relative_to(root.resolve()) for root in allowed):
        raise ValueError('Performance output must stay inside this project .tmp')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def source_hash(root):
    return digest(b''.join(p.relative_to(root).as_posix().encode()+b'\0'+p.read_bytes()+b'\0'
                          for p in sorted((root/'src').rglob('*.py'))))


async def worker(args):
    source = args.source_root.resolve(strict=True)
    # Loading only a frozen source tree is intentional. No service CLI is invoked.
    sys.path.insert(0, str(source/'src'))
    from wx_clawbot.output import render_segments, display_text, RESULT_LIMIT, DisplaySegment
    from wx_clawbot.runtime_state import RuntimeState
    from wx_clawbot.channels.wechat import Credentials
    from wx_clawbot import schema
    from markdown_it import MarkdownIt
    fixture = json.loads((source/'tests/fixtures/wechat-markdown.json').read_text())['cases']
    report = {'scope': 'offline synthetic data; no WeChat/native/production database I/O',
              'source_sha256': source_hash(source), 'baseline_commit': BASELINE,
              'python': platform.python_version(), 'platform': platform.platform(), 'seed': 20261031,
              'dependencies':{name:importlib.metadata.version(name) for name in ('markdown-it-py','mdurl','websockets','iterm2','cryptography','Pillow')},
              'schema': schema.VERSION, 'render': {}, 'golden': {}, 'sql': {}}
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    rng = random.Random(20261031)
    texts = [(item['id'], item['text']) for item in fixture]
    atoms = [x['text'] for x in fixture] + ['plain English。\n\n', 'x\r\ny\r\n', 'literal\rdata', '# ASCII\n\n',
            '[label]: https://example.invalid/a(b)\n\n[label]', 'a\n---\nb', '中文x,y:1', 'one\ntwo\n', '    a\n']
    texts += [(f'random-{i}', '\n\n'.join(rng.choices(atoms,k=rng.randint(1,6)))) for i in range(200)]
    for name, raw in texts:
        parts = render_segments(raw)
        assert ''.join(p.source for p in parts) == display_text(raw)
        report['golden'][name] = digest(json.dumps([p.text for p in parts], ensure_ascii=False))
    plain = '汉字 English 123。\n\n'
    mixed = fixture[-1]['text']+'\n\n'
    examples = {'ordinary_2k': ('中文 English 内容。\n\n'*125),
        'ordinary_48k': ('中文 English 内容。\n\n'*3000),
        'maximum_plain': (plain*(RESULT_LIMIT//len(plain))),
        'maximum_code': '```python\n'+'  value = "A\\B"  \n\n'*24000+'```\n',
        'dense_small_blocks': '- 项目\n\n> 引用\n\n'*20000,
        'mixed': mixed*(RESULT_LIMIT//len(mixed)),
        'maximum_heading_expansion': '# x\n'*120000,
        'unclosed_delimiters': '*`[_~~\\字'*40000}
    for name, raw in examples.items():
        raw = raw[:RESULT_LIMIT]
        samples = []
        for _ in range(1 + (15 if len(raw)<100000 else 5)):
            before = time.perf_counter()
            parts = render_segments(raw)
            elapsed = time.perf_counter()-before
            assert elapsed<20
            samples.append(elapsed)
        assert ''.join(p.source for p in parts) == display_text(raw)
        assert all(0<len(p.text)<=8000 for p in parts)
        report['render'][name] = {'characters': len(raw), 'source_sha256': digest(raw),
            'payload_sha256': digest(json.dumps([p.text for p in parts], ensure_ascii=False)),
            'seconds': stats(samples[1:]), 'segments': len(parts)}
        save()
        print(json.dumps({'case': name, 'median_seconds': report['render'][name]['seconds']['median']}), flush=True)
    parse_calls = 0
    original = MarkdownIt.parse
    def counted(*a, **kw):
        nonlocal parse_calls
        parse_calls += 1
        return original(*a, **kw)
    with patch.object(MarkdownIt, 'parse', new=counted):
        render_segments(examples['ordinary_48k'])
    report['plain_48k_parse_calls'] = parse_calls
    tree = ast.parse(textwrap.dedent(inspect.getsource(RuntimeState.claim_reply)))
    claim = next(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and 'SELECT o.id' in n.value)
    active = "SELECT id FROM tasks" + (" INDEXED BY task_active" if schema.VERSION>=4 else "") + " WHERE state NOT IN ('completed','failed','interrupted','cancelled') ORDER BY rowid LIMIT 129"
    if schema.VERSION>=5:
        from wx_clawbot.occupancy import ACTIVE_FROM,ACTIVE_WHERE
        active=f"SELECT t.id FROM {ACTIVE_FROM} WHERE {ACTIVE_WHERE} ORDER BY t.rowid LIMIT 129"
    native = 'SELECT id FROM tasks WHERE thread_id=? AND turn_id=?'
    def measured(db, query, params=()):
        values=[]
        for _ in range(16):
            before=time.perf_counter(); result=db.execute(query,params).fetchall()
            values.append((time.perf_counter()-before)*1000)
        return {'milliseconds':stats(values[1:]),'rows':len(result),
                'plan':[row[3] for row in db.execute('EXPLAIN QUERY PLAN '+query,params)]}
    with tempfile.TemporaryDirectory(prefix='ledger-',dir=args.output.parent) as tmp:
        root=Path(tmp)
        credentials=Credentials('synthetic-bot','synthetic-owner','https://ilinkai.weixin.qq.com/','synthetic')
        state=await RuntimeState.open(root/'runtime.sqlite3',credentials)
        await state.close()
        db=sqlite3.connect(root/'runtime.sqlite3')
        prior=0
        for size in (1000,10000,100000):
            db.executemany("INSERT INTO outbox(id,text,priority,state,task_id,kind,created_at,body_sha256) VALUES(?,? ,1,'accepted',?,'final',0,?)",
                ((f'old-{i}','x'*128,f'old-task-{i//5}','a'*64) for i in range(prior,size)))
            db.executemany("INSERT INTO tasks(id,client_id,target,thread_id,input,state,created_at,updated_at,turn_id) VALUES(?,?,?,'historic-thread','synthetic','completed',?,0,?)",
                ((f'task-{i}',f'client-{i}','{}',i,f'turn-{i}') for i in range(prior,size)))
            db.execute("DELETE FROM outbox WHERE id LIKE 'new-%'")
            db.executemany("INSERT INTO outbox(id,text,priority,state,task_id,kind,created_at,body_sha256) VALUES(?,'new',1,?,'new-task','final',1,?)",
                ((f'new-{i}','unknown' if i==0 else 'pending','b'*64) for i in range(71)))
            db.commit()
            report['sql'][str(size)]={'blocked_claim':measured(db,claim), 'active':measured(db,active),
                'native_turn':measured(db,native,('historic-thread',f'turn-{size-1}'))}
            assert report['sql'][str(size)]['blocked_claim']['rows']==0
            prior=size
        db.close()
        state=await RuntimeState.open(root/'runtime.sqlite3',credentials)
        values=[]
        for i in range(31):
            before=time.perf_counter()
            await state.queue_reply(f'control-{i}',DisplaySegment('synthetic control'),priority=0,kind='control')
            values.append((time.perf_counter()-before)*1000)
        report['write_milliseconds']=stats(values[1:])
        await state.close()
    report['process_peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report['completed']=True
    save()


async def runtime_worker(args):
    source=args.source_root.resolve(strict=True)
    sys.path.insert(0,str(source/'src'))
    from wx_clawbot import output
    cases={'maximum_plain':'汉字 English 123。\n\n'*28000,
           'maximum_heading_expansion':'# x\n'*120000}
    result={'scope':'fresh runtime renderer process; parent plus largest exited child is a conservative peak sum',
            'source_sha256':source_hash(source),'cases':{}}
    prefix=lambda i,n:f'〔{i}/{n}〕synthetic-task\n\n' if n>1 else ''
    slots=asyncio.Semaphore(2)
    for name,body in cases.items():
        text='synthetic｜task｜completed\n'+body[:output.RESULT_LIMIT]
        values=[]
        for _ in range(6):
            start=time.perf_counter()
            if hasattr(output,'render_in_worker'):
                parts=await output.render_in_worker(text,prefix=prefix,slots=slots)
            else:
                parts=await asyncio.to_thread(output.render_segments,text,prefix=prefix)
            values.append(time.perf_counter()-start)
        result['cases'][name]={'seconds':stats(values[1:]),'payload_sha256':digest(json.dumps([p.text for p in parts],ensure_ascii=False))}
        print(json.dumps({'runtime_case':name,'median_seconds':statistics.median(values[1:])}),flush=True)
    parent=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    child=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    result.update(parent_peak_rss_bytes=parent,largest_child_peak_rss_bytes=child,
                  conservative_total_peak_rss_bytes=parent+child,completed=True)
    args.output.write_text(json.dumps(result,indent=2))


def compare(args):
    before=json.loads(args.baseline.read_text()); after=json.loads(args.candidate.read_text())
    checks={'golden_equal':before['golden']==after['golden'],
            'parse_calls_reduced_by_two':before['plain_48k_parse_calls']-after['plain_48k_parse_calls']>=2,
            'rss_budget':after['process_peak_rss_bytes']<=before['process_peak_rss_bytes']*1.2,
            'write_budget':after['write_milliseconds']['p95']<=max(before['write_milliseconds']['p95']*1.25,before['write_milliseconds']['p95']+2)}
    for name,b in before['render'].items():
        a=after['render'][name]
        checks[name+'_payload_equal']=a['payload_sha256']==b['payload_sha256']
        checks[name+'_budget']=a['seconds']['median']<=max(b['seconds']['median']*1.15,b['seconds']['median']+.02)
    for name in ('maximum_plain','maximum_heading_expansion'):
        checks[name+'_20_percent_faster']=after['render'][name]['seconds']['median']<=before['render'][name]['seconds']['median']*.8
    q=after['sql']['100000']; old=before['sql']['100000']
    checks['blocked_claim_budget']=q['blocked_claim']['milliseconds']['median']<=min(10,old['blocked_claim']['milliseconds']['median']*.1)
    checks['active_budget']=q['active']['milliseconds']['median']<=2
    checks['native_turn_budget']=q['native_turn']['milliseconds']['median']<=2
    result={'checks':checks,'passed':all(checks.values()),'baseline_source_sha256':before['source_sha256'],'candidate_source_sha256':after['source_sha256']}
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('baseline','candidate','compare','runtime'))
    parser.add_argument('--output',required=True,type=output_path)
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.action=='compare':
        return compare(args)
    if not args.worker:
        source=args.source_root
        if source is None and args.action=='baseline':
            source=args.output.parent/'baseline-source'
            if source.exists():
                raise ValueError('Use --source-root for an existing verified baseline; never overwrite it')
            files=subprocess.check_output(['git','ls-tree','-r','--name-only',BASELINE,'-z']).split(b'\0')
            for raw in files:
                if not raw: continue
                name=Path(raw.decode())
                if name.parts[0] not in ('src','tests') and name.name!='pyproject.toml': continue
                path=source/name; path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(subprocess.check_output(['git','show',BASELINE+':'+str(name)]))
        source=(source or PROJECT).resolve(strict=True)
        command=[sys.executable,str(Path(__file__).resolve()),args.action,'--worker','--source-root',str(source),'--output',str(args.output)]
        return subprocess.run(command,env={**os.environ,'PYTHONPATH':str(source/'src')},timeout=600).returncode
    asyncio.run(runtime_worker(args) if args.action=='runtime' else worker(args))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
