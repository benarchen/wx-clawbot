"""Offline paired admission SQL measurement; no production ledger or native I/O."""

import argparse
import json
import math
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time

from wx_clawbot.occupancy import ACTIVE_FROM, ACTIVE_WHERE


PROJECT=Path(__file__).resolve().parents[2]
OLD="SELECT count(*) FROM tasks INDEXED BY task_active WHERE state NOT IN ('completed','failed','interrupted','cancelled')"
NEW=f"SELECT count(*) FROM {ACTIVE_FROM} WHERE {ACTIVE_WHERE}"


def measure(db,sql):
    start=time.perf_counter_ns();count=db.execute(sql).fetchone()[0]
    return (time.perf_counter_ns()-start)/1e6,count


def stats(samples):
    return {'samples_ms':samples,'median_ms':statistics.median(samples),'p95_ms':sorted(samples)[math.ceil(len(samples)*.95)-1],'max_ms':max(samples)}


def main(args):
    output=Path(args.output).absolute()
    if not output.resolve().is_relative_to((PROJECT/'.tmp').resolve()):
        raise ValueError('Output must be inside this candidate project .tmp')
    output.parent.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='queries-',dir=output.parent) as temp:
        for mode in ('settled','released_unknown'):
            for historical in (1000,10000,100000):
                path=Path(temp)/f'{mode}-{historical}.sqlite3'
                db=sqlite3.connect(path)
                try:
                    db.executescript("""CREATE TABLE tasks(id TEXT PRIMARY KEY,state TEXT NOT NULL);
                        CREATE INDEX task_active ON tasks(state) WHERE state NOT IN ('completed','failed','interrupted','cancelled');
                        CREATE TABLE task_occupancy(task_id TEXT PRIMARY KEY,state TEXT NOT NULL);
                        CREATE INDEX occupancy_active ON task_occupancy(state) WHERE state IN ('waiting','holding');""")
                    db.executemany('INSERT INTO tasks VALUES(?,?)',((f'h-{i}','completed' if mode=='settled' else 'unknown') for i in range(historical)))
                    db.executemany('INSERT INTO task_occupancy VALUES(?,?)',((f'h-{i}','released') for i in range(historical)))
                    db.executemany('INSERT INTO tasks VALUES(?,?)',((f'a-{i}','received') for i in range(128)))
                    db.executemany('INSERT INTO task_occupancy VALUES(?,?)',((f'a-{i}','waiting') for i in range(128)))
                    db.commit();db.execute('ANALYZE')
                    measure(db,OLD);measure(db,NEW)
                    old=[];new=[]
                    for i in range(15):
                        order=((OLD,old),(NEW,new)) if i%2==0 else ((NEW,new),(OLD,old))
                        for sql,samples in order:
                            elapsed,count=measure(db,sql);samples.append(elapsed)
                    old_count=db.execute(OLD).fetchone()[0];new_count=db.execute(NEW).fetchone()[0]
                    assert new_count==128
                    assert old_count==(128 if mode=='settled' else historical+128)
                    plan=[list(r) for r in db.execute('EXPLAIN QUERY PLAN '+NEW)]
                    assert any('occupancy_active' in str(r) for r in plan)
                    results.append({'mode':mode,'historical_rows':historical,'actual_active':128,
                        'old_result':old_count,'candidate_result':new_count,'old':stats(old),'candidate':stats(new),'candidate_plan':plan})
                finally:db.close()
    report={'passed':True,'samples_each':15,'warmups_each':1,'paired_alternating_order':True,
        'results':results,'notes':'settled mode is equivalent-result performance; released_unknown mode intentionally changes active admission semantics',
        'production_ledger_writes':0,'native_submissions':0,'wechat_sends':0}
    output.write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'cases':len(results),'output':str(output)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    main(parser.parse_args())
