"""Pairable PERF01 task-admission and atomic final-write benchmark, synthetic only."""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from performance import output_path, source_hash, stats


async def main(args):
    source=args.source_root.resolve(strict=True)
    sys.path.insert(0,str(source/'src'))
    sys.path.insert(0,str(source/'tests'))
    from wx_clawbot.channels.wechat import Credentials
    from wx_clawbot.runtime_state import RuntimeState
    from test_wechat_state import message
    with tempfile.TemporaryDirectory(prefix='writes-',dir=args.output.parent) as tmp:
        path=Path(tmp)/'runtime.sqlite3'
        credentials=Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','synthetic')
        state=await RuntimeState.open(path,credentials)
        await state.close()
        with sqlite3.connect(path) as db:
            db.executemany("INSERT INTO tasks(id,client_id,target,thread_id,input,state,created_at,updated_at,turn_id) VALUES(?,?,?,'history','synthetic','completed',0,0,?)",
                ((f'task-{i}',f'client-{i}','{}',f'turn-{i}') for i in range(100000)))
            db.executemany("INSERT INTO outbox(id,text,priority,state,task_id,kind,created_at,body_sha256) VALUES(?,'synthetic history',1,'accepted',?,'final',0,?)",
                ((f'old-{i}',f'task-{i}','a'*64) for i in range(100000)))
        state=await RuntimeState.open(path,credentials)
        admission=[];final=[]
        try:
            for i in range(31):
                accepted=(await state.accept_batch({'ret':0,'msgs':[message(i+1,text='synthetic task')]},phase='runtime'))['accepted'][0]
                start=time.perf_counter()
                task=await state.task_intent(accepted.message_id,{'thread_id':'synthetic-thread'},accepted.text)
                admission.append((time.perf_counter()-start)*1000)
                await state.task_update(task['id'],'running',turn_id=f'new-turn-{i}')
                start=time.perf_counter()
                assert await state.task_finish(task['id'],'completed','synthetic final',turn_id=f'new-turn-{i}')
                final.append((time.perf_counter()-start)*1000)
            report={'source_sha256':source_hash(source),'scope':'100000 synthetic completed tasks and accepted final replies; no production I/O',
                'admission_milliseconds':stats(admission[1:]),'atomic_final_milliseconds':stats(final[1:]),
                'completed':True}
            args.output.write_text(json.dumps(report,indent=2))
            print(json.dumps({k:v for k,v in report.items() if k not in ('admission_milliseconds','atomic_final_milliseconds')}))
        finally:
            await state.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=output_path)
    asyncio.run(main(parser.parse_args()))
