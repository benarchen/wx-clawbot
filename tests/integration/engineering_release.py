"""Probe a frozen release with synthetic state and managed child processes only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time


CHILD = r'''
import asyncio, json, sys
from pathlib import Path
from wx_clawbot import managed
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.channels.wechat import Credentials
root=Path(sys.argv[2])
async def business():
    state=await RuntimeState.open(root/'runtime.sqlite3',Credentials('fixture-bot','fixture-owner',
        'https://ilinkai.weixin.qq.com/','fixture-token'))
    try:
        await state.queue_reply('retained','synthetic retained result')
        (root/'ready').write_text('ready')
        await asyncio.sleep(float(sys.argv[3]))
    finally:
        await state.close()
    return 0
managed.cli_main=lambda _:asyncio.run(business())
arguments=['--config',str(root/'unused-config.json'),'--state-dir',str(root)]
if sys.argv[1]!='-': arguments.extend(['--release-manifest',sys.argv[1]])
code=managed.main(arguments)
print(json.dumps({'code':code}))
raise SystemExit(code)
'''


def main(args):
    project = Path(__file__).resolve().parents[2]
    root, release = args.output.absolute(), args.release.resolve(strict=True)
    if root.exists() or not root.resolve().is_relative_to((project / '.tmp').resolve()):
        raise ValueError('A new private evidence directory in this project .tmp required')
    root.mkdir(mode=0o700, parents=True)
    interpreter, manifest = release / '.venv/bin/python', release / 'release.json'
    frozen = json.loads(manifest.read_text())
    environment = dict(os.environ, WX_CLAWBOT_RELEASE_MANIFEST=str(manifest))
    shadow = root / 'development-shadow'
    (shadow / 'wx_clawbot').mkdir(parents=True)
    (shadow / 'wx_clawbot/__init__.py').write_text('raise RuntimeError("DEVELOPMENT_SHADOW_IMPORTED")\n')
    environment['PYTHONPATH'] = str(shadow)
    probe = subprocess.run([str(interpreter), '-I', '-c',
        'import json; from wx_clawbot.release import verify_active; v=verify_active(); '
        'print(json.dumps({"version":v["version"],"source_sha256":v["source_sha256"]}))'],
        cwd=shadow, env=environment, capture_output=True, text=True, check=True, timeout=20)
    assert json.loads(probe.stdout)['source_sha256'] == frozen['source_sha256']
    raw = '```text\n' + '  A\\B  \r\n' * 5000 + '```\r\n'
    render = subprocess.run([str(interpreter), '-I', '-m', 'wx_clawbot.render_worker'],
        cwd=shadow, env=environment, input=json.dumps({'text': raw}).encode(),
        capture_output=True, check=True, timeout=25)
    assert json.loads(render.stdout)['parts']
    state = root / 'state'
    state.mkdir(mode=0o700)
    def run(name, path, *, sleep=0):
        with (root / (name + '.log')).open('w') as log:
            return subprocess.run([str(interpreter), '-I', '-c', CHILD, str(path), str(state), str(sleep)],
                cwd=shadow, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=25).returncode
    assert run('initial', manifest) == 0
    def snapshot():
        with sqlite3.connect((state / 'runtime.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 6
            return hashlib.sha256(json.dumps(list(db.execute('SELECT * FROM outbox ORDER BY id'))).encode()).hexdigest()
    before = snapshot()
    invalid = root / 'invalid-release.json'
    invalid.write_text(json.dumps({**frozen, 'version': '0.0.0'}))
    invalid.chmod(0o600)
    assert run('refused', invalid) != 0
    assert snapshot() == before
    assert run('recovery', manifest) == 0
    assert snapshot() == before
    (state / 'ready').unlink()
    with (root / 'holding.log').open('w') as stream:
        holder = subprocess.Popen([str(interpreter), '-I', '-c', CHILD, str(manifest), str(state), '20'],
            cwd=shadow, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        try:
            end = time.monotonic() + 10
            while not (state / 'ready').exists():
                if holder.poll() is not None or time.monotonic() >= end:
                    raise RuntimeError('Owned managed probe did not become ready')
                time.sleep(.01)
            assert run('duplicate', manifest) != 0
            holder.send_signal(signal.SIGTERM)
            assert holder.wait(timeout=15) == 143
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait()
    assert snapshot() == before
    assert run('after-signal', manifest) == 0
    assert snapshot() == before
    rollback = None
    if args.rollback_python is not None:
        old_environment = {k:v for k,v in environment.items() if k!='WX_CLAWBOT_RELEASE_MANIFEST'}
        check = subprocess.run([str(args.rollback_python), '-I', '-c',
            'import json; from importlib import metadata; from wx_clawbot.managed import source_digest; '
            'v=metadata.distribution("wx-clawbot"); '
            'assert not json.loads(v.read_text("direct_url.json") or "{}").get("dir_info",{}).get("editable"); '
            'print(json.dumps({"version":v.version,"source_sha256":source_digest()}))'],
            cwd=shadow, env=old_environment, capture_output=True, text=True, check=True, timeout=20)
        rollback = json.loads(check.stdout)
        if rollback['source_sha256'] != args.rollback_source_sha256:
            raise ValueError('Compatible rollback interpreter differs from reviewed source')
        with (root / 'compatible-rollback.log').open('w') as log:
            code = subprocess.run([str(args.rollback_python), '-I', '-c', CHILD, '-', str(state), '0'],
                cwd=shadow, env=old_environment, stdout=log, stderr=subprocess.STDOUT, timeout=25).returncode
        assert code == 0 and snapshot() == before
    proof = {'status': 'passed', 'version': frozen['version'], 'source_sha256': frozen['source_sha256'],
             'non_editable_manifest_verified': True, 'development_shadow_ignored': True,
             'isolated_render_child_verified': True, 'invalid_release_refused': True,
             'compatible_recovery_preserves_new_rows': True, 'single_managed_consumer': True,
             'sigterm_exit_code': 143, 'state_schema': 6, 'service_backend': 'synthetic_runtime_state',
             'compatible_previous_version': rollback,
             'wechat_sends': 0, 'native_submissions': 0, 'production_writes': 0, 'launchd_writes': 0}
    (root / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rollback-python', type=Path)
    parser.add_argument('--rollback-source-sha256')
    os.umask(0o077)
    args=parser.parse_args()
    if (args.rollback_python is None)!=(args.rollback_source_sha256 is None):
        parser.error('Compatible rollback interpreter and reviewed source digest must be supplied together')
    main(args)
