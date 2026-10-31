"""Explicit owner-WeChat interaction acceptance in an existing dedicated fixture.

prepare never starts native work. start requires a real persisted owner /attach.
No synthetic inbox, native answers, model replacement or global config writes.
inspect gathers evidence; it does not declare product acceptance automatically.
"""

import argparse
import asyncio
import hashlib
import json
import shlex
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from wx_clawbot import schema
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.channels.private import load_credentials, private_directory, private_file, read_json, write_json
from wx_clawbot.hosts.connection import close_connection
from wx_clawbot.hosts.discovery import ItermDirectory, inspect_terminal
from wx_clawbot.operations import live_instance
from wx_clawbot.sessions import SessionBinding, verify_binding


CASES = ("approval-phone-first", "approval-desktop-first", "approval-conflict", "approval-expired",
         "approval-disconnected", "question-phone-first", "question-desktop-first")


def native_settings(reply):
    mode, sandbox = reply.get("collaborationMode"), reply.get("sandbox")
    if (not isinstance(mode, dict) or not isinstance(sandbox, dict)
            or reply.get("approvalPolicy") is None or reply.get("approvalsReviewer") is None):
        raise ValueError("Complete original thread settings required before a test override")
    return {"approvalPolicy": reply["approvalPolicy"], "approvalsReviewer": reply["approvalsReviewer"],
            "sandboxPolicy": sandbox, "collaborationMode": mode}


def ledger(root, credentials):
    path = root / "runtime.sqlite3"
    private_file(path)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        schema.validate(db, credentials, versions=(2, schema.VERSION))
    except BaseException:
        db.close()
        raise
    return closing(db)


def require_observer(db, thread_id):
    row = db.execute("SELECT snapshot FROM routes WHERE id=1").fetchone()
    snapshot = json.loads(row[0]) if row else {}
    observer = snapshot.get("observer")
    if not isinstance(observer, dict) or observer.get("thread_id") != thread_id:
        raise ValueError("Owner must actually attach this dedicated native thread before starting")


async def prepare(args):
    record = read_json(args.fixture_record)
    matches = [c for c in record.get("cases", []) if Path(c["root"]).resolve() == args.fixture_root.resolve(strict=True)]
    if len(matches) != 1 or not args.fixture_root.resolve().is_relative_to((Path.cwd() / ".tmp").resolve()):
        raise ValueError("One task-owned temporary project, not a business project, is required")
    source = matches[0]
    if hashlib.sha256((args.codex_home / "config.toml").read_bytes()).hexdigest() != args.expected_config_sha256:
        raise ValueError("Configuration differs from the explicitly approved baseline")
    root = private_directory(args.report_dir.resolve())
    if (root / "case.json").exists():
        raise FileExistsError("Existing acceptance case must not be replaced")
    credentials = load_credentials(args.state_dir / "credentials.json")
    target = args.fixture_root.resolve() / ("w08-" + args.case + ".txt")
    if args.case.startswith("approval-") and target.exists():
        raise ValueError("Dedicated effect file already exists; do not overwrite it")
    case = {"phase": "prepared", "case": args.case, "socket": record["socket"], "fixture": source,
            "config_sha256": args.expected_config_sha256, "binding": [credentials.bot_id, credentials.owner_id],
            "target": str(target), "effect": "W08-" + args.case.upper() + "-" + uuid.uuid4().hex[:8].upper()}
    native, host, _, binding = await connect(case)
    try:
        case["attested_process"] = json.loads(json.dumps(asdict(binding.endpoint.process)))
        resumed = await native.rpc.request("thread/resume", {"threadId": binding.thread_id, "excludeTurns": True})
        case["original_settings"] = native_settings(resumed)
        case["original_permission_profile"] = resumed.get("activePermissionProfile")
    finally:
        await native.close()
        await close_connection(host)
    write_json(root / "case.json", case)
    return {"status": "prepared_no_native_submission", "case": args.case}


async def connect(case):
    import iterm2
    native = await CodexConnection.connect(Path(case["socket"]))
    host = None
    try:
        host = await iterm2.Connection.async_create()
        app = await iterm2.async_get_app(host)
        terminal = app.get_session_by_id(case["fixture"]["terminal_id"])
        if terminal is None:
            raise ValueError("Original dedicated terminal is absent")
        endpoint = await inspect_terminal(terminal)
        if case.get("attested_process") is not None and (
            endpoint.process is None or json.loads(json.dumps(asdict(endpoint.process))) != case["attested_process"]
        ):
            raise ValueError("Dedicated process generation changed; no native work or desktop input allowed")
        source = case["fixture"]
        if tuple(source["runtime_identity"]) != native.runtime_identity:
            raise ValueError("Original dedicated runtime changed")
        binding = SessionBinding(endpoint, Path(source["root"]), native.runtime_identity,
                                 source["thread_id"], source["native_session_id"])
        await verify_binding(binding, ItermDirectory(host), native)
        return native, host, terminal, binding
    except BaseException:
        await native.close()
        if host:
            await close_connection(host)
        raise


def validate_command(actual, expected):
    tokens = shlex.split(actual)
    if len(tokens) == 3 and tokens[:2] in (["/bin/zsh", "-lc"], ["/bin/zsh", "-c"]):
        tokens = shlex.split(tokens[2])
    if tokens != shlex.split(expected):
        raise ValueError("Native approval command differs; do not answer")


async def act(args):
    path = args.report_dir / "case.json"
    case = read_json(path)
    credentials = load_credentials(args.state_dir / "credentials.json")
    if case["binding"] != [credentials.bot_id, credentials.owner_id]:
        raise ValueError("Confirmed owner binding changed")
    if hashlib.sha256((args.codex_home / "config.toml").read_bytes()).hexdigest() != case["config_sha256"]:
        raise ValueError("Approved configuration baseline changed")
    native, host, terminal, binding = await connect(case)
    try:
        if args.action == "start":
            if case["phase"] != "prepared" or live_instance(args.state_dir) is None:
                raise ValueError("Existing intent cannot repeat and verified foreground must be running")
            with ledger(args.state_dir, credentials) as db:
                require_observer(db, binding.thread_id)
            before = await native.inspect(binding.thread_id)
            queue = NativeQueue(native, binding.thread_id, binding.project)
            if before["status"]["type"] != "idle" or await queue.list():
                raise ValueError("Dedicated thread must be idle with an empty queue")
            # This subscribes to the already-loaded thread and checks the same model.
            resumed = await native.rpc.request("thread/resume", {"threadId": binding.thread_id, "excludeTurns": True})
            if any(resumed["thread"].get(k) != before.get(k) for k in ("id", "cwd", "sessionId", "model", "modelProvider")):
                raise ValueError("Original thread identity or model changed")
            if native_settings(resumed) != case["original_settings"]:
                raise ValueError("Restore the previous dedicated test's settings before starting another")
            if resumed.get("activePermissionProfile") != case.get("original_permission_profile"):
                raise ValueError("Original dedicated permission profile changed")
            settings = {"model": before["model"], "reasoning_effort": resumed.get("reasoningEffort"), "developer_instructions": None}
            if case["case"].startswith("approval-"):
                if Path(case["target"]).exists():
                    raise ValueError("Effect file already exists")
                command = "printf %s " + shlex.quote(case["effect"]) + " > " + shlex.quote(case["target"])
                prompt = ("W08 本人授权的专用双端审批验收，仅允许创建本命令指定的临时文件。"
                          "只用 exec_command 的 require_escalated 为精确命令申请一次性人工审批：" + command
                          + " 。拒绝、取消或错误后立即停止，禁止绕过、重试、其他文件操作或配置变更。最后仅报告实际结果。")
                mode = "default"
                case["expected_command"] = command
            else:
                question = ("同一个 request_user_input 请求包含两题：id=choice，选项 PHONE_ALPHA 与 PHONE_BETA；"
                            "id=note，选项 NOTE_BASE 与 NOTE_EXTRA，isOther=true，允许选择其他并自由填写。" if case["case"] == "question-phone-first" else
                            "仅一个问题 id=choice，选项 DESK_ALPHA 与 DESK_BETA。")
                prompt = ("W08 专用两端追问验收。不读写文件，不调用其他工具。立即用 " + question
                          + " 收到答案后只复述实际答案，不自行回答或重复提问。")
                mode = "plan"
            case.update(phase="native_submission_intent", client_id="w08-interaction-" + uuid.uuid4().hex,
                        prompt=prompt, model=before["model"], submitted_at=time.time())
            write_json(path, case, replace=True)
            result = await native.rpc.request("turn/start", {"threadId": binding.thread_id,
                "input": [{"type": "text", "text": prompt}], "clientUserMessageId": case["client_id"],
                "approvalPolicy": "on-request", "approvalsReviewer": "user",
                "collaborationMode": {"mode": mode, "settings": settings}})
            case.update(phase="native_accepted", turn_id=result["turn"]["id"])
            write_json(path, case, replace=True)
            async with asyncio.timeout(300):
                while True:
                    event = await native.rpc.next_event(timeout=120)
                    if (event.get("method") == "turn/completed"
                            and event.get("params", {}).get("threadId") == binding.thread_id
                            and event.get("params", {}).get("turn", {}).get("id") == case["turn_id"]):
                        case.update(phase="native_terminal_without_interaction", terminal_event=event)
                        write_json(path, case, replace=True)
                        raise ValueError("Native turn ended without the required interaction; inspect without resubmitting")
                    if "id" in event and event.get("params", {}).get("turnId") == case["turn_id"]:
                        break
            case.update(phase="native_request_observed", request=event)
            write_json(path, case, replace=True)
            expected = "item/commandExecution/requestApproval" if mode == "default" else "item/tool/requestUserInput"
            if event["method"] != expected or event["params"].get("threadId") != binding.thread_id:
                raise ValueError("Unexpected native request; preserve without answering")
            if mode == "default":
                validate_command(event["params"]["command"], case["expected_command"])
                if Path(event["params"]["cwd"]).resolve() != binding.project:
                    raise ValueError("Native command cwd differs from dedicated fixture")
            elif {q["id"] for q in event["params"]["questions"]} != ({"choice", "note"} if case["case"] == "question-phone-first" else {"choice"}):
                raise ValueError("Native question identities differ; preserve without answering")
            async with asyncio.timeout(30):
                while True:
                    with ledger(args.state_dir, credentials) as db:
                        row = db.execute("SELECT public_id,state,deadline FROM interactions WHERE thread_id=? AND turn_id=? ORDER BY created_at DESC LIMIT 1",
                                         (binding.thread_id, case["turn_id"])).fetchone()
                    if row:
                        break
                    await asyncio.sleep(.1)
            case.update(phase="awaiting_real_owner_or_desktop", public_id=row[0], initial_state=row[1], deadline=row[2])
            write_json(path, case, replace=True)
        elif args.action.startswith("desktop-"):
            if case.get("phase") != "awaiting_real_owner_or_desktop":
                raise ValueError("Only a recorded live native interaction permits desktop input")
            if case.get("desktop_action_intent") is not None:
                raise ValueError("Desktop action already attempted; inspect native state instead of repeating input")
            with ledger(args.state_dir, credentials) as db:
                row = db.execute("SELECT state FROM interactions WHERE public_id=?", (case["public_id"],)).fetchone()
            if row != ("pending",):
                raise ValueError("Interaction is already handled; desktop input refused")
            screen = await terminal.async_get_screen_contents()
            text = "\n".join(screen.line(i).string for i in range(screen.number_of_lines)).replace("\0", " ")
            if case["case"].startswith("approval-"):
                if "Would you like to run the following command?" not in text:
                    raise ValueError("Exact native desktop approval is not visible")
            elif ("PHONE_ALPHA" if case["case"] == "question-phone-first" else "DESK_ALPHA") not in text:
                raise ValueError("Exact native desktop question is not visible")
            case["desktop_action_intent"] = args.action
            write_json(path, case, replace=True)
            await terminal.async_send_text("\r" if args.action == "desktop-accept" else "\x1b", suppress_broadcast=True)
            case["desktop_input_sent"] = True
            write_json(path, case, replace=True)
        elif args.action == "restore":
            if not case.get("turn_id") or (await native.inspect(binding.thread_id))["status"]["type"] != "idle":
                raise ValueError("Only a finished dedicated test turn permits restoring its original defaults")
            page = await native.rpc.request("thread/turns/list", {"threadId": binding.thread_id, "limit": 1,
                "itemsView": "full", "sortDirection": "desc"})
            if page["data"][0]["id"] != case["turn_id"] or page["data"][0]["status"] not in {"completed", "interrupted", "failed"}:
                raise ValueError("Original test turn is not the latest confirmed terminal turn")
            case["restoration_intent"] = True
            write_json(path, case, replace=True)
            changed_defaults = {k: case["original_settings"][k] for k in ("approvalPolicy", "approvalsReviewer", "collaborationMode")}
            await native.rpc.request("thread/settings/update", {"threadId": binding.thread_id, **changed_defaults})
            resumed = await native.rpc.request("thread/resume", {"threadId": binding.thread_id, "excludeTurns": True})
            if (native_settings(resumed) != case["original_settings"] or resumed["model"] != case["model"]
                    or resumed.get("activePermissionProfile") != case.get("original_permission_profile")):
                raise ValueError("Restoration not verified; preserve evidence")
            case["original_settings_restored"] = True
            write_json(path, case, replace=True)
        else:
            if not case.get("turn_id"):
                raise ValueError("No submitted native turn to inspect")
            page = await native.rpc.request("thread/turns/list", {"threadId": binding.thread_id, "limit": 1,
                "itemsView": "full", "sortDirection": "desc"})
            turn = page["data"][0]
            if turn["id"] != case["turn_id"]:
                raise ValueError("Latest native turn differs; inspect exact history before proceeding")
            with ledger(args.state_dir, credentials) as db:
                row = db.execute("SELECT state FROM interactions WHERE public_id=?", (case.get("public_id"),)).fetchone()
                inbound = db.execute("SELECT message_id,text,phase FROM inbox WHERE text LIKE ? AND received_at>=? ORDER BY rowid",
                                     ("%" + case.get("public_id", "absent") + "%", case["submitted_at"])).fetchall()
            users = [i for i in turn["items"] if i["type"] == "userMessage" and i.get("clientId") == case["client_id"]]
            effect = None
            target = Path(case["target"])
            if case["case"].startswith("approval-") and target.exists():
                if target.is_symlink() or not target.is_file() or target.stat().st_size > 256:
                    raise ValueError("Effect file differs from the bounded acceptance object")
                effect = target.read_text()
            case["inspection"] = {"turn_status": turn["status"], "native_client_occurrences": len(users),
                "interaction_state": row[0] if row else None, "real_inbound": inbound,
                "effect": effect}
            write_json(path, case, replace=True)
        return {"status": case["phase"], "case": case["case"], "request_id": case.get("public_id"),
                "inspection": {k: v for k, v in case.get("inspection", {}).items() if k not in {"real_inbound", "effect"}}}
    finally:
        await native.close()
        await close_connection(host)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "start", "inspect", "desktop-accept", "desktop-cancel", "restore"))
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--fixture-record", type=Path)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / "Library" / "Application Support" / "wx-clawbot")
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    args = parser.parse_args()
    if args.action == "prepare" and any(getattr(args, k) is None for k in ("case", "fixture_record", "fixture_root", "expected_config_sha256")):
        parser.error("prepare requires case, fixture-record, fixture-root and approved config digest")
    print(json.dumps(asyncio.run(prepare(args)) if args.action == "prepare" else asyncio.run(act(args)), ensure_ascii=False))
