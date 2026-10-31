"""Facts extracted from versioned CLI schema generators, not synthetic RPC success."""

import json
import unittest
from pathlib import Path

from wx_clawbot.agents.codex import SUPPORTED_SERVER_VERSIONS


class ProtocolContractTests(unittest.TestCase):
    def test_supported_versions_have_recorded_schema_baselines(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/codex-contract.json").read_text())
        self.assertEqual(set(fixture["versions"]), SUPPORTED_SERVER_VERSIONS)

    def test_queue_requires_correlation_and_explicit_thread(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/codex-contract.json").read_text())
        for version, schemas in fixture["versions"].items():
            with self.subTest(version=version):
                self.assertEqual(set(schemas["v2/ThreadQueueAddParams.json"]["required"]),
                                 {"clientUserMessageId", "input", "threadId"})
                self.assertIn("clientInfo", schemas["v1/InitializeParams.json"]["required"])
                self.assertEqual(set(schemas["v2/ServerRequestResolvedNotification.json"]["required"]),
                                 {"requestId", "threadId"})
