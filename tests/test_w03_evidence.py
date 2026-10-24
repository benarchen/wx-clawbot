"""Acceptance regression tests with synthetic history, without live connections."""

import subprocess
import sys
import unittest
from pathlib import Path

from integration.w03_verify import EvidenceFailure, V03_CHECKS, V04_CHECKS, config_baseline, desktop_receipt, distinct_fifo, verdict


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

    def test_confirmed_dedicated_entry_passes_without_falsifying_tui_counterexample(self):
        checks = dict.fromkeys((*V03_CHECKS, *V04_CHECKS), True)
        checks["dedicated_desktop_cli_and_bridge_share_native_fifo"] = True
        checks["original_tui_tab_and_bridge_distinct_task_queue"] = False
        result = verdict(checks)
        self.assertTrue(result["v03_passed"])
        self.assertTrue(result["v04_passed"])
        self.assertTrue(result["passed"])
        self.assertFalse(result["checks"]["original_tui_tab_and_bridge_distinct_task_queue"])
        self.assertEqual(result["desktop_entry_contract"], "dedicated-queue")

    def test_original_tui_result_cannot_cover_failed_confirmed_desktop_entry(self):
        checks = dict.fromkeys((*V03_CHECKS, *V04_CHECKS), True)
        checks["original_tui_tab_and_bridge_distinct_task_queue"] = True
        checks["dedicated_desktop_cli_and_bridge_share_native_fifo"] = False
        self.assertFalse(verdict(checks)["passed"])

    def test_desktop_receipt_requires_exact_thread_queue_and_distinct_inputs(self):
        case = {"shared_native_snapshot": [
            {"id": "q-a", "clientUserMessageId": "client-a"},
            {"id": "q-b", "clientUserMessageId": "client-b"},
        ], "desktop_receipt": {"thread_id": "thread-a", "queue_id": "q-b"}}
        self.assertEqual(desktop_receipt(case, "thread-a")["queue_id"], "q-b")
        with self.assertRaises(EvidenceFailure):
            desktop_receipt(case, "thread-other")
        case["desktop_receipt"]["queue_id"] = "q-a"
        with self.assertRaises(EvidenceFailure):
            desktop_receipt(case, "thread-a")

    def test_missing_or_truthy_textual_evidence_never_passes(self):
        checks = dict.fromkeys((*V03_CHECKS, *V04_CHECKS), True)
        checks.pop("native_queue_deletion_and_actual_running_interruption")
        self.assertFalse(verdict(checks)["passed"])
        checks["native_queue_deletion_and_actual_running_interruption"] = "passed"
        self.assertFalse(verdict(checks)["passed"])

    def test_explicit_external_config_approval_preserves_original_chain(self):
        original = "a" * 64
        primary = {"expected_config_sha256": original}
        comparison = {"expected_config_sha256": original}
        self.assertEqual(config_baseline(primary, comparison), original)
        approval = {"previous_sha256": original, "sha256": "b" * 64,
                    "confirmed_at": "2026-10-25 00:00", "reason": "user_accepted_external_desktop_configuration_sync"}
        primary["confirmed_config_baseline"] = approval
        with self.assertRaises(EvidenceFailure):
            config_baseline(primary, comparison)
        comparison["confirmed_config_baseline"] = dict(approval)
        self.assertEqual(config_baseline(primary, comparison), "b" * 64)
        primary["confirmed_config_baseline"]["previous_sha256"] = "c" * 64
        comparison["confirmed_config_baseline"]["previous_sha256"] = "c" * 64
        with self.assertRaises(EvidenceFailure):
            config_baseline(primary, comparison)

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
