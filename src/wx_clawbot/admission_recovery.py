"""Bounded read-only native evidence; never restores or executes historical work."""

import asyncio
import hashlib
import json
import time

from .agents.rpc import RpcError


class EvidenceUnavailable(ValueError):
    pass


async def terminal_evidence(native, tasks, generation):
    """Prove original turns ended and no queued work remains on their thread."""
    if not isinstance(tasks,list) or not 1<=len(tasks)<=128 or any(
        not isinstance(t,dict) or t.get('state')!='unknown' or not isinstance(t.get('target'),dict)
        or any(not isinstance(t.get(k),str) or not t[k] or len(t[k])>256 for k in ('thread_id','turn_id','client_id'))
        or not isinstance(t['target'].get('cwd'),str) or not t['target']['cwd'].startswith('/') for t in tasks):
        raise EvidenceUnavailable("missing_terminal_identity")
    thread_id = tasks[0]["thread_id"]
    cwd = tasks[0]["target"]["cwd"]
    if any(t["thread_id"] != thread_id or t["target"]["cwd"] != cwd for t in tasks):
        raise EvidenceUnavailable("conflicting_thread_identity")

    async def inspect():
        value = await native.inspect(thread_id)
        if not isinstance(value,dict) or value.get("id") != thread_id or value.get("cwd") != cwd:
            raise EvidenceUnavailable("native_identity_mismatch")
        if not isinstance(value.get('status'),dict) or value['status'].get("type") not in {"idle", "notLoaded"}:
            raise EvidenceUnavailable("native_still_active")

    await inspect()
    # queue/list is a read operation; NativeQueue.list additionally requires a
    # live TUI for dispatch, which cannot grant or deny historical read authority.
    queue = await native.rpc.request("thread/queue/list", {"threadId": thread_id, "limit": 1})
    if not isinstance(queue, dict) or queue.get("data") != [] or queue.get("nextCursor") is not None:
        raise EvidenceUnavailable("native_queue_not_empty_or_incomplete")
    found, cursor, cursors = {}, None, set()
    clients = {t["target"].get("native_client_id") if t["target"].get("source") == "external" else t["client_id"] for t in tasks}
    if None in clients or "" in clients:
        raise EvidenceUnavailable("missing_client_identity")
    seen_clients = set()
    for _ in range(200):
        params = {"threadId": thread_id, "limit": 1, "itemsView": "full", "sortDirection": "desc"}
        if cursor:
            params["cursor"] = cursor
        page = await native.rpc.request("thread/turns/list", params)
        rows = page.get("data") if isinstance(page, dict) else None
        if not isinstance(rows, list) or len(rows) > 1:
            raise EvidenceUnavailable("malformed_history")
        for turn in rows:
            if (not isinstance(turn, dict) or not isinstance(turn.get("items"), list)
                    or not isinstance(turn.get("id"), str) or not turn['id']
                    or any(not isinstance(i,dict) for i in turn['items'])):
                raise EvidenceUnavailable("malformed_turn")
            if turn.get('status') == 'inProgress':
                raise EvidenceUnavailable('native_history_still_active')
            if any(i.get('type') in {'commandExecution','mcpToolCall','dynamicToolCall'} and
                   i.get('status') in {'inProgress','running'} for i in turn['items'] if isinstance(i,dict)):
                raise EvidenceUnavailable('known_tool_still_running')
            users = [i for i in turn["items"] if isinstance(i, dict) and i.get("type") == "userMessage"]
            if any(i.get('clientId') is not None and not isinstance(i['clientId'],str) for i in users):
                raise EvidenceUnavailable('malformed_client_identity')
            matches = [i.get("clientId") for i in users if i.get("clientId") in clients]
            if len(set(matches)) != len(matches) or any(c in seen_clients for c in matches):
                raise EvidenceUnavailable("duplicate_client_history")
            seen_clients.update(matches)
            for task in tasks:
                if task["turn_id"] != turn["id"]:
                    continue
                client = task["target"].get("native_client_id") if task["target"].get("source") == "external" else task["client_id"]
                if client not in matches or turn["id"] in found and found[turn["id"]] != turn.get("status"):
                    raise EvidenceUnavailable("ambiguous_original_turn")
                if turn.get("status") not in {"completed", "failed", "interrupted"}:
                    raise EvidenceUnavailable("turn_not_terminal")
                found[turn["id"]] = turn["status"]
        if set(found) == {t['turn_id'] for t in tasks}:
            break  # Ownership proof does not require unrelated older results.
        cursor = page.get("nextCursor")
        if cursor is None:
            break
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise EvidenceUnavailable("invalid_history_cursor")
        cursors.add(cursor)
    else:
        raise EvidenceUnavailable("history_bound_exceeded")
    if set(found) != {t["turn_id"] for t in tasks} or seen_clients != clients:
        raise EvidenceUnavailable("original_turn_not_found")
    await inspect()
    # A queue insertion between history and the second inspection must still
    # prevent release, even when the native status remains idle.
    after = await native.rpc.request("thread/queue/list", {"threadId": thread_id, "limit": 1})
    if not isinstance(after, dict) or after.get("data") != [] or after.get("nextCursor") is not None:
        raise EvidenceUnavailable("native_queue_changed")
    return {"kind": "native_terminal", "thread_id": thread_id, "turns": found,
            "queue_empty": True, "generation": generation,
            "clients_sha256": hashlib.sha256(json.dumps(sorted(clients)).encode()).hexdigest()}


class AdmissionRecovery:
    """At most two checks at a time; slow native reads never own admission_gate."""

    def __init__(self, engine, *, clock=time.monotonic):
        self.engine = engine
        self.schedule = {}
        self.lock = asyncio.Lock()
        self.wake = asyncio.Event()
        self.clock = clock
        self.query_timeout = 5

    def trigger(self, thread_id):
        self.schedule.pop(thread_id, None)
        self.wake.set()

    async def check(self, tasks):
        engine = self.engine
        thread_id = tasks[0]["thread_id"]
        attempt = self.schedule.get(thread_id, (0, 0))[1]
        reason = "native_unavailable"
        try:
            if not engine.controller.native_ready:
                raise EvidenceUnavailable('native_generation_changed')
            if thread_id in engine.inflight:
                raise EvidenceUnavailable("submission_inflight")
            async with asyncio.timeout(self.query_timeout):
                await engine.reconcile_results(thread_id=thread_id)
                tasks=[t for t in await engine.state.occupancy_snapshot(holding_only=True) if t['thread_id']==thread_id]
                if not tasks:
                    self.schedule.pop(thread_id,None)
                    return
                evidence = await terminal_evidence(engine.native, tasks, engine.generation)
            async with engine.admission_gate:
                if not engine.controller.native_ready or thread_id in engine.inflight:
                    raise EvidenceUnavailable("native_generation_changed")
                current = [t for t in await engine.state.occupancy_snapshot(holding_only=True) if t["thread_id"] == thread_id]
                if [(t["id"], t["occupancy"]["revision"]) for t in current] != [(t["id"], t["occupancy"]["revision"]) for t in tasks]:
                    raise EvidenceUnavailable("occupancy_revision_changed")
                await engine.state.release_occupancies(tasks, evidence)
            self.schedule.pop(thread_id, None)
            return
        except EvidenceUnavailable as exc:
            reason = str(exc)
        except (TimeoutError, ConnectionError, RpcError, ValueError):
            reason = "native_query_unavailable"
        # Storage failure must escape, rather than being disguised as a transient
        # native error. In particular a failed release cannot unlock admission.
        await engine.state.record_occupancy_check(tasks, reason)
        delay = (1, 2, 5, 15, 30)[min(attempt, 4)]
        self.schedule[thread_id] = (self.clock() + delay, attempt + 1)

    async def reconcile(self, *, force=False):
        async with self.lock:
            groups = {}
            for task in await self.engine.state.occupancy_snapshot(holding_only=True):
                groups.setdefault(task["thread_id"], []).append(task)
            self.schedule = {k: v for k, v in self.schedule.items() if k in groups}
            eligible = [tasks for key, tasks in groups.items() if all(t["state"] == "unknown" for t in tasks)
                        and (force or self.schedule.get(key, (0, 0))[0] <= self.clock())]
            await asyncio.gather(*(self.check(tasks) for tasks in eligible[:2]))

    async def run(self):
        while True:
            self.wake.clear()
            await self.reconcile()
            try:
                await asyncio.wait_for(self.wake.wait(), 1)
            except TimeoutError:
                pass
