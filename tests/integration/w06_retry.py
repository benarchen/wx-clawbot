"""Explicit real owner result retry; preparation is read-only, run needs duplicate consent."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.channels.http import WeixinHttp
from wx_clawbot.channels.private import load_credentials, private_directory, read_json, write_json
from wx_clawbot.channels.wechat import WechatApi
from wx_clawbot.delivery import Sender
from wx_clawbot.runtime_state import RuntimeState


def tasks_snapshot(root):
    with closing(sqlite3.connect((root / "runtime.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        return db.execute("SELECT * FROM tasks ORDER BY rowid").fetchall()


def prepare(args):
    root = private_directory(args.state_dir)
    path = root / "case.json"
    if path.exists():
        raise ValueError("Existing retry intent must not be replaced")
    load_credentials(args.owner_state_dir / "credentials.json")
    with closing(sqlite3.connect((args.owner_state_dir / "runtime.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT id,thread_id,client_id,turn_id,target,state FROM tasks ORDER BY rowid DESC LIMIT 1").fetchone()
        if row is None or row[5] != "completed" or not Path(json.loads(row[4])["cwd"]).is_relative_to(args.fixture_root.resolve(strict=True)):
            raise ValueError("Only an already completed task in the dedicated fixtures is eligible")
        result = db.execute("SELECT text FROM outbox WHERE task_id=? AND kind='final' ORDER BY rowid", (row[0],)).fetchall()
        if len(result) != 1 or not result[0][0] or len(result[0][0]) > 1000:
            raise ValueError("One short original result required for the controlled retry")
    label = "WX-W06-RETRY-" + uuid.uuid4().hex[:10].upper()
    text = label + "\n投递重试验收：仅发送已完成任务的既有结果，不再次执行。\n" + result[0][0]
    write_json(path, {"phase": "prepared", "label": label, "event_id": label, "text": text,
        "source_task_id": row[0], "thread_id": row[1], "client_id": row[2], "turn_id": row[3]})
    print(json.dumps({"status": "prepared_no_send", "label": label, "planned_http_sends": 2,
                      "planned_delivery_retries": 1, "native_submission_calls": 0}, ensure_ascii=False))


async def count_native(native, case):
    cursor, count = None, 0
    for _ in range(200):
        params = {"threadId": case["thread_id"], "itemsView": "full", "limit": 1, "sortDirection": "desc"}
        if cursor:
            params["cursor"] = cursor
        page = await native.rpc.request("thread/turns/list", params)
        for turn in page["data"]:
            for item in turn["items"]:
                if item.get("type") == "userMessage" and item.get("clientId") == case["client_id"]:
                    if turn["id"] != case["turn_id"] or turn.get("status") != "completed":
                        raise ValueError("Original native result identity changed")
                    count += 1
        cursor = page.get("nextCursor")
        if not cursor:
            return count
    raise ValueError("Native history bound exceeded")


async def worker(args):
    path = args.state_dir / "case.json"
    case = read_json(path)
    if case["phase"] != "first_send_intent":
        raise ValueError("Registered first send cannot be repeated")
    state = await RuntimeState.open(args.owner_state_dir / "runtime.sqlite3",
                                    load_credentials(args.owner_state_dir / "credentials.json"))
    http = WeixinHttp()
    try:
        if (await state.delivery_counts()).get("pending", 0):
            raise ValueError("Unrelated pending replies prevent an isolated crash test")
        await state.queue_reply(case["event_id"], case["text"], priority=0,
                                task_id=case["source_task_id"], kind="test_retry")
        reply = await state.claim_reply()
        assert reply["id"] == case["event_id"]
        response = await WechatApi(http).send_text(state.credentials, peer=state.credentials.owner_id,
            text=reply["text"], context_token=reply["context"], client_id=reply["client_id"])
        case.update(phase="fault_after_real_ack", first_server_message_id=response.get("message_id"))
        write_json(path, case, replace=True)
        os._exit(86)
    finally:
        await http.close()
        await state.close()


async def run(args):
    if not args.confirm_possible_duplicate or args.socket is None:
        raise ValueError("Explicit owner duplicate consent and original runtime socket required")
    path = args.state_dir / "case.json"
    case = read_json(path)
    if case["phase"] != "prepared":
        raise ValueError("Existing send state must be inspected, never repeated")
    baseline = tasks_snapshot(args.owner_state_dir)
    native = await CodexConnection.connect(args.socket)
    state = http = None
    try:
        before = await count_native(native, case)
        assert before == 1
        case.update(phase="first_send_intent", consent="owner_explicit_possible_duplicate_once",
                    original_native_execution_count=before)
        write_json(path, case, replace=True)
        argv = [sys.executable, str(Path(__file__).resolve()), "--worker", "--owner-state-dir", str(args.owner_state_dir),
                "--state-dir", str(args.state_dir), "--fixture-root", str(args.fixture_root)]
        process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, error = await asyncio.wait_for(process.communicate(), 60)
        if process.returncode != 86:
            case.update(phase="worker_failed_inspect_before_retry", worker_error=error.decode()[-4000:])
            write_json(path, case, replace=True)
            raise AssertionError("First-send crash point not reached")
        state = await RuntimeState.open(args.owner_state_dir / "runtime.sqlite3",
                                        load_credentials(args.owner_state_dir / "credentials.json"))
        http = WeixinHttp()
        await state.retry_reply(case["event_id"], confirm_unknown=True)
        assert await Sender(state, WechatApi(http)).once()
        attempts = await state.delivery_attempts(case["event_id"])
        assert [a["state"] for a in attempts] == ["unknown", "accepted"]
        assert tasks_snapshot(args.owner_state_dir) == baseline
        after = await count_native(native, case)
        assert after == before == 1
        report = {"actual_http_sends": 2, "explicit_result_retries": 1,
                  "native_execution_count_before": before, "native_execution_count_after": after,
                  "native_submission_calls_from_retry": 0, "owner_task_rows_unchanged": True,
                  "delivery_attempt_states": [a["state"] for a in attempts], "label": case["label"]}
        case.update(phase="verified", report=report)
        write_json(path, case, replace=True)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        if http:
            await http.close()
        if state:
            await state.close()
        await native.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-state-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--confirm-possible-duplicate", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args)
    else:
        asyncio.run(worker(args) if args.worker else run(args))
