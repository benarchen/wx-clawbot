import json
import tempfile
import unittest
from pathlib import Path

from wx_clawbot.config import ConfigError, load_projects, resolve_directory


class ConfigTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / ".tmp" / "tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.config = self.root / "config.json"

    def load(self, data):
        self.config.write_text(json.dumps(data))
        return load_projects(self.config)

    def test_load_and_resolve_existing_child(self):
        child = self.project / "child"
        child.mkdir()
        project, = self.load({"projects": [{"alias": "sample", "root": str(self.project)}]})
        self.assertEqual(resolve_directory(project, "child"), child)

    def test_invalid_shapes_and_private_fields_are_rejected(self):
        for data in [[], {}, {"projects": []}, {"projects": "bad"},
                     {"projects": [], "token": "secret"},
                     {"projects": [{"alias": "bad name", "root": str(self.project)}]},
                     {"projects": [{"alias": "sample", "root": "relative"}]}]:
            with self.subTest(data=data), self.assertRaises(ConfigError):
                self.load(data)

    def test_duplicate_alias_or_canonical_root_rejected(self):
        item = {"alias": "sample", "root": str(self.project)}
        for second in [item, {**item, "alias": "other"}]:
            with self.assertRaises(ConfigError):
                self.load({"projects": [item, second]})

    def test_unreadable_and_malformed_config(self):
        with self.assertRaises(ConfigError):
            load_projects(self.config)
        self.config.write_text("{")
        with self.assertRaises(ConfigError):
            load_projects(self.config)

    def test_empty_missing_and_symlink_escape_rejected(self):
        (self.project / "escape").symlink_to(self.root, target_is_directory=True)
        project, = self.load({"projects": [{"alias": "sample", "root": str(self.project)}]})
        for path in ["", "missing", "..", "escape"]:
            with self.subTest(path=path), self.assertRaises(ConfigError):
                resolve_directory(project, path)
