"""Explicit owner-only real HTTP crash test; never polls or executes an Agent task."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.channels.http import WeixinHttp
from wx_clawbot.channels.private import load_credentials, private_directory, read_json, write_json
from wx_clawbot.channels.wechat import WechatApi
from wx_clawbot.delivery import Sender
from wx_clawbot.runtime_state import RuntimeState


PHASES = ("before_http", "after_http_ack", "pending_outbox")


def update(path, **values):
    record = read_json(path)
    record.update(values)
    write_json(path, record, replace=True)


def primary_snapshot(root):
    with closing(sqlite3.connect((root / "runtime.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        context = db.execute("SELECT token,created_ms,seq FROM reply_context WHERE id=1").fetchone()
        if context is None:
            raise ValueError("Owner has no confirmed reply context")
        tasks = db.execute("SELECT id,state,queue_id,turn_id FROM tasks ORDER BY rowid").fetchall()
        return context, tasks


async def worker(args):
    journal = args.state_dir / (args.worker + ".json")
    case = read_json(journal)
    if case["phase"] != "worker_intent":
        raise ValueError("Existing send intent cannot be repeated")
    credentials = load_credentials(args.owner_state_dir / "credentials.json")
    state = await RuntimeState.open(args.state_dir / args.worker / "runtime.sqlite3", credentials)
    http = WeixinHttp()
    try:
        context, _ = primary_snapshot(args.owner_state_dir)
        # Same confirmed owner and application; this is a reply-context seed, not
        # a fabricated inbound message. This test never advances the receive cursor.
        await state._call(lambda: state.db.execute("INSERT INTO reply_context VALUES(1,?,?,?)", context))
        await state.queue_reply(case["event_id"], case["text"], priority=1, kind="test")
        if args.worker == "pending_outbox":
            update(journal, phase="fault_pending_outbox", real_http_calls=0)
            os._exit(86)
        reply = await state.claim_reply()
        update(journal, phase="send_intent_persisted", real_http_calls=0)
        if args.worker == "before_http":
            update(journal, phase="fault_before_http")
            os._exit(86)
        update(journal, phase="http_intent", real_http_calls=1)
        response = await WechatApi(http).send_text(credentials, peer=credentials.owner_id,
            text=reply["text"], context_token=reply["context"], client_id=reply["client_id"])
        update(journal, phase="fault_after_http_ack", native_message_id=response.get("message_id"), server_acknowledged=True)
        os._exit(86)  # Actual server acknowledgement, no local finish_reply.
    finally:
        await http.close()
        await state.close()


async def recover(args, journal):
    case = read_json(journal)
    credentials = load_credentials(args.owner_state_dir / "credentials.json")
    state = await RuntimeState.open(args.state_dir / case["fault"] / "runtime.sqlite3", credentials)
    http = WeixinHttp()
    try:
        if case["fault"] == "pending_outbox":
            sender = Sender(state, WechatApi(http))
            update(journal, phase="recovery_http_intent", recovery_http_calls=1)
            assert await sender.once()
            assert await state.delivery_counts() == {"accepted": 1}
            assert not await sender.once()
            actual_http_calls, final = 1, "accepted"
        else:
            api = SimpleNamespace(send_text=AsyncMock(side_effect=AssertionError("Unknown delivery must not be retried")))
            assert not await Sender(state, api).once()
            api.send_text.assert_not_awaited()
            assert await state.delivery_counts() == {"unknown": 1}
            actual_http_calls, final = case["real_http_calls"], "unknown"
        assert await state.tasks() == []
        report = {"fault": case["fault"], "real_http_calls": actual_http_calls,
                  "final_delivery_state": final, "native_tasks_created": 0,
                  "receive_polling_used": False, "wechat_transport_used": True,
                  "phone_receipt_confirmed": False}
        update(journal, phase="verified_server_side", report=report)
        return report
    finally:
        await http.close()
        await state.close()


async def main(args):
    if args.worker:
        await worker(args)
        return
    private_directory(args.state_dir)
    _, tasks_before = primary_snapshot(args.owner_state_dir)
    reports, phone_texts = [], []
    for fault in PHASES:
        journal = args.state_dir / (fault + ".json")
        if journal.exists():
            raise ValueError("Existing journal: inspect it instead of repeating sends")
        nonce = uuid.uuid4().hex[:12].upper()
        label = "WX-W06-SEND-" + fault.upper() + "-" + nonce
        text = label + "\n这是本人授权的崩溃恢复测试回执，不执行项目任务。"
        write_json(journal, {"phase": "worker_intent", "fault": fault, "event_id": label, "text": text})
        argv = [sys.executable, str(Path(__file__).resolve()), "--confirm-owner-test",
                "--owner-state-dir", str(args.owner_state_dir), "--state-dir", str(args.state_dir), "--worker", fault]
        process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, error = await asyncio.wait_for(process.communicate(), 90)
        except TimeoutError:
            update(journal, phase="observation_timeout_do_not_resend", worker_pid=process.pid)
            process.send_signal(2)
            await process.wait()
            raise
        if process.returncode != 86:
            update(journal, worker_exit=process.returncode, worker_error=error.decode()[-4000:])
            raise AssertionError("Worker did not reach registered crash; inspect without resending")
        reports.append(await recover(args, journal))
        if fault != "before_http":
            phone_texts.append(label)
    _, tasks_after = primary_snapshot(args.owner_state_dir)
    assert tasks_after == tasks_before
    report = {"cases": reports, "primary_tasks_unchanged": True, "expected_phone_labels": phone_texts,
              "phone_receipt_confirmed": False}
    write_json(args.state_dir / "report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-owner-test", required=True, action="store_true")
    parser.add_argument("--owner-state-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--worker", choices=PHASES)
    asyncio.run(main(parser.parse_args()))
