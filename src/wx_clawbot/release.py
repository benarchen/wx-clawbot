"""Verify a frozen installed release; this module never deploys or mutates state."""

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import sys

from . import __version__
from .channels.private import private_file, read_json


ENVIRONMENT_KEY = 'WX_CLAWBOT_RELEASE_MANIFEST'


def package_files(root):
    files = {}
    for path in sorted(root.rglob('*.py')):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Installed source files must be regular release files')
        files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def tree_digest(files, root):
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode() + b'\0' + (root / relative).read_bytes() + b'\0')
    return digest.hexdigest()


def lock_versions(path):
    versions = {}
    for line in path.read_text().splitlines():
        if line and not line[0].isspace() and not line.startswith('#'):
            name, version = line.split()[0].split('==', 1)
            versions[name.lower().replace('_', '-')] = version
    if not versions:
        raise ValueError('A nonempty exact runtime lock required')
    return versions


def installed_manifest(lock, wheel):
    root = Path(__file__).resolve().parent
    files = package_files(root)
    expected = lock_versions(lock)
    for name, version in expected.items():
        if metadata.version(name) != version:
            raise ValueError('Installed runtime dependency differs from lock')
    distribution = metadata.distribution('wx-clawbot')
    direct = json.loads(distribution.read_text('direct_url.json') or '{}')
    if direct.get('dir_info', {}).get('editable'):
        raise ValueError('Editable packages cannot be frozen releases')
    return {'format': 1, 'version': __version__, 'python': list(sys.version_info[:3]),
            'schema': 6, 'source_sha256': tree_digest(files, root), 'package_files': files,
            'lock_sha256': hashlib.sha256(lock.read_bytes()).hexdigest(),
            'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'wheel_name': wheel.name, 'dependencies': expected}


def verify(path):
    path = Path(path).absolute()
    value = read_json(path)
    required = {'format', 'version', 'python', 'schema', 'source_sha256', 'package_files',
                'lock_sha256', 'wheel_sha256', 'wheel_name', 'dependencies'}
    if (set(value) != required or value['format'] != 1 or value['version'] != __version__
            or value['python'] != list(sys.version_info[:3]) or value['schema'] != 6):
        raise ValueError('Release version, interpreter or schema manifest mismatch')
    release = path.parent.resolve(strict=True)
    if Path(sys.prefix).resolve(strict=True) != release / '.venv':
        raise ValueError('Interpreter does not belong to this release')
    root = Path(__file__).resolve().parent
    if not root.is_relative_to(release / '.venv'):
        raise ValueError('Package is outside the installed release')
    actual = package_files(root)
    if actual != value['package_files'] or tree_digest(actual, root) != value['source_sha256']:
        raise ValueError('Installed release source differs from frozen manifest')
    name = value['wheel_name']
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.whl'):
        raise ValueError('A release-local wheel filename required')
    lock, wheel = release / 'requirements.lock', release / name
    private_file(lock)
    private_file(wheel)
    if (hashlib.sha256(lock.read_bytes()).hexdigest() != value['lock_sha256']
            or hashlib.sha256(wheel.read_bytes()).hexdigest() != value['wheel_sha256']
            or lock_versions(lock) != value['dependencies']):
        raise ValueError('Release wheel or dependency lock differs from manifest')
    for name, version in value['dependencies'].items():
        if metadata.version(name) != version:
            raise ValueError('Installed dependency version differs from manifest')
    distribution = metadata.distribution('wx-clawbot')
    direct = json.loads(distribution.read_text('direct_url.json') or '{}')
    if distribution.version != __version__ or direct.get('dir_info', {}).get('editable'):
        raise ValueError('Release distribution metadata mismatch')
    return value


def verify_active(path=None):
    selected = str(path) if path is not None else os.environ.get(ENVIRONMENT_KEY)
    if selected is None:
        return None  # Development and the legacy explicit foreground entry remain supported.
    value = verify(Path(selected))
    os.environ[ENVIRONMENT_KEY] = str(Path(selected).absolute())
    return value


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'verify'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--wheel', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        from .channels.private import write_json
        if args.lock is None or args.wheel is None:
            parser.error('freeze requires --lock and --wheel')
        write_json(args.manifest, installed_manifest(args.lock, args.wheel))
    value = verify(args.manifest)
    print(json.dumps({'status': 'release_verified', 'version': value['version'],
        'schema': value['schema'], 'source_sha256': value['source_sha256'],
        'package_files': len(value['package_files'])}))


if __name__ == '__main__':
    main()
