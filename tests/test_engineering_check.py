import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class EngineeringCheckTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('engineering_check', project / 'scripts/check.py')
        self.check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.check)
        parent = project / '.tmp/check-entry-tests'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('docs', 'goals', 'tests', 'src/wx_clawbot'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / 'README.md').write_text('# Test\n当前代码版本为 `1.2.3`，schema 6。同步追问回答数组，异步 q1 字符串。\n')
        (self.root / 'AGENTS.md').write_text('# Synthetic rules\n')
        (self.root / 'ROADMAP.md').write_text('## 最近完成\n\n## 最近验证\n')
        (self.root / 'docs/image-input.md').write_text('当前账本为 schema 6。\n')
        (self.root / 'pyproject.toml').write_text('[project]\nversion="1.2.3"\n')
        (self.root / 'src/wx_clawbot/__init__.py').write_text('__version__ = "1.2.3"\n')

    def test_consistent_synthetic_documents_pass(self):
        self.check.documents(self.root)

    def test_broken_link_is_refused(self):
        (self.root / 'README.md').write_text('[missing](missing.md)\n')
        with self.assertRaises(ValueError):
            self.check.documents(self.root)

    def test_broken_local_anchor_is_refused(self):
        path = self.root / 'README.md'
        path.write_text(path.read_text() + '\n[missing](#does-not-exist)\n')
        with self.assertRaises(ValueError):
            self.check.documents(self.root)

    def test_current_image_prerequisite_cannot_revert_to_old_schema(self):
        (self.root / 'docs/image-input.md').write_text('当前使用 schema 4。\n')
        with self.assertRaises(ValueError):
            self.check.documents(self.root)

    def test_package_and_project_version_must_match(self):
        (self.root / 'src/wx_clawbot/__init__.py').write_text('__version__ = "1.2.2"\n')
        with self.assertRaises(ValueError):
            self.check.documents(self.root)

    def test_empty_test_suite_returns_failed_summary(self):
        output = self.root / 'evidence'
        with self.assertRaises(RuntimeError):
            self.check.run(self.root, output)
        result = json.loads((output / 'summary.json').read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['checks'][0]['check'], 'unittest')
        self.assertNotEqual(result['checks'][0]['exit_code'], 0)
        self.assertEqual(len(result['checks']), 1)

    def test_dependency_failure_stops_before_document_success(self):
        def command(arguments, **kwargs):
            return SimpleNamespace(returncode=1 if 'pip' in arguments else 0)
        output = self.root / 'evidence'
        with patch.object(self.check.subprocess, 'run', side_effect=command), \
                patch.object(self.check, 'documents') as documents:
            with self.assertRaises(RuntimeError):
                self.check.run(self.root, output)
            documents.assert_not_called()
        result = json.loads((output / 'summary.json').read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['checks'][-1]['check'], 'dependencies')
