"""Seeded local ENG01 scale measurements; synthetic peers and ledgers only."""

import argparse
import asyncio
import gc
import hashlib
import json
import math
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


def stats(values):
    return {'samples': len(values), 'samples_ms': values, 'median_ms': statistics.median(values),
            'p95_ms': sorted(values)[math.ceil(len(values) * .95) - 1], 'max_ms': max(values)}


def compare(project, output, args):
    if args.baseline_python is None or args.candidate_python is None:
        raise ValueError('Explicit baseline and candidate interpreters required')
    cohorts = {'baseline': [], 'candidate': []}
    interpreters = {'baseline': args.baseline_python, 'candidate': args.candidate_python}
    for group in range(-1, 7):
        order = ('baseline', 'candidate') if group % 2 == 0 else ('candidate', 'baseline')
        for name in order:
            path = output.with_name(output.stem + f'-{group}-{name}.json')
            with path.with_suffix('.log').open('w') as stream:
                command = [str(interpreters[name]), '-I', str(Path(__file__).resolve()), 'measure',
                           '--output', str(path)]
                if name == 'candidate' and args.release_manifest is not None:
                    command.extend(['--release-manifest', str(args.release_manifest)])
                subprocess.run(command, cwd=project, stdout=stream, stderr=subprocess.STDOUT,
                    check=True, timeout=300)
            if group >= 0:
                cohorts[name].append(json.loads(path.read_text()))
    rows = []
    def key(case):
        return tuple(case.get(k) for k in ('kind', 'endpoints', 'threads', 'historical', 'active',
                                           'pages', 'concurrency', 'source_characters'))
    maps = {name: [{key(c): c for c in sample['cases']} for sample in samples]
            for name, samples in cohorts.items()}
    for identity in maps['candidate'][0]:
        cases = {name: [sample[identity] for sample in maps[name]] for name in maps}
        if any(c['status'] != 'passed' for c in cases['baseline']):
            rows.append({'case': identity, 'baseline_status': 'refused',
                         'candidate_status': cases['candidate'][0]['status'], 'speedup_claim': False})
            continue
        measurements = {name: [c.get('wall_ms', c.get('median_ms')) for c in cases[name]] for name in cases}
        medians = {name: statistics.median(values) for name, values in measurements.items()}
        rows.append({'case': identity, 'baseline_ms': measurements['baseline'],
            'candidate_ms': measurements['candidate'], 'median_ms': medians,
            'delta_percent': (medians['candidate'] / medians['baseline'] - 1) * 100})
    result = {'status': 'measured', 'seed': 20261103, 'warmup_pairs': 1, 'alternating_pairs': 7,
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'source_sha256': {name: [sample['source_sha256'] for sample in samples]
                                for name, samples in cohorts.items()},
              'rss_peak_bytes': {name: [sample['rss_peak_bytes'] for sample in samples]
                                 for name, samples in cohorts.items()},
              'child_rusage_maxrss_bytes': {name: [sample['child_rusage_maxrss_bytes'] for sample in samples]
                                            for name, samples in cohorts.items()}, 'cases': rows}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'pairs': 7, 'cases': len(rows)}))


def main(args):
    project = Path(__file__).resolve().parents[2]
    output = args.output.absolute()
    if output.exists() or not output.resolve().is_relative_to((project / '.tmp').resolve()):
        raise ValueError('A fresh report in this candidate .tmp is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.action == 'compare':
        return compare(project, output, args)
    sys.path.insert(0, str(project / 'tests'))
    import test_controller as fixtures
    if args.release_manifest is not None:
        from wx_clawbot.release import verify_active
        verify_active(args.release_manifest)
    from wx_clawbot.admission_recovery import terminal_evidence
    from wx_clawbot.agents.codex import CodexConnection
    from wx_clawbot.catalog import SessionCatalog
    from wx_clawbot.delivery import Sender
    from wx_clawbot.hosts.discovery import TerminalEndpoint
    from wx_clawbot.hosts.process import ProcessIdentity
    from wx_clawbot.managed import source_digest
    from wx_clawbot.output import render_in_worker, render_segments

    result = {'status': 'running', 'seed': 20261103, 'source_sha256': source_digest(),
              'wechat_sends': 0, 'native_submissions': 0, 'production_writes': 0, 'cases': []}
    result['harness_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['release_manifest_verified'] = args.release_manifest is not None
    child = subprocess.run([sys.executable, '-I', '-c',
        'from wx_clawbot.managed import source_digest; print(source_digest())'],
        capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if child != result['source_sha256']:
        raise ValueError('Parent and isolated child must load the same measured source')
    result['child_source_sha256'] = child

    class Scale(fixtures.ControllerTests):
        async def measure_catalog(self, endpoints, count):
            cwd = self.sessions[0].target.cwd
            threads = [{'id': f'thread-{i}', 'sessionId': f'native-{i}', 'cwd': str(cwd),
                        'status': {'type': 'idle'}, 'name': 'synthetic'} for i in range(count)]
            native = object.__new__(CodexConnection)
            native.runtime_identity = (1, 2)
            calls = 0
            async def rpc(method, params):
                nonlocal calls
                calls += 1
                if method == 'thread/list':
                    offset = int(params.get('cursor', '0'))
                    return {'data': threads[offset:offset + 100],
                            'nextCursor': str(offset + 100) if offset + 100 < count else None}
                if method == 'thread/read':
                    return {'thread': threads[int(params['threadId'].split('-')[1])]}
                raise AssertionError(method)
            native.rpc = SimpleNamespace(request=rpc)
            terminals = [TerminalEndpoint(str(i), ProcessIdentity(i + 1, (1, 2), '/fixture/codex', 1),
                                         'codex_candidate') for i in range(endpoints)]
            directory = SimpleNamespace(discover=AsyncMock(return_value=terminals),
                cwd=AsyncMock(return_value=cwd), validate=AsyncMock(return_value=True),
                current_thread_id=AsyncMock(side_effect=lambda endpoint:
                    f'thread-{count - 1 if int(endpoint.terminal_id) == 0 else int(endpoint.terminal_id) % count}'))
            catalog = SessionCatalog((self.controller.routes.projects['one'],), directory, native)
            start = time.perf_counter()
            try:
                found = await catalog.discover()
                self.assertEqual(len(found), endpoints)
                status = 'passed'
            except ValueError:
                status = 'refused'
            return {'kind': 'catalog', 'endpoints': endpoints, 'threads': count, 'status': status,
                    'wall_ms': (time.perf_counter() - start) * 1000, 'rpc_calls': calls}

        async def history(self, page):
            calls = 0
            task = {'state': 'unknown', 'thread_id': 'thread-one', 'turn_id': 'original',
                    'client_id': 'original-client', 'target': {'cwd': str(self.root)}}
            async def rpc(method, params):
                nonlocal calls
                calls += 1
                if method == 'thread/queue/list':
                    return {'data': [], 'nextCursor': None}
                index = int(params.get('cursor', '1'))
                last = index == page
                return {'data': [{'id': 'original' if last else f'unrelated-{index}', 'status': 'completed',
                    'items': [{'type': 'userMessage', 'clientId': 'original-client' if last else f'client-{index}'}]}],
                    'nextCursor': None if last else str(index + 1)}
            native = SimpleNamespace(inspect=AsyncMock(return_value={'id': 'thread-one',
                'cwd': str(self.root), 'status': {'type': 'idle'}}), rpc=SimpleNamespace(request=rpc))
            await terminal_evidence(native, [task], 'synthetic-generation')
            gc.collect()
            calls, timings = 0, []
            for _ in range(100):
                start = time.perf_counter()
                evidence = await terminal_evidence(native, [task], 'synthetic-generation')
                timings.append((time.perf_counter() - start) * 1000)
                self.assertEqual(evidence['turns'], {'original': 'completed'})
            return {'kind': 'native_history', 'pages': page, 'status': 'passed',
                    'wall_ms': statistics.median(timings), 'rpc_calls': calls / 100,
                    'in_process_warmup': 1, 'iterations': 100, 'samples_ms': timings}

        async def measure(self):
            for endpoints in (1, 8, 16):
                for count in (1, 100, 101, 1000):
                    result['cases'].append(await self.measure_catalog(endpoints, count))
            for pages in (1, 50, 200):
                result['cases'].append(await self.history(pages))
            for historical in (0, 10000, 100000):
                for active in (1, 16):
                    def populate():
                        self.state.db.execute('BEGIN IMMEDIATE')
                        try:
                            self.state.db.execute('DELETE FROM tasks')
                            now = time.time()
                            destination = json.dumps({'session_id': 'fixture', 'project_alias': 'one',
                                'cwd': str(self.root), 'origin': 'managed', 'thread_id': 'thread-one'})
                            self.state.db.executemany('''INSERT INTO tasks
                                (id,client_id,target,thread_id,input,state,created_at,updated_at)
                                VALUES(?,?,?,'thread-one','','completed',?,?)''',
                                ((f'h-{i}', f'c-{i}', destination, now, now) for i in range(historical)))
                            self.state.db.executemany('''INSERT INTO tasks
                                (id,client_id,target,thread_id,input,state,created_at,updated_at)
                                VALUES(?,?,?,'thread-one','','received',?,?)''',
                                ((f'a-{i}', f'ac-{i}', destination, now, now) for i in range(active)))
                            self.state.db.executemany("INSERT INTO task_occupancy VALUES(?,'waiting',0,'fixture','{}',NULL,?)",
                                ((f'a-{i}', now) for i in range(active)))
                            self.state.db.execute('COMMIT')
                        except BaseException:
                            self.state.db.execute('ROLLBACK')
                            raise
                    await self.state._call(populate)
                    samples = []
                    for _ in range(1001):
                        start = time.perf_counter()
                        rows = await self.state.tasks(active_only=True)
                        samples.append((time.perf_counter() - start) * 1000)
                        self.assertEqual(len(rows), active)
                    result['cases'].append({'kind': 'ledger', 'historical': historical, 'active': active,
                                            'status': 'passed', **stats(samples[1:])})
            for concurrency in (1, 8, 32):
                for size in (1024, 8192, 63 * 1024, 64 * 1024):
                    # ASCII makes byte count and the renderer's character threshold equal.
                    text = ('Normal **emphasis** and `literal_value`.\n\n' * (size // 40 + 2))[:size]
                    async def batch():
                        chunks = await asyncio.gather(*(render_in_worker(text, renderer=render_segments,
                            slots=self.state.render_slots) for _ in range(concurrency)))
                        self.assertTrue(all(chunks))
                    cold_start = time.perf_counter()
                    await batch()
                    cold_ms = (time.perf_counter() - cold_start) * 1000
                    gc.collect()
                    timings = []
                    for _ in range(7 if size <= 8192 else 1):
                        start = time.perf_counter()
                        await batch()
                        timings.append((time.perf_counter() - start) * 1000)
                    result['cases'].append({'kind': 'render', 'concurrency': concurrency,
                        'source_characters': len(text), 'source_bytes': len(text.encode()), 'status': 'passed',
                        'wall_ms': statistics.median(timings), 'cold_ms': cold_ms,
                        'in_process_warmup': 1, 'iterations': len(timings), 'samples_ms': timings})

        async def load(self):
            if args.seconds < 120:
                raise ValueError('The acceptance load must run for at least 120 seconds')
            controls, jobs, peaks, phases = [], set(), [], []
            started = time.monotonic()
            launches = 0
            source = ('Normal **emphasis** and `literal_value`.\n\n' * 1700)[:63 * 1024]
            initial_cpu = resource.getrusage(resource.RUSAGE_SELF)
            delivered = []
            class Api:
                async def send_text(self, *args, **kwargs):
                    delivered.append(kwargs['client_id'])
                    return {'ret': 0, 'message_id': len(delivered)}
            sender = Sender(self.state, Api())
            try:
                while time.monotonic() - started < args.seconds:
                    done = {job for job in jobs if job.done()}
                    for job in done:
                        job.result()
                    jobs -= done
                    if not jobs:
                        jobs = {asyncio.create_task(render_in_worker(source, renderer=render_segments,
                            slots=self.state.render_slots)) for _ in range(32)}
                        launches += len(jobs)
                    start = time.perf_counter()
                    message = await self.incoming('/status')
                    received = time.perf_counter()
                    await self.controller.prepare(message)
                    prepared = time.perf_counter()
                    self.assertTrue(await sender.once())
                    sent = time.perf_counter()
                    controls.append((sent - start) * 1000)
                    phases.append({'receive_ms': (received-start)*1000,
                        'prepare_ms': (prepared-received)*1000, 'send_ms': (sent-prepared)*1000})
                    peaks.append({'second': time.monotonic() - started, 'render_jobs': len(jobs)})
                    await asyncio.sleep(.02)
            finally:
                for job in jobs:
                    job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
            usage = resource.getrusage(resource.RUSAGE_SELF)
            result['load'] = {'seconds': time.monotonic() - started, 'controls': stats(controls),
                'render_launches': launches, 'peak_render_jobs': max(p['render_jobs'] for p in peaks),
                'last_30_seconds': [p for p in peaks if p['second'] >= args.seconds - 30],
                'cpu_user_seconds': usage.ru_utime - initial_cpu.ru_utime,
                'cpu_system_seconds': usage.ru_stime - initial_cpu.ru_stime,
                'path': 'accept_batch/controller.prepare/outbox/Sender.once/fake_api',
                'phases_ms': phases,
                'fake_deliveries': len(delivered),
                'remaining_render_jobs': sum(not j.done() for j in jobs)}
            self.assertGreaterEqual(len(controls), 100)
            self.assertEqual(len(delivered), len(controls))
            self.assertEqual(result['load']['remaining_render_jobs'], 0)
            self.assertLessEqual(result['load']['controls']['p95_ms'], 50)
            self.assertLessEqual(result['load']['controls']['max_ms'], 250)

        async def test_measure(self):
            # IsolatedAsyncioTestCase enables debug by default; production
            # asyncio.run uses debug=False. Measure both revisions in that mode.
            asyncio.get_running_loop().set_debug(False)
            result['event_loop_debug'] = asyncio.get_running_loop().get_debug()
            try:
                await (self.load() if args.action == 'load' else self.measure())
                result['status'] = 'passed'
            except BaseException:
                result['status'] = 'failed'
                raise
            finally:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                result['rss_peak_bytes'] = usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
                children = resource.getrusage(resource.RUSAGE_CHILDREN)
                result['child_rusage_maxrss_bytes'] = children.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')

    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Scale('test_measure')]))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    print(json.dumps({'status': result['status'], 'cases': len(result['cases']),
                      'source_sha256': result['source_sha256']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('measure', 'load', 'compare'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--baseline-python', type=Path)
    parser.add_argument('--candidate-python', type=Path)
    parser.add_argument('--release-manifest', type=Path)
    main(parser.parse_args())
