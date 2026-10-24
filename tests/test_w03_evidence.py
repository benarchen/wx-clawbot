"""Acceptance regression tests with synthetic history, without live connections."""

import subprocess
import sys
import unittest
from pathlib import Path

from integration.w03_verify import V03_CHECKS, V04_CHECKS, distinct_fifo, verdict


def turn(turn_id, client_id, text, reply, *, status="completed"):
    return {"id": turn_id, "status": status, "items": [
        {"type": "userMessage", "clientId": client_id,
         "content": [{"type": "text", "text": text}]},
        {"type": "agentMessage", "text": reply},
    ]}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.first = turn("turn-first", "bridge-client", "FIRST", "FIRST")
        self.second = turn("turn-second", "desktop-client", "SECOND", "SECOND")

    def check(self, turns):
        return distinct_fifo(turns, "bridge-client", "FIRST", "SECOND")

    def test_distinct_ordered_completed_turns_with_both_results_pass(self):
        self.assertTrue(self.check([self.first, self.second]))

    def test_two_messages_merged_into_one_turn_fail_even_if_both_markers_are_echoed(self):
        self.first["items"].insert(1, self.second["items"][0])
        self.first["items"][-1]["text"] = "FIRST SECOND"
        self.assertFalse(self.check([self.first]))

    def test_reversed_order_or_duplicate_submission_does_not_pass(self):
        self.assertFalse(self.check([self.second, self.first]))
        self.assertFalse(self.check([self.first, self.first, self.second]))

    def test_received_input_without_its_completed_output_does_not_pass(self):
        self.second["status"] = "inProgress"
        self.assertFalse(self.check([self.first, self.second]))
        self.second["status"] = "completed"
        self.second["items"][-1]["text"] = "different answer"
        self.assertFalse(self.check([self.first, self.second]))

    def test_dedicated_cli_success_never_covers_original_tui_failure(self):
        checks = dict.fromkeys((*V03_CHECKS, *V04_CHECKS), True)
        checks["dedicated_desktop_cli_and_bridge_share_native_fifo"] = True
        checks["original_tui_tab_and_bridge_distinct_task_queue"] = False
        result = verdict(checks)
        self.assertTrue(result["v03_passed"])
        self.assertFalse(result["v04_passed"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["desktop_entry_contract"], "original-tui")

    def test_missing_or_truthy_textual_evidence_never_passes(self):
        checks = dict.fromkeys((*V03_CHECKS, *V04_CHECKS), True)
        checks.pop("native_queue_deletion_and_actual_running_interruption")
        self.assertFalse(verdict(checks)["passed"])
        checks["native_queue_deletion_and_actual_running_interruption"] = "passed"
        self.assertFalse(verdict(checks)["passed"])

    def test_only_all_required_true_checks_pass(self):
        checks = dict.fromkeys((*V03_CHECKS, *V04_CHECKS), True)
        self.assertTrue(verdict(checks)["passed"])

    def test_cli_rejects_contract_override_before_accessing_a_record_or_runtime(self):
        script = Path(__file__).parent / "integration" / "w03_verify.py"
        result = subprocess.run([
            sys.executable, str(script), "--live", "--primary-record", "missing-primary.json",
            "--comparison-record", "missing-comparison.json", "--desktop-entry", "dedicated-queue",
        ], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)
