"""Explicit seeded 120-second offline load. No native, WeChat or production I/O."""
import argparse
import asyncio
import json
import math
from pathlib import Path
import random
import resource
import sys
import time
import unittest


def stats(samples):
    return {'samples':len(samples),'p95_ms':sorted(samples)[math.ceil(len(samples)*.95)-1],
            'max_ms':max(samples)}


def main(args):
    project = Path(__file__).resolve().parents[2]
    output = args.output.absolute()
    if not output.resolve().is_relative_to((project/'.tmp').resolve()) or output.exists():
        raise ValueError('A new report inside this candidate .tmp required')
    output.parent.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(project/'tests'))
    import test_async_questions as fixtures
    from wx_clawbot.agents.rpc import OutcomeUnknown
    from wx_clawbot.commands import CommandError,parse_command
    from wx_clawbot.managed import source_digest
    from wx_clawbot.runtime_state import RuntimeState
    from wx_clawbot.execution import Execution

    class Load(fixtures.AsyncFixture):
        async def test_seeded_load(self):
            rng = random.Random(20261103)
            started = time.monotonic()
            row = await self.question()
            registration=[]
            for index in range(100):
                item={**self.item,'id':'load-'+str(index)}
                t=time.perf_counter()
                await self.emit(item)
                registration.append((time.perf_counter()-t)*1000)
            rows=await self.state.async_rows(active=True)
            rpc_clients=[]
            async def native(method,params):
                self.assertEqual(method,'turn/steer')
                rpc_clients.append(params['clientUserMessageId'])
                await asyncio.sleep(rng.choice([0,.01,.05]))
                if rng.randrange(9)==0:
                    raise OutcomeUnknown('synthetic accepted but ACK lost')
                return {'turnId':self.turn}
            self.agent.rpc.request.side_effect=native
            controls=[];events=answers=duplicates=rejections=0
            disconnected=False
            while time.monotonic()-started < args.seconds:
                pick=rng.choice(rows)
                t=time.perf_counter()
                await self.engine.control(parse_command('/status'))
                controls.append((time.perf_counter()-t)*1000)
                await self.emit({**self.item,'id':pick['item_id']})
                duplicates+=1
                event={'method':'item/completed','params':{'threadId':'unrelated-thread','turnId':'foreign','item':self.item}}
                await self.engine.event(event);events+=1
                if not disconnected and rng.randrange(3)==0:
                    try:
                        await self.engine.control(parse_command('/answer '+pick['public_id']+' BETA'))
                        answers+=1
                    except CommandError:
                        rejections+=1
                if time.monotonic()-started>args.seconds*.7 and not disconnected:
                    await self.state.native_disconnected()
                    disconnected=True
                    for broker in self.engine.brokers.values():
                        broker.disconnect()
                    credentials,path=self.state.credentials,self.state.path
                    await self.engine.close()
                    await self.state.close()
                    self.state=await RuntimeState.open(path,credentials)
                    self.addAsyncCleanup(self.state.close)
                    self.controller.state=self.state
                    self.engine=Execution(self.controller)
                await self.engine.async_questions.expire()
                await asyncio.sleep(.02)
            self.assertEqual(len(rpc_clients),len(set(rpc_clients)))
            self.assertEqual(len(await self.state.tasks()),1)
            self.queue.add.assert_awaited_once()
            self.assertLess(stats(controls)['p95_ms'],1000)
            self.assertLess(stats(registration)['p95_ms'],1000)
            usage=resource.getrusage(resource.RUSAGE_SELF)
            result={'status':'passed','seed':20261103,'seconds':time.monotonic()-started,
                'source_sha256':source_digest(),'registration':stats(registration),'control':stats(controls),
                'duplicate_events':duplicates,'unrelated_events':events,'answer_calls':len(rpc_clients),
                'answer_client_unique':True,'answer_responses':answers,'refused_duplicate_commands':rejections,
                'original_task_submissions':self.queue.add.await_count,'task_rows':1,
                'disconnect_injected':disconnected,'production_writes':0,'wechat_sends':0,
                'final_active_question_rows':len(await self.state.async_rows(active=True)),
                'deadline_cache':len(self.engine.async_questions.deadlines)}
            result.update(sqlite_reopened=True,rss_peak_bytes=usage.ru_maxrss if sys.platform=='darwin' else usage.ru_maxrss*1024,
                cpu_user_seconds=usage.ru_utime,cpu_system_seconds=usage.ru_stime,
                retained_question_rows=await self.state._call(lambda:self.state.db.execute('SELECT count(*) FROM async_questions').fetchone()[0]),
                outbox_rows=await self.state._call(lambda:self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0]))
            output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({k:result[k] for k in ['status','seconds','registration','control','answer_calls','original_task_submissions']}),flush=True)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Load)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=120,choices=[120])
    main(parser.parse_args())
