"""PERF01 discovery counts, sender wake latency and optional read-only SDK view."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

from performance import PROJECT, output_path, source_hash, stats
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.delivery import Sender
from wx_clawbot.hosts.discovery import ItermDirectory
from wx_clawbot.hosts.lifecycle import HostLifecycle
from wx_clawbot.runtime_state import RuntimeState


async def main(args):
    sys.path.insert(0,str(PROJECT/'tests'))
    from test_performance_discovery import discovery_counts
    from test_wechat_state import message
    report={'source_sha256':source_hash(PROJECT),'wechat_sends':0,'production_writes':0}
    report['discovery']=[await discovery_counts(PROJECT,n) for n in (2,10,30,100)]
    with tempfile.TemporaryDirectory(prefix='wake-',dir=args.output.parent) as tmp:
        account=Credentials('fixture-bot','fixture-owner','https://ilinkai.weixin.qq.com/','synthetic')
        state=await RuntimeState.open(Path(tmp)/'runtime.sqlite3',account)
        await state.accept_batch({'ret':0,'msgs':[message()]},phase='runtime')
        starts=asyncio.Queue()
        async def send(*_,**kwargs):
            starts.put_nowait(time.perf_counter())
            return {'ret':0}
        sender=asyncio.create_task(Sender(state,SimpleNamespace(send_text=send)).run())
        values=[]
        try:
            for i in range(100):
                await asyncio.sleep(.005)
                start=time.perf_counter()
                await state.queue_reply(f'wake-{i}','synthetic wake result')
                # Includes render plus commit as well as the wake, a stricter
                # start point than only measuring from after the commit.
                values.append(((await asyncio.wait_for(starts.get(),1))-start)*1000)
            report['wake_milliseconds']=stats(values)
            assert report['wake_milliseconds']['p95']<=100
        finally:
            sender.cancel()
            await asyncio.gather(sender,return_exceptions=True)
            await state.close()
    if args.sdk_read_only:
        # Never launches an absent host, creates terminals, changes settings,
        # reads screens, submits tasks, or answers requests.
        host=HostLifecycle()
        try:
            await host.ensure(launch=False,explicit=False)
            directory=ItermDirectory(lifecycle=host)
            view=await directory.discovery_view()
            endpoints=await view.discover()
            candidates=[e for e in endpoints if e.classification=='codex_candidate']
            checks=[await view.validate(e) for e in endpoints]
            report['sdk_view']={'live_connection':True,'endpoints':len(endpoints),
                'candidate_processes':len(candidates),
                'exact_process_checks':checks,
                'expected_candidate_flags':[e.classification=='codex_candidate' for e in endpoints],
                'screens_read':0,'native_submissions':0,'terminal_writes':0}
            assert checks==report['sdk_view']['expected_candidate_flags']
        finally:
            await host.close()
    report['passed']=True
    args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=output_path)
    parser.add_argument('--sdk-read-only',action='store_true')
    asyncio.run(main(parser.parse_args()))
