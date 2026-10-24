"""Explicit read-only W03 evidence audit; never submits tasks or answers prompts.

Historical UI observations and received requests come from a private live journal.
Every task outcome, endpoint, file effect and queue snapshot is re-read here.
Native TUI queue failures stay failures even when a separate CLI entry works.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import iterm2

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.hosts.connection import close_connection
from wx_clawbot.hosts.discovery import ItermDirectory, TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity


class EvidenceFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceFailure(message)


def users(turn):
    return [item for item in turn["items"] if item["type"] == "userMessage"]


def output(turn):
    return "\n".join(item.get("text", "") for item in turn["items"] if item["type"] == "agentMessage")


async def history(native, thread_id):
    turns, cursors, cursor = [], set(), None
    for _ in range(50):
        page = await native.read_turns(thread_id, cursor=cursor)
        turns.extend(page["data"])
        cursor = page.get("nextCursor")
        if not cursor:
            require(len({turn["id"] for turn in turns}) == len(turns), "Duplicate native turn page")
            return turns
        require(cursor not in cursors, "Native cursor repeated")
        cursors.add(cursor)
    raise EvidenceFailure("Native history audit exceeded bound")


def case_turn(record, turns, label, status):
    case = record["cases"][label]
    matching = [turn for turn in turns if turn["id"] == case["turn_id"]]
    require(len(matching) == 1 and matching[0]["status"] == status, "Native case terminal state differs")
    require(any(item.get("clientId") == case["submission_id"] for item in users(matching[0])),
            "Native client submission identity differs")
    return case, matching[0]


def paired_request(case):
    # Requests are historical wire observations, not inferred from a schema field.
    first = case.get("request", case.get("bridge_request"))
    second = case.get("other_request", case.get("observer_request"))
    require(first == second and isinstance(first, dict), "Two-subscriber request observation missing")
    require(first["params"]["turnId"] == case["turn_id"], "Interaction turn association differs")
    return first


async def verify(primary, comparison, desktop_entry):
    root = (Path(__file__).resolve().parents[2] / ".tmp").resolve()
    require(primary["project"] != comparison["project"], "Two fixture projects required")
    for record in (primary, comparison):
        require(Path(record["project"]).resolve().is_relative_to(root), "Only local temporary fixtures allowed")
    require(primary["socket"] == comparison["socket"], "Runtime differs between fixtures")
    native = await CodexConnection.connect(Path(primary["socket"]))
    host = None
    checks = {}
    try:
        host = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        directory = ItermDirectory(host)
        histories = []
        for record in (primary, comparison):
            p = record["process"]
            endpoint = TerminalEndpoint(record["terminal_id"], ProcessIdentity(
                p["pid"], tuple(p["started"]), p["executable"], p["tty_device"]), "codex_candidate")
            require(await directory.validate(endpoint), "Task-owned terminal process identity changed")
            require(tuple(record["runtime_identity"]) == native.runtime_identity, "Runtime generation changed")
            thread = await native.inspect(record["thread_id"])
            require(thread["sessionId"] == record["native_session_id"] and thread["model"] == record["model"]
                    and Path(thread["cwd"]).resolve() == Path(record["project"]).resolve(), "Native identity changed")
            require(thread["status"]["type"] == "idle", "Fixture has a pending task or interaction")
            require(not await NativeQueue(native, record["thread_id"], Path(record["project"])).list(),
                    "Native fixture queue is not empty")
            turns = await history(native, record["thread_id"])
            require(record["nonce"] in json.dumps(users(turns[0])), "Startup nonce differs")
            histories.append(turns)
        checks["same_original_terminals_and_native_threads"] = True
        turns, other_turns = histories
        project = Path(primary["project"])
        for label, filename, expected in (
            ("approval-probe", "approval-bridge-first.txt", "BRIDGE_FIRST"),
            ("desktop-first", "approval-desktop-first.txt", "DESKTOP_FIRST"),
        ):
            case, turn = case_turn(primary, turns, label, "completed")
            paired_request(case)
            require((project / filename).read_text() == expected, "Approval file effect differs")
            require(case.get("desktop_prompt_closed"), "Historical desktop dismissal evidence missing")
        checks["approval_both_first_answer_orders"] = True
        race, race_turn = case_turn(primary, turns, "simultaneous-conflict", "interrupted")
        paired_request(race)
        require(race["both_attempts_delivered"] and race["desktop_prompt_closed"]
                and not (project / "approval-race-once.txt").exists(), "Conflict result differs")
        checks["concurrent_conflicting_attempts_single_native_outcome"] = True
        for label in ("expiry-disconnect", "question-desktop-cancel"):
            case, _ = case_turn(primary, turns, label, "interrupted")
            require(case["desktop_form_closed"] if label.startswith("question") else case["desktop_prompt_closed"],
                    "Historical pending form dismissal missing")
        expired = primary["cases"]["expiry-disconnect"]
        require(all(expired[key] for key in ("expired_answer_rejected", "disconnected_late_answer_rejected",
                                             "old_generation_on_reconnect_rejected", "new_public_identity")),
                "Old interaction rejection evidence missing")
        require(not (project / "approval-expired-must-not-exist.txt").exists(), "Expired approval executed")
        checks["expiry_disconnect_reconnect_and_late_answers"] = True
        question, turn = case_turn(primary, turns, "question-multi-free-visible", "completed")
        paired_request(question)
        require(question["desktop_form_shown"] and question["desktop_form_closed"]
                and all(value in output(turn) for value in ("MULTI_BETA", "FREE_VISIBLE_W03")),
                "Visible multi-question/free-text outcome differs")
        question, turn = case_turn(primary, turns, "question-desktop-first", "completed")
        paired_request(question)
        require(question["invalid_answer_rejected"] and question["handled_bridge_answer_rejected"]
                and "DESK_ALPHA" in output(turn) and "DESK_BETA" not in output(turn), "Desktop-first answer differs")
        checks["multi_question_single_choice_free_text_invalid_and_cancel"] = True
        interrupted, _ = case_turn(primary, turns, "queue-cancel-interrupt-v2", "interrupted")
        require(interrupted["native_deleted"] == [True, True] and interrupted["running_file_confirmed"]
                and interrupted["file_absent_after_deadline"], "Interruption observation incomplete")
        require((project / "queue-running-v2.txt").read_text() == "RUNNING"
                and not (project / "queue-interrupted-v2-must-not-exist.txt").exists(), "Native interruption file effect differs")
        all_users = json.dumps([users(turn) for turn in turns])
        require(all(marker not in all_users for marker in ("QUEUE_CANCEL_ONE", "QUEUE_CANCEL_TWO")),
                "Deleted native queue input executed")
        checks["native_queue_deletion_and_actual_running_interruption"] = True
        mixed = comparison["cases"]["mixed-queue-164-v2"]
        lost_id = mixed["lost_client_id"]
        require(mixed["lost_phase"] == "outcome_unknown"
                and mixed["lost_reconciled_receipt"]["clientUserMessageId"] == lost_id
                and mixed["lost_cancel_native_deleted"], "Lost receipt reconciliation missing")
        require(all(item.get("clientId") != lost_id for turn in other_turns for item in users(turn)),
                "Cancelled unknown-outcome submission executed")
        checks["lost_queue_receipt_reconciled_without_resubmission"] = True
        fifo = comparison["cases"]["bridge-fifo-capacity"]
        require(fifo["eleventh_rejected"] and len(fifo["deleted"]) == 8 and all(fifo["deleted"]),
                "Real bridge admission/deletion evidence missing")
        checks["bridge_ten_item_admission_bound"] = True
        for label, markers in (
            ("bridge-fifo-capacity", ("FIFO_W03_0", "FIFO_W03_1")),
            ("desktop-native-queue", ("UNIFIED_BRIDGE_FIRST", "UNIFIED_DESKTOP_SECOND")),
        ):
            case = comparison["cases"][label]
            gate_index = next(i for i, turn in enumerate(other_turns) if turn["id"] == case["turn_id"])
            sequence = other_turns[gate_index:gate_index + 3]
            require(len(sequence) == 3 and all(turn["status"] == "completed" and len(users(turn)) == 1
                                             for turn in sequence), "Native FIFO turns were merged or incomplete")
            for turn, marker in zip(sequence[1:], markers):
                require(marker in output(turn), "Native FIFO output differs")
            snapshot = case.get("before_release", case.get("shared_native_snapshot"))
            require([users(turn)[0]["clientId"] for turn in sequence[1:]] ==
                    [item["clientUserMessageId"] for item in snapshot], "Queue to actual turn association differs")
        checks["bridge_fifo_distinct_turns"] = True
        checks["dedicated_desktop_cli_and_bridge_share_native_fifo"] = True
        for record, native_turns, case_label, client_key in (
            (primary, turns, "busy-queue", "bridge_first"),
            (comparison, other_turns, "mixed-queue-164-v2", "first_client_id"),
        ):
            case = record["cases"][case_label]
            client_id = case[client_key]["client_id"] if client_key == "bridge_first" else case[client_key]
            merged = [turn for turn in native_turns if any(item.get("clientId") == client_id for item in users(turn))]
            require(len(merged) == 1 and len(users(merged[0])) == 2, "Expected TUI mixed queue counterexample changed")
        checks["original_tui_tab_and_bridge_distinct_task_queue"] = False
        digest = hashlib.sha256((Path.home() / ".codex" / "config.toml").read_bytes()).hexdigest()
        require(digest == primary["expected_config_sha256"] == comparison["expected_config_sha256"],
                "Authorized global configuration baseline changed")
        checks["authorized_configuration_baseline_unchanged"] = True
        return {"checks": checks, "desktop_entry_contract": desktop_entry,
                "v03_passed": True, "v04_passed": desktop_entry == "dedicated-queue",
                "passed": desktop_entry == "dedicated-queue"}
    finally:
        await native.close()
        if host is not None:
            await close_connection(host)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--primary-record", type=Path, required=True)
    parser.add_argument("--comparison-record", type=Path, required=True)
    parser.add_argument("--desktop-entry", choices=("original-tui", "dedicated-queue"), default="original-tui")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = asyncio.run(verify(json.loads(args.primary_record.read_text()),
                                   json.loads(args.comparison_record.read_text()), args.desktop_entry))
    except Exception as exc:
        report = {"passed": False, "error": str(exc) if isinstance(exc, EvidenceFailure) else type(exc).__name__}
    report["checked_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(encoded)
    print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
