"""Run local project checks only; no installation, live native tasks or WeChat I/O."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib
import urllib.parse
import unicodedata
import uuid


def documents(project):
    for folder in ('docs', 'goals', 'config', 'tests/fixtures'):
        for path in (project / folder).rglob('*.json'):
            json.loads(path.read_text())
    for path in [project / 'README.md', project / 'AGENTS.md', project / 'ROADMAP.md',
                 *(project / 'docs').rglob('*.md'), *(project / 'goals').rglob('*.md')]:
        for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', path.read_text()):
            url = urllib.parse.urlsplit(target)
            if not url.scheme and url.path and not (path.parent / urllib.parse.unquote(url.path)).exists():
                raise ValueError('Missing local documentation target: ' + str(path.relative_to(project)))
            destination = path.parent / urllib.parse.unquote(url.path) if url.path else path
            if not url.scheme and url.fragment and destination.suffix == '.md':
                anchors, counts = set(), {}
                for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', destination.read_text(), re.M):
                    slug = ''.join(c for c in heading.lower() if c in ' -_'
                                   or unicodedata.category(c)[0] in 'LN').replace(' ', '-')
                    count = counts.get(slug, 0)
                    counts[slug] = count + 1
                    anchors.add(slug + (f'-{count}' if count else ''))
                if urllib.parse.unquote(url.fragment) not in anchors:
                    raise ValueError('Missing local documentation anchor: ' + str(path.relative_to(project)))
    version = tomllib.loads((project / 'pyproject.toml').read_text())['project']['version']
    package = (project / 'src/wx_clawbot/__init__.py').read_text()
    if not re.search(r'__version__\s*=\s*[\'"]' + re.escape(version) + r'[\'"]', package):
        raise ValueError('Project and package version differ')
    if 'schema 6' not in (project / 'README.md').read_text():
        raise ValueError('Current README must describe the supported runtime schema')
    if re.search(r'当前[^\n]*(?:schema 4|`0\.1\.0`)', (project / 'docs/image-input.md').read_text()):
        raise ValueError('Image guide still presents the historical prerequisite as current')
    readme = (project / 'README.md').read_text()
    if not all(text in readme for text in ('同步追问', '回答数组', '异步', 'q1', '字符串')):
        raise ValueError('Answer formats must distinguish synchronous and asynchronous input')
    for section in ('最近完成', '最近验证'):
        text = (project / 'ROADMAP.md').read_text().split('## ' + section + '\n', 1)[1].split('\n## ', 1)[0]
        if len(re.findall(r'^- ', text, re.M)) > 20:
            raise ValueError('Roadmap recent section exceeds its record bound')


def run(project, output):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    rows = []
    def command(name, arguments):
        start = time.perf_counter()
        with (output / (name + '.log')).open('w') as stream:
            result = subprocess.run(arguments, cwd=project, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=300)
        rows.append({'check': name, 'exit_code': result.returncode,
                     'seconds': time.perf_counter() - start})
        if result.returncode:
            raise RuntimeError('Local check failed: ' + name)
    summary = {'status': 'running', 'checks': rows, 'wechat_sends': 0,
               'native_submissions': 0, 'production_writes': 0}
    try:
        command('unittest', [sys.executable, '-I', '-c',
            'import unittest,sys; suite=unittest.defaultTestLoader.discover("tests"); '
            'count=suite.countTestCases(); print("discovered_tests",count,flush=True); '
            'result=unittest.TextTestRunner(verbosity=2).run(suite); '
            'sys.exit(0 if count and result.wasSuccessful() and not result.skipped else 1)'])
        command('compile', [sys.executable, '-I', '-m', 'compileall', '-q', 'src', 'tests', 'scripts'])
        command('dependencies', [sys.executable, '-I', '-m', 'pip', 'check'])
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=project,
                             capture_output=True, text=True)
        if top.returncode == 0 and Path(top.stdout.strip()).resolve() == project.resolve():
            command('diff', ['git', 'diff', '--check'])
        else:
            rows.append({'check': 'diff', 'status': 'not_a_git_checkout'})
        documents(project)
        rows.append({'check': 'documents', 'exit_code': 0})
        summary['status'] = 'passed'
    except Exception as error:
        summary.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    project = Path(__file__).resolve().parents[1]
    output = args.report_dir or project / '.tmp/check' / uuid.uuid4().hex
    if not output.resolve().is_relative_to((project / '.tmp').resolve()):
        parser.error('Reports must stay in this project .tmp')
    print(json.dumps(run(project, output), ensure_ascii=False))


if __name__ == '__main__':
    main()
