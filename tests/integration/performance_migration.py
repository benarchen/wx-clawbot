"""Synthetic schema-3 to schema-4 migration with full business-row digests."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from wx_clawbot import schema
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.runtime_state import RuntimeState
from performance import output_path


def snapshot(path):
    with sqlite3.connect(path) as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result={}
        for table in tables:
            digest=hashlib.sha256(); count=0
            for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid'):
                digest.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode()+b'\n')
                count+=1
            result[table]={'rows':count,'sha256':digest.hexdigest()}
        return result


async def main(args):
    with tempfile.TemporaryDirectory(prefix='migration-',dir=args.output.parent) as tmp:
        root=Path(tmp); path=root/'runtime.sqlite3'
        credentials=Credentials('synthetic-bot','synthetic-owner','https://ilinkai.weixin.qq.com/','synthetic')
        state=await RuntimeState.open(path,credentials)
        await state.close()
        with sqlite3.connect(path) as db:
            for statement in schema.PERFORMANCE_UPGRADE:db.execute('DROP INDEX '+statement.split()[2])
            db.execute('PRAGMA user_version=3')
            db.executemany("INSERT INTO tasks(id,client_id,target,thread_id,input,state,created_at,updated_at,turn_id) VALUES(?,?,?,'history','synthetic','completed',0,0,?)",
                ((f'task-{i}',f'client-{i}','{}',f'turn-{i}') for i in range(100000)))
            digest=hashlib.sha256(b'synthetic history').hexdigest()
            db.executemany("INSERT INTO outbox(id,text,priority,state,task_id,kind,created_at,body_sha256) VALUES(?,'synthetic history',1,'accepted',?,'final',0,?)",
                ((f'old-{i}',f'task-{i}',digest) for i in range(100000)))
            db.commit()
            assert schema.validate(db,credentials)==3
        before=snapshot(path)
        before_bytes=path.stat().st_size
        started=time.perf_counter(); result=schema.upgrade(root,credentials)
        seconds=time.perf_counter()-started
        after=snapshot(path); backup=snapshot(root/result['backup'])
        assert before==after==backup
        assert seconds<60
        with sqlite3.connect(path) as db:
            assert schema.validate(db,credentials)==4
            assert db.execute('PRAGMA quick_check').fetchall()==[('ok',)]
            assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
            index_bytes={name:db.execute('SELECT COALESCE(sum(pgsize),0) FROM dbstat WHERE name=?',(name,)).fetchone()[0]
                         for name in ('reply_task_kind','task_native_turn','task_active')}
        assert schema.upgrade(root,credentials)['status']=='current'
        report={'scope':'synthetic ledger only','from_schema':3,'to_schema':4,
                'seconds':seconds,'business_rows':before,'all_business_rows_and_backup_exact':True,
                'database_bytes_before':before_bytes,'database_bytes_after':path.stat().st_size,
                'new_index_bytes':index_bytes,
                'integrity_ok':True,'repeat_noop':True,'passed':True}
        args.output.write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=output_path)
    asyncio.run(main(parser.parse_args()))
