"""Explicit two-repository native load, bounded outputs and optional real poll fault.

Inbound commands and bulk sending are synthetic. No working terminal is targeted.
The optional owner poll requires the normal foreground to be stopped beforehand.
"""

import argparse
import asyncio
import collections
import gc
import hashlib
import json
import math
import os
import resource
import shlex
import subprocess
import sys
import time
import tracemalloc
import uuid
from pathlib import Path

from wx_clawbot.admission import repository_key
from wx_clawbot.agents.queue import NativeQueue
from wx_clawbot.channels.private import private_directory, write_json
from wx_clawbot.delivery import Sender
from wx_clawbot.hosts.connection import close_connection
from wx_clawbot.interactions import APPROVAL
from w06_channel import poll_fault
from w06_recovery import command, connect, update


def is_sleep_gate(command):
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
        if len(tokens) == 3 and tokens[0] == "/bin/zsh" and tokens[1] in {"-c", "-lc"}:
            tokens = shlex.split(tokens[2])
        return tokens == ["sleep", "90"]
    except ValueError:
        return False


async def main(args):
    private_directory(args.state_dir)
    journal = args.state_dir / "load.json"
    if journal.exists():
        raise ValueError("Existing load intent; inspect it instead of resubmitting")
    nonce = uuid.uuid4().hex
    case = {"phase": "worker_intent", "nonce": nonce, "thread_id": args.threads[0],
            "state_root": str(args.state_dir / "ledger")}
    write_json(journal, case)
    native, host, state, controller, engine, _ = await connect(args, case)
    jobs = []
    gates, started, finished = {}, set(), set()
    event_counts, queue_high_water = collections.Counter(), 0
    latency, memory = [], []
    sampling = True
    counter = 10
    tracemalloc.start()
    started_at = time.monotonic()

    async def incoming(text):
        nonlocal counter
        counter += 1
        await command(controller, counter, text)

    def memory_sample(phase):
        current, peak = tracemalloc.get_traced_memory()
        memory.append({"seconds": round(time.monotonic() - started_at, 3), "phase": phase,
                       "python_current_bytes": current, "python_peak_bytes": peak,
                       "process_rss_kib": int(subprocess.check_output(["/bin/ps", "-p", str(os.getpid()), "-o", "rss="], text=True, timeout=1).strip())})

    async def sample_controls():
        while sampling:
            before = time.perf_counter()
            await incoming("/status")
            if len(latency) < 3000:
                latency.append((time.perf_counter() - before) * 1000)
            await asyncio.sleep(.1)

    try:
        sessions = [next(s for s in controller.catalog.sessions.values() if s.binding.thread_id == thread)
                    for thread in args.threads]
        if len({s.target.project_alias for s in sessions}) != 2:
            raise ValueError("Two distinct registered temporary projects required")
        keys = [await repository_key(s.target.cwd, controller.routes.projects[s.target.project_alias].root) for s in sessions]
        if len(set(keys)) != 2:
            raise ValueError("Two independent repositories required; shared worktrees must remain mutually exclusive")
        for session in sessions:
            thread = await native.inspect(session.binding.thread_id)
            if thread.get("status", {}).get("type") == "active" or await NativeQueue(native, session.binding.thread_id, session.target.cwd).list():
                raise ValueError("Dedicated thread must be idle with an empty native queue")
        controller.routes.snapshot(tuple(s.target for s in sessions))
        await incoming("/focus 1")
        for session in sessions:
            await controller.subscriptions.acquire(session.target, "load-test")
        baseline = hashlib.sha256((args.codex_home / "config.toml").read_bytes()).hexdigest()
        if baseline != args.expected_config_sha256:
            raise ValueError("Global configuration differs from the explicitly approved baseline")
        update(journal, phase="native_gate_intents", config_sha256=baseline)

        put = native.rpc.events.put_nowait
        def counted_put(event):
            nonlocal queue_high_water
            put(event)
            queue_high_water = max(queue_high_water, native.rpc.events.qsize())
        native.rpc.events.put_nowait = counted_put
        event_handler = engine.event

        async def event(event):
            params = event.get("params", {})
            thread_id = params.get("threadId")
            if thread_id in args.threads:
                method = event["method"]
                event_counts[method] += 1
                turn_id = params.get("turnId") or params.get("turn", {}).get("id")
                if turn_id == gates.get(thread_id):
                    item = params.get("item", {})
                    if method == "item/started" and item.get("type") == "commandExecution":
                        if not is_sleep_gate(item.get("command")):
                            raise AssertionError("Gate attempted a command outside the exact sleep scope")
                        started.add(thread_id)
                    if method == "turn/completed":
                        if params["turn"].get("status") != "completed":
                            raise AssertionError("Native timing gate did not complete")
                        finished.add(thread_id)
                    if method == APPROVAL:
                        if not is_sleep_gate(params["command"]):
                            raise AssertionError("Only the explicitly authorized sleep may be approved")
                        update(journal, gate_approval_intent={"thread_id": thread_id, "request_id": event["id"]})
                        await native.rpc.respond(event["id"], {"decision": "accept"})
            await event_handler(event)

        engine.event = event
        jobs.extend([asyncio.create_task(engine.run()), asyncio.create_task(engine.maintain())])
        class SimulatedSend:
            async def send_text(self, *_, **__):
                return {"ret": 0, "message_id": 7}
        fake_api = SimulatedSend()
        jobs.append(asyncio.create_task(Sender(state, fake_api).run()))
        for index, session in enumerate(sessions):
            client_id = "wx-load-gate-" + nonce + "-" + str(index)
            update(journal, next_gate_intent={"thread_id": session.binding.thread_id, "client_id": client_id})
            result = await native.rpc.request("turn/start", {"threadId": session.binding.thread_id,
                "clientUserMessageId": client_id, "input": [{"type": "text", "text":
                    "专用只读计时任务：只调用一次 exec_command 执行 sleep 90，不读写文件，不运行测试或其他命令；等命令结束后仅回复 WX-W06-GATE-DONE。"}]})
            gates[session.binding.thread_id] = result["turn"]["id"]
            update(journal, gate_turns=gates)
        async with asyncio.timeout(60):
            while len(started) != 2:
                for job in jobs:
                    if job.done():
                        job.result()
                await asyncio.sleep(.1)
        memory_sample("two_native_gates_running")
        markers = []
        for index in range(2):
            for number in range(10):
                marker = "WX-W06-LOAD-" + nonce[:8] + f"-{index}-{number}"
                markers.append(marker)
                prompt = "不要调用工具，不要修改文件，只回复 " + marker + "。"
                if index == 1 and number == 9:
                    prompt = ("不要调用工具或修改文件。输出 240 行，每行格式为 WX-W06-LONG-" + nonce[:8]
                              + "-NNNN-abcdefghijklmnopqrstuvwx，NNNN 从 0001 递增至 0240，不省略；最后单独回复 " + marker + "。")
                await incoming(f"/send {index + 1} {prompt}")
        bridge_tasks = [t for t in await state.tasks(active_only=True) if t["target"].get("source") != "external"]
        if len(bridge_tasks) != 20 or any(t["state"] != "queued" for t in bridge_tasks):
            raise AssertionError("Exactly twenty tasks must be in the real native queues")
        snapshots = [await NativeQueue(native, s.binding.thread_id, s.target.cwd).list() for s in sessions]
        assert [len(rows) for rows in snapshots] == [10, 10]
        await incoming("/send 1 不要调用工具，只回复 WX-W06-ELEVENTH-MUST-NOT-RUN。")
        assert len([t for t in await state.tasks(active_only=True) if t["target"].get("source") != "external"]) == 20
        cancelled = next(t for t in bridge_tasks if t["input"].endswith(markers[9] + "。"))
        before_cancel = time.perf_counter()
        await incoming("/stop " + cancelled["id"])
        cancel_ms = (time.perf_counter() - before_cancel) * 1000
        assert (await state.tasks(task_id=cancelled["id"]))["state"] == "cancelled"
        await incoming("/send 1 不要调用工具，不要修改文件，只回复 WX-W06-REPLACEMENT-" + nonce[:8] + "。")
        bridge_tasks = [t for t in await state.tasks(active_only=True) if t["target"].get("source") != "external"]
        assert len(bridge_tasks) == 20
        update(journal, phase="native_queues_full", queue_lengths=[10, 10], bridge_task_ids=[t["id"] for t in bridge_tasks])
        memory_sample("two_queues_full")
        jobs.append(asyncio.create_task(sample_controls()))
        channel = None
        last_memory = time.monotonic()
        async with asyncio.timeout(300):
            while True:
                for job in jobs:
                    if job.done():
                        job.result()
                if len(finished) == 2 and channel is None and args.owner_state_dir:
                    channel = asyncio.create_task(poll_fault(args.owner_state_dir))
                    jobs.append(channel)
                tasks = [await state.tasks(task_id=t["id"]) for t in bridge_tasks]
                if all(t["state"] in {"completed", "failed", "interrupted", "cancelled"} for t in tasks):
                    assert all(t["state"] == "completed" for t in tasks)
                    if channel is None or channel.done():
                        break
                if time.monotonic() - last_memory >= 5:
                    memory_sample("native_events_and_controls")
                    last_memory = time.monotonic()
                await asyncio.sleep(.25)
        sampling = False
        assert len(latency) >= 100 and event_counts and queue_high_water <= 256
        long_task = next(t for t in tasks if "输出 240 行" in t["input"])
        long_turn = await engine.read_turn(long_task["thread_id"], long_task["turn_id"])
        text = "\n".join(i.get("text", "") for i in long_turn["items"] if i.get("type") == "agentMessage")
        assert len(text) > 8000 and markers[-1] in text
        long_segments = await state._call(lambda: state.db.execute("SELECT count(*) FROM outbox WHERE task_id=? AND kind='final'", (long_task["id"],)).fetchone()[0])
        assert long_segments >= 2
        for task in tasks:
            turn = await engine.read_turn(task["thread_id"], task["turn_id"])
            users = [i for i in turn["items"] if i.get("type") == "userMessage"]
            assert len(users) == 1 and users[0].get("clientId") == task["client_id"]
        for thread_id in args.threads:
            history = [turn async for turn in engine.turns(thread_id)]
            owned = {t["client_id"] for t in bridge_tasks} | {cancelled["client_id"]}
            actual = [user["clientId"] for turn in reversed(history) for user in turn["items"]
                      if user.get("type") == "userMessage" and user.get("clientId") in owned]
            expected = [t["client_id"] for t in bridge_tasks if t["thread_id"] == thread_id]
            assert actual == expected and cancelled["client_id"] not in actual
        await engine.prune_memory()
        gc.collect()
        memory_sample("completed_and_pruned")
        assert hashlib.sha256((args.codex_home / "config.toml").read_bytes()).hexdigest() == baseline
        p95 = sorted(latency)[math.ceil(len(latency) * .95) - 1]
        report = {"native_tasks_completed": 20, "queue_limits_verified": [10, 10], "eleventh_not_submitted": True,
                  "control_samples": len(latency), "control_p95_ms": round(p95, 3),
                  "control_max_ms": round(max(latency), 3), "control_scope": "normalized receive through inbox and control Outbox commit; excludes model, public network and send",
                  "status_samples_only": True, "queued_stop_native_confirmed": True,
                  "queued_stop_local_ms": round(cancel_ms, 3),
                  "native_fifo_and_each_client_once": True,
                  "native_event_counts": dict(event_counts), "event_queue_high_water": queue_high_water,
                  "event_queue_limit": 256, "python_memory_samples": memory,
                  "process_peak_rss_native_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "process_peak_rss_unit": "bytes" if sys.platform == "darwin" else "KiB",
                  "native_long_output_characters": len(text), "long_result_segments": long_segments,
                  "global_config_unchanged": True, "bulk_wechat_sending_simulated": True,
                  "real_poll": channel.result() if channel else None, "passed": p95 < 1000}
        write_json(args.state_dir / "report.json", report)
        update(journal, phase="verified" if report["passed"] else "latency_target_failed", report=report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        assert report["passed"]
    except BaseException as error:
        update(journal, phase="failed_inspect_native_before_any_retry", error_type=type(error).__name__,
               gate_turns=gates, event_counts=dict(event_counts))
        raise
    finally:
        sampling = False
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        tracemalloc.stop()
        await state.close()
        await close_connection(host)
        await native.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-dedicated", required=True, action="store_true")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--codex-executable", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--threads", nargs=2, required=True)
    parser.add_argument("--owner-state-dir", type=Path)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.set_defaults(worker=None)
    asyncio.run(main(parser.parse_args()))
