"""Explicit native-process crash tests; synthetic inbound/delivery, no WeChat HTTP.

Requires two exact, dedicated native threads under a temporary fixture root.
Every case registers an intent before spawning a worker. Existing journals cannot
be rerun. A failed or timed-out case must be inspected, never submitted again.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import load_projects
from wx_clawbot.controller import Controller
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.connection import close_connection
from wx_clawbot.hosts.discovery import ItermDirectory
from wx_clawbot.hosts.visible import ItermWindowStarter, LaunchRegistry, VisibleStarter
from wx_clawbot.runtime_state import RuntimeState


PHASES = ("before_rpc", "after_rpc_frame", "after_native_ack", "during_final_transaction", "after_outbox_commit")


def update(path, **values):
    record = read_json(path)
    record.update(values)
    write_json(path, record, replace=True)


async def connect(args, case):
    import iterm2

    projects = load_projects(args.config)
    if len(projects) != 2 or any(not p.root.is_relative_to(args.fixture_root.resolve(strict=True)) for p in projects):
        raise ValueError("Exactly two explicitly temporary projects required")
    native = await CodexConnection.connect(args.socket)
    host = state = None
    try:
        host = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        catalog = SessionCatalog(projects, ItermDirectory(host), native)
        sessions = await catalog.discover()
        selected = [s for s in sessions if s.binding.thread_id == case["thread_id"]]
        if len(selected) != 1:
            raise ValueError("Exact dedicated thread is not uniquely visible and verified")
        thread = await native.inspect(case["thread_id"])
        if not args.worker and case["phase"] == "worker_intent" and thread.get("status", {}).get("type") == "active":
            raise ValueError("Dedicated thread is already active; do not inject a test")
        root = Path(case["state_root"])
        credentials = Credentials("fixture-w06-" + case["nonce"], "fixture-owner",
                                  "https://ilinkai.weixin.qq.com/", "fixture-token")
        state = await RuntimeState.open(root / "runtime.sqlite3", credentials)
        starter = VisibleStarter(LaunchRegistry(root / "launches"), ItermWindowStarter(host))
        controller = Controller(projects, catalog, state, starter, args.codex_executable, args.codex_home)
        engine = Execution(controller)
        return native, host, state, controller, engine, selected[0]
    except BaseException:
        if state:
            await state.close()
        if host:
            await close_connection(host)
        await native.close()
        raise


async def command(controller, identity, text):
    credentials = controller.state.credentials
    raw = {"message_id": identity, "from_user_id": credentials.owner_id, "to_user_id": credentials.bot_id,
           "message_type": 1, "message_state": 2, "create_time_ms": identity, "seq": identity,
           "context_token": "fixture-context", "item_list": [{"type": 1, "text_item": {"text": text}}]}
    message = (await controller.state.accept_batch({"ret": 0, "msgs": [raw]}, phase="runtime"))["accepted"][0]
    await controller.prepare(message)


async def worker(args):
    journal = args.state_dir / (args.worker + ".json")
    case = read_json(journal)
    if case["phase"] != "worker_intent":
        raise ValueError("Worker intent already consumed; never repeat")
    update(journal, phase="worker_started", worker_pid=os.getpid())
    native, host, state, controller, engine, session = await connect(args, case)
    monitor = None
    try:
        controller.routes.snapshot((session.target,))
        await command(controller, 1, "/focus 1")
        queue = NativeQueue(native, session.binding.thread_id, session.target.cwd)
        original_add = queue.add
        if args.worker == "after_rpc_frame":
            send = native.rpc._send
            async def crash_after_frame(message):
                await send(message)
                if message.get("method") == "thread/queue/add":
                    update(journal, phase="fault_after_rpc_frame", native_add_calls=1)
                    os._exit(86)
            native.rpc._send = crash_after_frame

        async def crash_add(text, client_id):
            update(journal, phase="native_add_intent", client_id=client_id)
            if args.worker == "before_rpc":
                update(journal, phase="fault_before_rpc", native_add_calls=0)
                os._exit(86)
            receipt = await original_add(text, client_id)
            update(journal, phase="native_add_acknowledged", native_add_calls=1, queue_id=receipt["id"])
            if args.worker == "after_native_ack":
                update(journal, phase="fault_after_native_ack")
                os._exit(86)
            return receipt

        queue.add = crash_add
        engine.queue = lambda *_: queue
        if args.worker in {"during_final_transaction", "after_outbox_commit"}:
            original_finish = state.task_finish

            if args.worker == "during_final_transaction":
                def register_transaction_fault():
                    def crash():
                        update(journal, phase="fault_during_final_transaction")
                        os._exit(86)
                    state.db.create_function("w06_crash", 0, crash)
                    state.db.execute("""CREATE TEMP TRIGGER w06_final_fault BEFORE INSERT ON outbox
                        WHEN NEW.kind='final' BEGIN SELECT w06_crash(); END""")
                await state._call(register_transaction_fault)

            async def crash_finish(*values, **options):
                result = await original_finish(*values, **options)
                if args.worker == "after_outbox_commit" and result and values[1] == "completed":
                    update(journal, phase="fault_after_outbox_commit")
                    os._exit(86)
                return result

            state.task_finish = crash_finish
            monitor = asyncio.create_task(engine.run())
        await command(controller, 2, "不要调用工具，不要修改文件，只回复 " + case["marker"] + "。")
        if monitor:
            await asyncio.wait_for(monitor, 120)
        raise AssertionError("Expected worker crash point was not reached")
    finally:
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        await state.close()
        await close_connection(host)
        await native.close()


async def recover(args, journal):
    case = read_json(journal)
    native, host, state, controller, engine, session = await connect(args, case)
    monitor = None
    try:
        await controller.restore()
        mutations = 0
        original_queue = engine.queue

        def guarded_queue(*values):
            queue = original_queue(*values)
            async def forbidden_add(*_):
                nonlocal mutations
                mutations += 1
                raise AssertionError("Recovery attempted native resubmission")
            queue.add = forbidden_add
            return queue

        engine.queue = guarded_queue
        await engine.reconcile()
        tasks = await state.tasks()
        assert len(tasks) == 1
        task = tasks[0]
        if case["fault"] != "before_rpc":
            monitor = asyncio.create_task(engine.run())
            async with asyncio.timeout(120):
                while (await state.tasks(task_id=task["id"]))["state"] != "completed":
                    if monitor.done():
                        monitor.result()
                    await asyncio.sleep(.2)
                    await engine.reconcile()
        else:
            assert task["state"] == "unknown"
        matches = []
        async for turn in engine.turns(task["thread_id"]):
            users = [i for i in turn["items"] if i.get("type") == "userMessage" and i.get("clientId") == task["client_id"]]
            if users:
                matches.append(turn)
        expected = 0 if case["fault"] == "before_rpc" else 1
        assert len(matches) == expected and mutations == 0
        if expected:
            assert matches[0]["status"] == "completed"
            assert case["marker"] in "\n".join(i.get("text", "") for i in matches[0]["items"] if i.get("type") == "agentMessage")
            api = SimpleNamespace(send_text=AsyncMock(return_value={"ret": 0, "message_id": 7}))
            sender = Sender(state, api)
            while await sender.once():
                pass
            final_sends = [c for c in api.send_text.await_args_list if case["marker"] in c.kwargs["text"]]
            assert len(final_sends) == 1
        await controller.catalog.require(session.target)
        current_hash = hashlib.sha256((args.codex_home / "config.toml").read_bytes()).hexdigest()
        assert current_hash == case["config_sha256"]
        report = {"fault": case["fault"], "native_executions": len(matches), "recovery_add_calls": mutations,
                  "final_state": (await state.tasks(task_id=task["id"]))["state"],
                  "original_endpoint_reverified": True, "global_config_unchanged": True,
                  "real_native_process_crash": True, "wechat_transport_used": False}
        update(journal, phase="verified", report=report)
        return report
    finally:
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        await state.close()
        await close_connection(host)
        await native.close()


async def main(args):
    if args.worker:
        await worker(args)
        return
    if args.recover:
        journal = args.state_dir / (args.recover + ".json")
        if not read_json(journal)["phase"].startswith("fault_"):
            raise ValueError("Only an existing registered crash can be read-only recovered")
        print(json.dumps(await recover(args, journal), ensure_ascii=False), flush=True)
        return
    private_directory(args.state_dir)
    reports = []
    for index, fault in enumerate(args.cases):
        journal = args.state_dir / (fault + ".json")
        if journal.exists():
            raise ValueError("Existing case journal: inspect it, do not rerun")
        nonce = uuid.uuid4().hex
        case = {"phase": "worker_intent", "fault": fault, "nonce": nonce,
                "marker": "WX-W06-" + nonce, "thread_id": args.threads[index % 2],
                "state_root": str(args.state_dir / fault),
                "config_sha256": hashlib.sha256((args.codex_home / "config.toml").read_bytes()).hexdigest()}
        write_json(journal, case)
        # Verify idle original identity before starting a child with mutation rights.
        native, host, state, _, _, _ = await connect(args, case)
        await state.close()
        await close_connection(host)
        await native.close()
        argv = [sys.executable, str(Path(__file__).resolve()), "--confirm-dedicated", "--config", str(args.config),
                "--fixture-root", str(args.fixture_root), "--socket", str(args.socket),
                "--codex-executable", str(args.codex_executable), "--codex-home", str(args.codex_home),
                "--state-dir", str(args.state_dir), "--threads", *args.threads, "--worker", fault]
        process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, error = await asyncio.wait_for(process.communicate(), 180)
        except TimeoutError:
            update(journal, phase="observation_timeout_do_not_replay", worker_pid=process.pid)
            process.send_signal(2)
            await process.wait()
            raise
        if process.returncode != 86:
            update(journal, worker_exit=process.returncode, worker_error=error.decode()[-4000:])
            raise AssertionError("Worker failed before registered crash; inspect private journal")
        reports.append(await recover(args, journal))
    report_name = "report-" + "-".join(args.cases) + ".json"
    write_json(args.state_dir / report_name, {"cases": reports, "wechat_transport_used": False})
    print(json.dumps({"cases": reports, "passed": True}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-dedicated", action="store_true", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--codex-executable", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--threads", nargs=2, required=True)
    parser.add_argument("--worker", choices=PHASES)
    parser.add_argument("--recover", choices=PHASES, help="Only reconcile an already registered crash; never start a worker")
    parser.add_argument("--cases", nargs="+", choices=PHASES, default=PHASES)
    args = parser.parse_args()
    asyncio.run(main(args))
