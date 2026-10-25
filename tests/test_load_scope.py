import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class LoadScopeTests(unittest.TestCase):
    def test_observed_shell_wrappers_allow_only_exact_sleep_without_shell_side_effects(self):
        directory = str(Path(__file__).parent / "integration")
        with patch.object(sys, "path", [directory, *sys.path]):
            validate = importlib.import_module("w06_load").is_sleep_gate
        for command in ("sleep 90", "/bin/zsh -lc 'sleep 90'", "/bin/zsh -c 'sleep 90'"):
            self.assertTrue(validate(command))
        for command in (None, "sleep 90; touch NEVER", "/bin/zsh -c 'sleep 90 && touch NEVER'",
                        "/bin/zsh -c 'sleep $(touch NEVER)'", "/tmp/zsh -c 'sleep 90'", "sleep 900", "'broken"):
            self.assertFalse(validate(command))
