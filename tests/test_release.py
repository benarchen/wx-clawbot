import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wx_clawbot import release
from wx_clawbot.channels.private import write_json


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / '.tmp/release-tests'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.package = self.root / '.venv/lib/package'
        self.package.mkdir(parents=True)
        (self.package / 'release.py').write_text('# synthetic frozen package\n')
        (self.package / '__init__.py').write_text('# synthetic\n')
        self.lock, self.wheel = self.root / 'requirements.lock', self.root / 'project.whl'
        self.lock.write_text('fixture-dependency==1.0\n')
        self.wheel.write_bytes(b'synthetic wheel bytes')
        self.lock.chmod(0o600)
        self.wheel.chmod(0o600)
        self.editable = False
        distribution = SimpleNamespace(version=release.__version__, read_text=lambda *_:
            json.dumps({'dir_info': {'editable': self.editable}}))
        patches = [patch.object(release, '__file__', str(self.package / 'release.py')),
                   patch.object(release.sys, 'prefix', str(self.root / '.venv')),
                   patch.object(release.metadata, 'version', return_value='1.0'),
                   patch.object(release.metadata, 'distribution', return_value=distribution)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.path = self.root / 'release.json'
        write_json(self.path, release.installed_manifest(self.lock, self.wheel))

    def test_frozen_install_is_verified_without_mutation(self):
        before = self.path.read_bytes()
        self.assertEqual(release.verify(self.path)['version'], release.__version__)
        self.assertEqual(self.path.read_bytes(), before)

    def test_source_mutation_is_refused(self):
        (self.package / '__init__.py').write_text('# changed after freeze\n')
        with self.assertRaises(ValueError):
            release.verify(self.path)

    def test_symlink_with_identical_bytes_is_not_an_installed_source_file(self):
        path = self.package / '__init__.py'
        outside = self.root / 'outside.py'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            release.verify(self.path)

    def test_additional_source_is_refused(self):
        (self.package / 'unexpected.py').write_text('# unexpected import\n')
        with self.assertRaises(ValueError):
            release.verify(self.path)

    def test_wheel_mutation_is_refused(self):
        self.wheel.write_bytes(b'other wheel')
        with self.assertRaises(ValueError):
            release.verify(self.path)

    def test_lock_mutation_is_refused(self):
        self.lock.write_text('fixture-dependency==2.0\n')
        with self.assertRaises(ValueError):
            release.verify(self.path)

    def test_editable_metadata_cannot_claim_frozen_release(self):
        self.editable = True
        with self.assertRaises(ValueError):
            release.verify(self.path)

    def test_wrong_environment_is_refused(self):
        (self.root / 'other').mkdir()
        with patch.object(release.sys, 'prefix', str(self.root / 'other')):
            with self.assertRaises(ValueError):
                release.verify(self.path)

    def test_wrong_dependency_version_is_refused(self):
        with patch.object(release.metadata, 'version', return_value='2.0'):
            with self.assertRaises(ValueError):
                release.verify(self.path)

    def test_legacy_development_is_explicitly_unfrozen(self):
        with patch.dict(release.os.environ, {}, clear=True):
            self.assertIsNone(release.verify_active())

    def test_manifest_identity_is_inherited_by_children(self):
        with patch.dict(release.os.environ, {}, clear=True):
            release.verify_active(self.path)
            self.assertEqual(release.os.environ[release.ENVIRONMENT_KEY], str(self.path))
            self.assertEqual(release.verify_active()['source_sha256'],
                             release.verify(self.path)['source_sha256'])

    def test_schema_or_version_mismatch_is_refused(self):
        value = json.loads(self.path.read_text())
        value['schema'] = 5
        write_json(self.path, value, replace=True)
        with self.assertRaises(ValueError):
            release.verify(self.path)


class ReleaseBuildPlanTests(unittest.TestCase):
    def test_default_plan_does_not_create_directory_or_execute_tools(self):
        project = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('release_builder', project / 'scripts/build_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        parent = project / '.tmp/build-plan-test'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            output = Path(temporary) / 'new-release'
            with patch.object(module.subprocess, 'run') as run:
                result = module.build(project, output)
            self.assertFalse(result['applied'])
            self.assertFalse(output.exists())
            run.assert_not_called()
