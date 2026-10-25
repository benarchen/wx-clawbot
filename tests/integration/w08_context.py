"""Explicit natural-age context observation, not a TTL assertion or task retry.

Uses only this application's confirmed owner binding. No polling, native execution,
credential replacement, clock change or automatic retry of uncertain sends.
"""
import argparse
import asyncio
import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from wx_clawbot.channels.http import ProtocolError, WeixinHttp
from wx_clawbot.channels.private import load_credentials, private_directory, private_file, private_lease, read_json, write_json
from wx_clawbot.channels.state import ChannelState
from wx_clawbot.channels.wechat import BusinessError, DeliveryUnknown, SessionExpired, WechatApi
from wx_clawbot import schema


def oldest_context(root, credentials):
    candidates = []
    for filename in ("state.sqlite3", "runtime.sqlite3"):
        path = root / filename
        if not path.exists():
            continue
        private_file(path)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if filename == "runtime.sqlite3":
                schema.validate(db, credentials)
            elif db.execute("PRAGMA application_id").fetchone()[0] != ChannelState.APPLICATION_ID:
                raise ProtocolError("Context source is not this application's diagnostic ledger")
            if db.execute("SELECT bot,owner FROM channel WHERE id=1").fetchone() != (credentials.bot_id, credentials.owner_id):
                raise ProtocolError("Context source belongs to another binding")
            row = db.execute("SELECT context,created_ms FROM inbox WHERE context IS NOT NULL AND context<>'' ORDER BY created_ms LIMIT 1").fetchone()
            if row:
                candidates.append(row)
    if not candidates:
        raise ValueError("An actually received owner context is required")
    return min(candidates, key=lambda row: row[1])


def prepare(args):
    root = private_directory(args.report_dir.resolve())
    credentials = load_credentials(args.state_dir / "credentials.json")
    context, created_ms = oldest_context(args.state_dir, credentials)
    record = {"phase": "prepared", "binding": [credentials.bot_id, credentials.owner_id],
              "old_context": context, "created_ms": created_ms, "probe_hours": [24, 36, 48],
              "attempts": [], "case_id": uuid.uuid4().hex[:10].upper()}
    write_json(root / "case.json", record)
    print(json.dumps({"status": "prepared_no_send", "context_age_hours": round((time.time() * 1000 - created_ms) / 3600000, 3),
                      "observation_ages_hours": record["probe_hours"], "ttl_guaranteed": False}))


async def run(args):
    with private_lease(args.report_dir / "observation.lock"):
        return await observe(args)


async def observe(args):
    path = args.report_dir / "case.json"
    record = read_json(path)
    credentials = load_credentials(args.state_dir / "credentials.json")
    if record["binding"] != [credentials.bot_id, credentials.owner_id]:
        raise ProtocolError("Confirmed binding changed; stop the old context observation")
    if record["phase"] != ("old_context_rejected" if args.action == "recover" else "prepared"):
        raise ValueError("Existing send intent/outcome must not be repeated")
    http = WeixinHttp()
    api = WechatApi(http)
    try:
        indices = [None] if args.action == "recover" else list(range(len(record["attempts"]), len(record["probe_hours"])))
        for index in indices:
            if index is not None:
                age_hours = record["probe_hours"][index]
                not_before = record["created_ms"] / 1000 + age_hours * 3600
                if time.time() < not_before and not args.wait:
                    print(json.dumps({"status": "not_due", "seconds_until_observation": round(not_before-time.time()), "ttl_guaranteed": False}))
                    return
                while time.time() < not_before:
                    await asyncio.sleep(min(60, not_before-time.time()))
                    # The file may have been deliberately frozen by an operator.
                    if read_json(path)["phase"] != "prepared":
                        raise ValueError("Observation was superseded; do not send")
                context = record["old_context"]
                label = "WX-W08-CONTEXT-OLD-" + record["case_id"] + "-" + str(age_hours)
            else:
                ledger = args.state_dir / "runtime.sqlite3"
                private_file(ledger)
                with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as db:
                    schema.validate(db, credentials, versions=(2,))
                    row = db.execute("SELECT token,created_ms FROM reply_context WHERE id=1").fetchone()
                if not row or row[1] / 1000 <= record["rejected_at"] or row[0] == record["old_context"]:
                    raise ValueError("A distinct, newly received owner context after rejection is required")
                context = row[0]
                label = "WX-W08-CONTEXT-FRESH-" + record["case_id"]
            if load_credentials(args.state_dir / "credentials.json") != credentials:
                record["phase"] = "binding_changed_observation_stopped"
                write_json(path, record, replace=True)
                print(json.dumps({"status": record["phase"], "native_submission_calls": 0}), flush=True)
                return
            attempt = {"label": label, "intent_at": time.time(), "source": "old" if index is not None else "fresh",
                       "observation_age_hours": age_hours if index is not None else None,
                       "client_id": "w08-context-" + uuid.uuid4().hex, "state": "sending"}
            record["attempts"].append(attempt)
            record["phase"] = "send_intent"
            write_json(path, record, replace=True)
            try:
                response = await api.send_text(credentials, peer=credentials.owner_id, text=label + "\u2028本人授权的上下文自然时效观察，仅发送本条，不执行任务。",
                                               context_token=context, client_id=attempt["client_id"])
            except SessionExpired as exc:
                attempt.update(state="rejected", error_code=exc.code)
                record["phase"] = "binding_expired_not_context_proof"
            except BusinessError as exc:
                attempt.update(state="rejected", error_code=exc.code)
                record["phase"] = "old_context_rejected" if index is not None else "fresh_context_rejected"
                if index is not None:
                    record["rejected_at"] = time.time()
            except DeliveryUnknown:
                attempt["state"] = "unknown"
                record["phase"] = "send_unknown_no_retry"
            except BaseException:
                attempt["state"] = "unknown"
                record["phase"] = "send_unknown_no_retry"
                write_json(path, record, replace=True)
                raise
            else:
                attempt.update(state="accepted", server_message_id=response.get("message_id"))
                record["phase"] = "prepared" if index is not None else "fresh_after_old_rejection_accepted"
            attempt["finished_at"] = time.time()
            write_json(path, record, replace=True)
            print(json.dumps({"status": record["phase"], "source": attempt["source"], "send_state": attempt["state"],
                              "context_age_hours": round((time.time()*1000-record["created_ms"])/3600000, 3),
                              "native_submission_calls": 0}), flush=True)
            if record["phase"] != "prepared":
                return
        record["phase"] = "no_rejection_observed_within_schedule"
        write_json(path, record, replace=True)
    finally:
        await http.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "recover"))
    parser.add_argument("--state-dir", type=Path, default=Path.home() / "Library" / "Application Support" / "wx-clawbot")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--wait", action="store_true", help="Explicitly wait for natural age; no fake clock or retry")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args)
    else:
        asyncio.run(run(args))
