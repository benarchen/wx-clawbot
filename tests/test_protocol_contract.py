"""Facts extracted from two real CLI schema generators, not synthetic RPC success."""

import json
import unittest
from pathlib import Path


class ProtocolContractTests(unittest.TestCase):
    def test_queue_requires_correlation_and_explicit_thread(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/codex-contract.json").read_text())
        for version, schemas in fixture["versions"].items():
            with self.subTest(version=version):
                self.assertEqual(set(schemas["v2/ThreadQueueAddParams.json"]["required"]),
                                 {"clientUserMessageId", "input", "threadId"})
                self.assertIn("clientInfo", schemas["v1/InitializeParams.json"]["required"])
                self.assertEqual(set(schemas["v2/ServerRequestResolvedNotification.json"]["required"]),
                                 {"requestId", "threadId"})
