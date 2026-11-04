"""Plan or explicitly build a private non-editable release; never starts services."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib


def build(project, output, *, python=sys.executable, apply=False, artifacts=None, wheel_sha256=None):
    project = project.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('A fresh release directory is required; existing releases are never overwritten')
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError('Release parent must use its real absolute path')
    config = tomllib.loads((project / 'pyproject.toml').read_text())
    if config['build-system']['requires'] != ['setuptools==80.9.0']:
        raise ValueError('The reviewed build backend must remain explicit')
    if (artifacts is None) != (wheel_sha256 is None):
        raise ValueError('Frozen artifacts and their explicit wheel SHA-256 must be supplied together')
    frozen = None
    if artifacts is not None:
        artifacts = artifacts.resolve(strict=True)
        frozen = json.loads((artifacts / 'release.json').read_text())
        name = frozen['wheel_name']
        if (Path(name).name != name or frozen['version'] != config['project']['version']
                or wheel_sha256 != frozen['wheel_sha256']
                or hashlib.sha256((artifacts / name).read_bytes()).hexdigest() != wheel_sha256
                or hashlib.sha256((artifacts / 'requirements.lock').read_bytes()).hexdigest() != frozen['lock_sha256']):
            raise ValueError('Frozen artifact identity does not match the requested release')
        if output.name != frozen['version'] + '-' + wheel_sha256[:12]:
            raise ValueError('Installed release directory must identify version and frozen wheel digest')
    plan = {'status': 'release_plan', 'version': config['project']['version'], 'schema': 6,
            'editable': False, 'starts_services': False, 'production_ledger_writes': 0, 'applied': False}
    if not apply:
        return plan
    output.mkdir(mode=0o700)
    os.chmod(output, 0o700)
    lock = output / 'requirements.lock'
    lock.write_bytes((project / 'requirements.lock').read_bytes())
    lock.chmod(0o600)
    with (output / 'build.log').open('w') as log:
        (output / 'build.log').chmod(0o600)
        def run(arguments, *, cwd=None):
            return subprocess.run(arguments, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                  check=True, timeout=300)
        if artifacts is not None:
            shutil.copyfile(artifacts / frozen['wheel_name'], output / frozen['wheel_name'])
            if lock.read_bytes() != (artifacts / 'requirements.lock').read_bytes():
                raise ValueError('Current dependency lock differs from frozen artifacts')
        else:
            with tempfile.TemporaryDirectory(prefix='.build-', dir=output) as temporary:
                source = Path(temporary)
                for name in ('pyproject.toml', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
                    shutil.copyfile(project / name, source / name)
                shutil.copytree(project / 'src/wx_clawbot', source / 'src/wx_clawbot',
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                for action in ('build_sdist', 'build_wheel'):
                    run([python, '-I', '-c', 'import setuptools.build_meta as b,sys; '
                         'getattr(b,sys.argv[1])(sys.argv[2])', action, str(output)], cwd=source)
        wheels = list(output.glob('*.whl'))
        if len(wheels) != 1:
            raise ValueError('Exactly one built project wheel required')
        wheel = wheels[0]
        wheel.chmod(0o600)
        for archive in output.glob('*.tar.gz'):
            archive.chmod(0o600)
        run([python, '-I', '-m', 'venv', str(output / '.venv')])
        interpreter = str(output / '.venv/bin/python')
        run([interpreter, '-I', '-m', 'pip', 'install', '--require-hashes', '-r', str(lock)])
        run([interpreter, '-I', '-m', 'pip', 'install', '--no-deps', str(wheel)])
        run([interpreter, '-I', '-m', 'pip', 'check'])
        manifest = output / 'release.json'
        run([interpreter, '-I', '-m', 'wx_clawbot.release', 'freeze', '--manifest', str(manifest),
             '--lock', str(lock), '--wheel', str(wheel)])
    value = json.loads((output / 'release.json').read_text())
    if frozen is not None and value != frozen:
        raise ValueError('Installed release manifest differs from the frozen artifact manifest')
    return {**plan, 'status': 'release_built', 'applied': True,
            'source_sha256': value['source_sha256'], 'wheel_sha256': value['wheel_sha256'],
            'lock_sha256': hashlib.sha256(lock.read_bytes()).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--wheel-sha256')
    args = parser.parse_args(argv)
    os.umask(0o077)
    os.environ.setdefault('SOURCE_DATE_EPOCH', '315532800')
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.output, apply=args.apply,
                          artifacts=args.artifacts, wheel_sha256=args.wheel_sha256)))


if __name__ == '__main__':
    main()
