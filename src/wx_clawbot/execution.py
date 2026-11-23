"""One native event stream, durable submission identities and explicit terminal receipts."""

import asyncio
import collections
import hashlib
import json
import time
import uuid
from pathlib import Path

from .agents.queue import NativeQueue, QueueFull
from .agents.registry import queue_label
from .admission import conflict, repository_key
from .commands import CommandError
from .catalog import DiscoveryUnavailable
from .controller import target_record
from .interactions import ACP_APPROVAL, APPROVAL, QUESTION, InteractionBroker
from .routing import Target
from .sessions import SessionUnbound
from .output import native_output, render_segments, render_in_worker, inline_literal, target_description, task_state
from .channels.media import ImageError
from .images import ImagePreparer
from .hosts.lifecycle import HostUnavailable
from .results import ResultWork
from .admission_recovery import AdmissionRecovery
from .async_questions import AsyncQuestions
from .native_controls import NativeControls
from .execution_control import handle_control


TERMINAL = {"completed", "failed", "interrupted", "cancelled"}


def restore_target(record):
    return Target(record["session_id"], record["project_alias"], Path(record["cwd"]),
                  record["origin"], record.get("agent", "codex"))


class Execution:
    def __init__(self, controller):
        self.controller = controller
        controller.engine = self
        self.state, self.catalog = controller.state, controller.catalog
        self.native = self.catalog.agent
        self.queues, self.admission = {}, {}
        self.turn_tasks = {}
        self.brokers = {}
        self.observed_turns = set()
        self.generation = uuid.uuid4().hex
        self.interaction_targets = {}
        self.interaction_sizes = {}
        self.admission_gate = asyncio.Lock()
        self.images = ImagePreparer(self.state)
        self.image_jobs = {}
        self.image_errors = []
        self.results = None
        self.inflight = collections.Counter()
        self.recovery = AdmissionRecovery(self)
        self.history_cursor = ''
        self.async_questions = AsyncQuestions(self)
        self.native_controls = NativeControls(self)

    def start_image_preparation(self, task):
        if task["id"] in self.image_jobs:
            return
        job = asyncio.create_task(self.prepare_images(task))
        self.image_jobs[task["id"]] = job
        def done(completed):
            self.image_jobs.pop(task["id"], None)
            if not completed.cancelled() and completed.exception() is not None:
                self.image_errors.append(completed.exception())
        job.add_done_callback(done)

    async def prepare_images(self, task):
        try:
            await self.images.prepare(task)
        except ImageError as exc:
            try:
                await self.state.task_finish(task["id"], "failed", f"图片任务未提交：{task['id']}。{exc}。")
            except Exception:
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await self.state.task_finish(task["id"], "failed", f"图片准备未确认（{type(exc).__name__}）：{task['id']}；没有提交原生任务。")
            except Exception:
                pass

    @staticmethod
    def earlier_waiting(task, active):
        for other in active:
            if other["id"] == task["id"]:
                break
            if other["state"] == "received" and other["target"]["session_id"] == task["target"]["session_id"]:
                return True
        return False

    async def close(self):
        for job in tuple(self.image_jobs.values()):
            job.cancel()
        await asyncio.gather(*tuple(self.image_jobs.values()), return_exceptions=True)
        await self.images.close()

    async def persist_interaction(self, record):
        target, expires_at = self.interaction_targets[record.public_id]
        return await self.state.record_interaction(record, generation=self.generation,
                                                   target=target, expires_at=expires_at)

    async def release_interaction(self, thread_id, record):
        await self.state.supersede_reply(record.public_id + "-prompt")
        for session in tuple(self.controller.subscriptions.bound.values()):
            if session.binding.thread_id == thread_id:
                await self.controller.subscriptions.release(session.target, "interaction-" + record.public_id)

    async def expire_interactions(self):
        for thread_id, broker in tuple(self.brokers.items()):
            for record in tuple(broker.records.values()):
                if record.state not in {"resolved", "stale"} and broker.clock() >= record.deadline:
                    record.state = "stale"
                    await broker.sync(record)
                    await self.release_interaction(thread_id, record)
                    await self.state.queue_reply(record.public_id + "-expired",
                        f"交互已过期：{record.public_id}；未发送自动答复，请在原终端核对。", priority=0)

    def backend_for(self, agent_kind="codex"):
        if hasattr(self.catalog, "backend_for"):
            return self.catalog.backend_for(agent_kind)
        return self.native if agent_kind == "codex" else None

    def queue(self, thread_id, cwd):
        key = (thread_id, cwd)
        if key not in self.queues:
            self.queues[key] = NativeQueue(self.native, thread_id, cwd)
        return self.queues[key]

    def verified_native(self, expected=None, *, agent="codex"):
        if agent == "antigravity":
            backend = self.backend_for("antigravity")
            generation = (getattr(self.controller, "agy_generation", 0),
                          backend.runtime_identity if backend is not None else None)
            if not getattr(self.controller, "agy_ready", False) or generation[1] is None or expected is not None and generation != expected:
                raise CommandError("Antigravity 连接已变化，本条操作未确认完成；请核对状态，不要重发未知任务。")
            return generation
        generation = (self.controller.native_generation, self.native.runtime_identity)
        if not self.controller.native_ready or generation[1] is None or expected is not None and generation != expected:
            raise CommandError("原生连接已变化，本条操作未确认完成；请核对状态，不要重发未知任务。")
        return generation

    async def submit(self, message_id, dispatch):
        # This lock is obtained before the first external await, preserving receive
        # order even if later endpoint verification takes different amounts of time.
        lock = self.admission.setdefault(dispatch.target.session_id, asyncio.Lock())
        async with lock:
            async with self.admission_gate:
                await self._submit_locked(message_id, dispatch)

    async def _submit_locked(self, message_id, dispatch):
        agent_kind = dispatch.target.agent
        backend = self.backend_for(agent_kind)
        self.verified_native(agent=agent_kind)
        if backend is None or not (backend.capabilities.queue or backend.capabilities.bridge_queue):
            raise CommandError("当前 Agent 未提供已验证的队列能力，任务未接收。")
        if dispatch.has_images and not backend.capabilities.image_input:
            raise CommandError("当前原生运行时的图片输入尚未核验，任务未提交；不会更换模型或运行时。")
        if not (await self.state.admission_budget())["allowed"]:
            raise CommandError("待核对回执已达容量上限，新任务未接收；请先恢复通道并处理未知投递。")
        try:
            await self.catalog.discover()  # Include newly opened desktop sessions before repository admission.
        except DiscoveryUnavailable as exc:
            raise CommandError(str(exc) + '任务未提交。') from None
        session = await self.catalog.require(dispatch.target)
        record = target_record(session)
        record["repository"] = await repository_key(dispatch.target.cwd,
                                  self.controller.routes.projects[dispatch.target.project_alias].root)
        active = await self.state.tasks(active_only=True)
        if sum(t["target"]["session_id"] == dispatch.target.session_id and t["state"] not in {"running", "waiting_interaction", "stopping"}
               for t in active) >= 10:
            raise CommandError("该会话的桥接排队或准入等待已达十条，新任务未接收。")
        task = await self.state.task_intent(message_id, record, dispatch.text)
        if task is None:
            return  # A source native message is never submitted a second time.
        task = await self.state.tasks(task_id=task["id"])
        await self.state.task_update(task["id"], "received")
        if task.get("input_items"):
            self.start_image_preparation(task)
            await self.state.queue_reply(task["id"] + "-preparing",
                f"图片任务已接收，正在准备：{task['id']}；尚未进入{queue_label(agent_kind)}。",
                priority=2, task_id=task["id"], kind="progress")
            return
        try:
            reason = ("同会话的前序任务尚未准备就绪" if self.earlier_waiting(task, active) else
                      await conflict(task, active, self.catalog, self.controller.routes.projects))
        except BaseException:
            await asyncio.shield(self.state.task_finish(task["id"], "failed",
                f"仓库或桌面活动核验失败，任务未提交：{task['id']}。"))
            raise
        if reason:
            await self.state.admission_wait(task, str(reason), getattr(reason, "blockers", ()))
            self.recovery.wake.set()
            return
        await self.dispatch(task)

    async def dispatch(self, task):
        target = restore_target(task["target"])
        agent_kind = target.agent
        backend = self.backend_for(agent_kind)
        record, text = task["target"], task["input"]
        task_id, thread_id = task["id"], record["thread_id"]
        attempted = False
        try:
            native_generation = self.verified_native(agent=agent_kind)
            await self.controller.subscriptions.acquire(target, "task-" + task_id)
            await self.catalog.require(target)
            content = await self.images.inputs(task) if task.get("input_items") else None
            if not await self.state.task_update(task_id, "dispatching"):
                await self.controller.subscriptions.release(target, "task-" + task_id)
                return
            self.verified_native(native_generation, agent=agent_kind)
            attempted = True
            self.inflight[thread_id] += 1
            try:
                if agent_kind == "antigravity":
                    receipt = await backend.submit_idle(thread_id, target.cwd, text, task["client_id"],
                                                        input_items=content)
                    # Register turn_id synchronously before any await so immediate
                    # permission requests or fast completions always resolve task_id.
                    self.turn_tasks[(thread_id, receipt.turn_id)] = task_id
                else:
                    queue = self.queue(thread_id, target.cwd)
                    receipt = (await queue.add(text, task["client_id"], input_items=content) if content is not None
                               else await queue.add(text, task["client_id"]))
            finally:
                self.inflight[thread_id] -= 1
                if self.inflight[thread_id] <= 0:
                    self.inflight.pop(thread_id, None)
            current = await self.state.tasks(task_id=task_id)
            if agent_kind == "antigravity":
                if current["state"] not in TERMINAL:
                    await self.state.task_update(task_id, "running", turn_id=receipt.turn_id)
                    await self.state.queue_reply(task_id + "-running",
                        f"**任务执行中**\n\n项目：{inline_literal(target.project_alias)}\n\n任务：{inline_literal(task_id)}",
                        priority=3, task_id=task_id, kind="progress")
            else:
                if current["state"] not in TERMINAL:
                    await self.state.task_update(task_id, "queued", queue_id=receipt["id"])
                await self.state.queue_reply(task_id + "-accepted",
                    f"**任务已排队**\n\n项目：{inline_literal(target.project_alias)}\n\n任务：{inline_literal(task_id)}",
                    priority=4, task_id=task_id, kind="accepted")
        except QueueFull:
            await self.state.task_finish(task_id, "failed", f"原生队列已满，任务未提交：{task_id}；请等待队列空位。")
            await self.controller.subscriptions.release(target, "task-" + task_id)
        except ImageError as exc:
            await self.state.task_finish(task_id, "failed", f"图片任务未提交：{task_id}。{exc}。")
            await self.controller.subscriptions.release(target, "task-" + task_id)
        except BaseException:
            current = await self.state.tasks(task_id=task_id)
            if current["state"] == "cancelled" and not attempted:
                await self.controller.subscriptions.release(target, "task-" + task_id)
                return  # A local received-only cancellation won before dispatch.
            if current["state"] not in TERMINAL:
                if attempted:
                    await asyncio.shield(self.state.task_update(task_id, "unknown"))
                    await self.state.queue_reply(task_id + "-unknown", f"任务状态未知：{task_id}；不会自动重发，请使用 /status 核对。", priority=0)
                else:
                    await asyncio.shield(self.state.task_finish(task_id, "failed", f"任务未提交，目标核验失败：{task_id}。"))
                    await self.controller.subscriptions.release(target, "task-" + task_id)
            raise

    async def drain_admission(self):
        any_ready = (self.controller.any_backend_ready() if hasattr(self.controller, "any_backend_ready")
                     else self.controller.native_ready)
        if not any_ready:
            return
        if self.controller.recovering:
            return
        async with self.admission_gate:
            active = await self.state.tasks(active_only=True)
            if any(task["state"] == "received" for task in active):
                try:
                    await self.catalog.discover()
                except DiscoveryUnavailable as exc:
                    for task in active:
                        if task['state'] == 'received':
                            await self.state.admission_wait(task, str(exc), ())
                    return
            for task in active:
                if task["state"] != "received":
                    continue
                if self.earlier_waiting(task, active):
                    continue
                target = restore_target(task["target"])
                backend_ready = (self.controller.backend_ready(target.agent)
                                 if hasattr(self.controller, "backend_ready") else self.controller.native_ready)
                if not backend_ready:
                    continue
                try:
                    await self.catalog.require(target)
                    current_key = await repository_key(target.cwd,
                        self.controller.routes.projects[target.project_alias].root)
                    if current_key != task["target"].get("repository"):
                        raise SessionUnbound("Repository changed during admission wait")
                except (SessionUnbound, ValueError):
                    await self.state.task_finish(task["id"], "failed", f"准入等待期间会话或仓库已变化，未提交任务：{task['id']}。")
                    continue
                if task.get("input_items"):
                    rows = await self.state.attachments(task_id=task["id"])
                    if not rows or any(row["state"] in {"failed", "released"} for row in rows):
                        await self.state.task_finish(task["id"], "failed", f"图片准备不可用，未提交：{task['id']}。")
                        continue
                    if any(row["state"] != "ready" for row in rows):
                        self.start_image_preparation(task)
                        continue
                reason = await conflict(task, active, self.catalog, self.controller.routes.projects)
                if reason is None:
                    await self.state.supersede_reply(task["id"] + "-waiting")
                    await self.dispatch(task)
                    active = await self.state.tasks(active_only=True)
                else:
                    await self.state.admission_wait(task, str(reason), getattr(reason, "blockers", ()))

    async def turns(self, thread_id):
        cursor, seen = None, set()
        for _ in range(200):
            # One full turn per frame avoids including nineteen unrelated tool outputs.
            params = {"threadId": thread_id, "limit": 1, "itemsView": "full", "sortDirection": "desc"}
            if cursor:
                params["cursor"] = cursor
            page = await self.native.rpc.request("thread/turns/list", params)
            rows = page.get("data") if isinstance(page, dict) else None
            if not isinstance(rows, list) or len(rows) > 1 or any(
                not isinstance(t, dict) or not isinstance(t.get("id"), str) or not isinstance(t.get("items"), list)
                for t in rows
            ):
                raise ValueError("Malformed bounded native turn page")
            for turn in rows:
                yield turn
            cursor = page.get("nextCursor")
            if cursor is None:
                return
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError("Invalid native turn cursor")
            seen.add(cursor)

    async def read_turn(self, thread_id, turn_id):
        async for turn in self.turns(thread_id):
            if turn["id"] == turn_id:
                return turn
        raise ValueError("Exact native turn is not in the bounded history")

    async def business_users(self, thread_id, turn, task=None):
        users = [i for i in turn.get('items', []) if i.get('type') == 'userMessage']
        return (await self.state.async_business_users(thread_id, turn['id'], users, task)
                if len(users) > 1 else users)

    async def reconcile_historical_result(self, task, target):
        # Frozen task identity and unique native client/turn evidence may prove
        # completion even when its old route or unloaded thread cannot dispatch.
        # This never hydrates the thread or creates a new routing qualification.
        if task["target"].get("thread_id") != task["thread_id"]:
            return
        generation = self.native.runtime_identity
        native_session = None

        async def exact_history():
            nonlocal native_session
            thread = await self.native.inspect(task["thread_id"])
            valid = (isinstance(thread, dict) and thread.get("id") == task["thread_id"]
                    and thread.get("cwd") == str(target.cwd)
                    and isinstance(thread.get("sessionId"), str) and bool(thread["sessionId"])
                    and (native_session is None or thread["sessionId"] == native_session)
                    and isinstance(thread.get("status"), dict)
                    and thread["status"].get("type") in {"idle", "active", "notLoaded", "systemError"}
                    and self.native.runtime_identity == generation)
            if valid:
                native_session = thread["sessionId"]
            return valid

        if not await exact_history():
            return
        external = task["target"].get("source") == "external"
        client = task["target"].get("native_client_id") if external else task["client_id"]
        if not client or external and not task["turn_id"]:
            return
        linked = await self.state.tasks(client_id=client)
        if linked is not None and linked["id"] != task["id"]:
            return
        found = None
        async for turn in self.turns(task["thread_id"]):
            users = await self.business_users(task['thread_id'], turn, task)
            if not any(item.get("clientId") == client for item in users):
                continue
            if found is not None or len(users) != 1:
                return
            found = turn
        if (found is not None and found.get("status") in {"completed", "failed", "interrupted"}
                and (task["turn_id"] is None or found["id"] == task["turn_id"])):
            if not await exact_history():
                return
            await self.complete(task["thread_id"], found)

    async def reconcile(self):
        """Only read the original runtime; this path never adds a native task."""
        await self.reconcile_results()
        await self.recovery.reconcile(force=True)

    async def reconcile_results(self, *, thread_id=None):
        tasks = [t for t in await self.state.tasks(active_only=True) if t['state']=='unknown']
        if thread_id is not None:
            tasks=[t for t in tasks if t['thread_id']==thread_id]
        else:
            # Released ownership never discards the chance to recover an exact
            # result later. Explicit refresh advances a bounded historical page.
            page=await self.state.unknown_history_page(after=self.history_cursor,limit=20)
            self.history_cursor=page[-1]['id'] if len(page)==20 else ''
            tasks=list({t['id']:t for t in tasks+page}.values())
        groups = {}
        for task in tasks:
            target = restore_target(task["target"])
            if target.agent != "codex":
                continue
            try:
                session = await self.catalog.require(target)
            except SessionUnbound:
                await self.reconcile_historical_result(task, target)
                continue
            if session.binding.thread_id != task["thread_id"]:
                raise ValueError("Stored task thread differs from current native identity")
            await self.controller.subscriptions.acquire(target, "task-" + task["id"])
            if task["target"].get("source") == "external":
                if task["turn_id"]:
                    turn = await self.read_turn(task["thread_id"], task["turn_id"])
                    users = await self.business_users(task['thread_id'], turn, task)
                    client = users[0].get("clientId") if len(users) == 1 else None
                    expected = task["target"].get("native_client_id")
                    linked = await self.state.tasks(client_id=client) if client else None
                    if (len(users) != 1 or expected is not None and client != expected
                            or linked is not None and linked["id"] != task["id"]):
                        await self.state.queue_reply(task["id"] + "-ambiguous",
                            f"桌面任务关联存在输入合并或身份冲突：{task['id']}；保持未知，请核对原终端。", priority=0)
                        continue
                    if turn.get("status") in {"completed", "failed", "interrupted"}:
                        await self.complete(task["thread_id"], turn)
                    elif turn.get("status") == "inProgress":
                        await self.state.task_update(task["id"], "running", turn_id=turn["id"])
                continue
            groups.setdefault(task["thread_id"], []).append(task)
        for thread_id, group in groups.items():
            queued = await self.queue(thread_id, restore_target(group[0]["target"]).cwd).list()
            clients = {t["client_id"] for t in group}
            matches = {c: [] for c in clients}
            # Keep only identity/status metadata, not hundreds of historical outputs.
            async for turn in self.turns(thread_id):
                users = await self.business_users(thread_id, turn)
                for user in users:
                    client = user.get("clientId")
                    if client in matches:
                        matches[client].append((turn["id"], turn.get("status"), len(users)))
            for task in group:
                found = matches[task["client_id"]]
                pending = [q for q in queued if q["clientUserMessageId"] == task["client_id"]]
                if len(found) > 1 or len(pending) > 1 or found and found[0][2] != 1:
                    await self.state.queue_reply(task["id"] + "-ambiguous",
                        f"原生任务关联存在重复或输入合并：{task['id']}；保持未知，请核对原终端。", priority=0)
                elif found:
                    turn_id, status, _ = found[0]
                    if status in {"completed", "failed", "interrupted"}:
                        await self.complete(thread_id, await self.read_turn(thread_id, turn_id))
                    elif status == "inProgress":
                        await self.state.task_update(task["id"], "running", turn_id=turn_id)
                        self.turn_tasks[(thread_id, turn_id)] = task["id"]
                elif len(pending) == 1:
                    await self.state.task_update(task["id"], "queued", queue_id=pending[0]["id"])
                # Absence within this bounded window is not proof of non-execution.

    async def map_turn(self, thread_id, turn):
        users = await self.business_users(thread_id, turn)
        matches = []
        for user in users:
            if user.get("clientId"):
                task = await self.state.tasks(client_id=user["clientId"])
                if task:
                    if task["thread_id"] != thread_id:
                        raise ValueError("Native task escaped its frozen thread")
                    matches.append(task)
        if matches and len(users) != 1:
            for task in matches:
                if task["state"] not in TERMINAL:
                    await self.state.task_update(task["id"], "unknown", turn_id=turn["id"])
            raise ValueError("Native turn merged separate inputs; cannot claim independent completion")
        if len(matches) == 1:
            # An answer for another task must not be hidden by the generic history view.
            if len(await self.business_users(thread_id, turn, matches[0])) != 1:
                if matches[0]['state'] not in TERMINAL:
                    await self.state.task_update(matches[0]['id'], 'unknown', turn_id=turn['id'])
                raise ValueError('Native turn contains an answer for a different task')
            self.turn_tasks[(thread_id, turn["id"])] = matches[0]["id"]
            return matches[0]
        task = await self.state.tasks(native_turn=(thread_id, turn["id"]))
        return task if task and task["target"].get("source") == "external" else None

    def controlled_target(self, thread_id):
        observer = self.observed(thread_id)
        if observer:
            return observer
        target = self.controller.routes.target
        session = self.controller.subscriptions.bound.get(target.session_id) if target else None
        return target if session and session.binding.thread_id == thread_id else None

    async def adopt_external(self, target, thread_id, turn_id, user):
        session = self.controller.subscriptions.event_session(target, thread_id)
        task = await self.state.external_task(target_record(session), turn_id,
                                              native_client_id=user.get("clientId"))
        await self.controller.subscriptions.retain_event(target, thread_id, "task-" + task["id"])
        self.turn_tasks[(session.binding.thread_id, turn_id)] = task["id"]
        return task

    async def sync_external(self, target):
        if target.agent != "codex":
            return
        session = await self.catalog.require(target)
        thread_id = session.binding.thread_id
        if (await self.native.inspect(thread_id)).get("status", {}).get("type") != "active":
            return
        async for turn in self.turns(thread_id):
            if turn.get("status") != "inProgress":
                return
            users = await self.business_users(thread_id, turn)
            if len(users) == 1 and await self.map_turn(thread_id, turn) is None:
                await self.adopt_external(target, thread_id, turn["id"], users[0])
            return  # Only the latest currently running turn, never historic adoption.

    async def complete(self, thread_id, turn):
        for item in turn.get('items', []):
            if item.get('type') == 'userMessage':
                await self.state.async_user(thread_id, turn['id'], item)
        await self.state.async_close(thread_turn=(thread_id, turn['id']), reason='turn_ended')
        task = await self.map_turn(thread_id, turn)
        status = turn.get("status")
        if status not in {"completed", "failed", "interrupted"}:
            return
        output = native_output(turn)
        task_result = task and (task["target"].get("source") != "external" or task["state"] == "stopping")
        if task:
            text = f"**任务{task_state(status).removeprefix('已')}**\n\n项目：{inline_literal(task['target']['project_alias'])}\n\n任务：{inline_literal(task['id'])}\n\n" + output
            await self.state.task_finish(task["id"], status, text, turn_id=turn["id"],
                                         deliver=bool(task_result))
            await self.controller.subscriptions.release(restore_target(task["target"]), "task-" + task["id"])
        if not task_result and (thread_id, turn["id"]) in self.observed_turns:
            observer = self.controller.routes.observer
            session = self.controller.subscriptions.bound.get(observer.session_id) if observer else None
            if session and session.binding.thread_id == thread_id:
                key = hashlib.sha256((thread_id + turn["id"]).encode()).hexdigest()
                text = f"**观察任务 · {task_state(status)}**\n\n项目：{inline_literal(observer.project_alias)}\n\n" + output
                # Observation output uses the same bounded transport segmentation.
                chunks = await render_in_worker(text, renderer=render_segments, slots=self.state.render_slots,
                    prefix=lambda i, n: f"〔观察：{observer.project_alias} {i}/{n}〕\n\n" if n > 1 else "")
                for index, chunk in enumerate(chunks, 1):
                    await self.state.queue_reply(f"observe-{key}-{index - 1}", chunk, priority=2)
            self.observed_turns.discard((thread_id, turn["id"]))
        self.turn_tasks.pop((thread_id, turn["id"]), None)
        self.observed_turns.discard((thread_id, turn["id"]))

    def observed(self, thread_id):
        target = self.controller.routes.observer
        session = self.controller.subscriptions.bound.get(target.session_id) if target else None
        return target if session and session.binding.thread_id == thread_id else None

    async def complete_agy(self, params):
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        status = params.get("status")
        if not isinstance(thread_id, str) or not isinstance(turn_id, str) or status not in {"completed", "failed", "interrupted"}:
            return
        task_id = self.turn_tasks.get((thread_id, turn_id))
        task = await self.state.tasks(task_id=task_id) if task_id else await self.state.tasks(native_turn=(thread_id, turn_id))
        if task is None and isinstance(params.get("clientId"), str):
            task = await self.state.tasks(client_id=params["clientId"])
        if task is None:
            return
        raw_text = params.get("text") if isinstance(params.get("text"), str) else ""
        error_text = params.get("error") if isinstance(params.get("error"), str) else ""
        if status == "failed" and error_text:
            output = (raw_text.strip() + "\n\n" if raw_text.strip() else "") + "原生错误：" + error_text
        elif raw_text.strip():
            output = raw_text.strip()
        elif status == "interrupted":
            output = "任务已中断。"
        else:
            output = "任务已结束，未返回文本内容。"
        text = (f"**任务{task_state(status).removeprefix('已')}**\n\n项目：{inline_literal(task['target']['project_alias'])}"
                f"\n\n任务：{inline_literal(task['id'])}\n\n" + output)
        await self.state.task_finish(task["id"], status, text, turn_id=turn_id, deliver=True)
        await self.controller.subscriptions.release(restore_target(task["target"]), "task-" + task["id"])
        self.turn_tasks.pop((thread_id, turn_id), None)
        self.recovery.wake.set()

    async def event(self, event):
        method, params = event.get("method"), event.get("params", {})
        if method == "agy/turn/completed":
            await self.complete_agy(params)
            return
        thread_id, turn_id = params.get("threadId"), params.get("turnId")
        if not isinstance(thread_id, str):
            return
        active_turn = params.get('turn', {}).get('id') if method == 'turn/started' else turn_id
        if method in {'turn/started', 'item/started'} and isinstance(active_turn, str):
            # This exact historical association is only a conflict signal. It
            # cannot subscribe, restore a route, read an unrelated turn or submit.
            if await self.state.reactivate_occupancy(thread_id, active_turn):
                self.recovery.trigger(thread_id)
        if method == 'turn/completed' and thread_id in self.recovery.schedule:
            self.recovery.trigger(thread_id)
        if not any(s.binding.thread_id == thread_id for s in self.controller.subscriptions.bound.values()):
            return  # Never read turns for unrelated runtime-wide notifications.
        self.native_controls.event(method, params)
        if method == "turn/started":
            turn_id = params.get("turn", {}).get("id")
            if turn_id and self.observed(thread_id):
                self.observed_turns.add((thread_id, turn_id))
        elif method == "item/started" and params.get("item", {}).get("type") == "userMessage":
            if await self.state.async_user(thread_id, turn_id, params['item']):
                return  # A durable exact supplement is never a new desktop task.
            task = await self.map_turn(thread_id, {"id": turn_id, "items": [params["item"]]})
            if task is None and (target := self.controlled_target(thread_id)):
                task = await self.adopt_external(target, thread_id, turn_id, params["item"])
                if self.observed(thread_id):
                    await self.state.queue_reply("observe-start-" + hashlib.sha256((thread_id + turn_id).encode()).hexdigest(),
                        f"观察：{target.project_alias} 的桌面任务已开始。", priority=3)
            if task and task["state"] not in TERMINAL:
                await self.state.task_update(task["id"], "running", turn_id=turn_id)
                if task["target"].get("source") != "external":
                    self.observed_turns.discard((thread_id, turn_id))
                    await self.state.queue_reply(task["id"] + "-running",
                        f"**任务执行中**\n\n项目：{inline_literal(task['target']['project_alias'])}\n\n任务：{inline_literal(task['id'])}",
                        priority=3, task_id=task["id"], kind="progress")
        elif method == "turn/completed":
            turn_id = params.get("turn", {}).get("id")
            if turn_id:
                await self.state.async_close(thread_turn=(thread_id, turn_id), reason='turn_ended')
                if self.results is not None:
                    self.results.enqueue(thread_id, turn_id)
                else:
                    await self.complete_turn(thread_id, turn_id)
        elif method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
            item = params['item']
            if item.get('delivery') == 'async' and item.get('questions') is not None:
                await self.async_questions.register(thread_id, turn_id, item)
        elif method in {APPROVAL, QUESTION, ACP_APPROVAL}:
            task_id = self.turn_tasks.get((thread_id, turn_id))
            target = self.observed(thread_id)
            if task_id:
                task = await self.state.tasks(task_id=task_id)
                if task["target"].get("source") == "external" and not self.observed(thread_id):
                    return  # Focus alone does not subscribe to new desktop interactions.
                target = restore_target(task["target"])
            if target is None and method != ACP_APPROVAL:
                # Map using the exact native turn, without adopting unrelated desktop tasks.
                turn = await self.read_turn(thread_id, turn_id)
                task = await self.map_turn(thread_id, turn)
                if task:
                    if task["target"].get("source") == "external" and not self.observed(thread_id):
                        return
                    target = restore_target(task["target"])
            if target is None and method == ACP_APPROVAL:
                task = await self.state.tasks(native_turn=(thread_id, turn_id))
                if task:
                    target = restore_target(task["target"])
            if target is None:
                return  # No approval is synthesized for an unobserved desktop task.
            self.trim_interactions()
            size = len(json.dumps(params, ensure_ascii=False).encode())
            shared_count, shared_size = await self.state.async_budget()
            if shared_count >= 256 or shared_size + size > 16 * 1024 * 1024:
                key = hashlib.sha256(json.dumps([thread_id, event.get("id")]).encode()).hexdigest()
                await self.state.queue_reply("interaction-limit-" + key,
                    "交互记录已达容量上限，请在原终端处理本次请求；没有发送自动答复。", priority=0)
                return
            rpc = (self.backend_for("antigravity").rpc if method == ACP_APPROVAL else self.native.rpc)
            broker = self.brokers.setdefault(thread_id, InteractionBroker(rpc, thread_id,
                                            generation=self.generation, persist=self.persist_interaction))
            record = broker.register(event)
            if record.public_id not in self.interaction_targets:
                session = await self.controller.subscriptions.retain_event(target, thread_id, "interaction-" + record.public_id)
                self.interaction_targets[record.public_id] = (target_record(session), time.time() + broker.ttl)
                self.interaction_sizes[record.public_id] = size
            await broker.sync(record)
            if record.state != "pending":
                return
            task = await self.state.tasks(native_turn=(thread_id, turn_id))
            if task and task["state"] not in TERMINAL:
                await self.state.task_update(task["id"], "waiting_interaction")
            if method in {APPROVAL, ACP_APPROVAL}:
                prefix = "Antigravity 审批" if method == ACP_APPROVAL else "审批"
                text = (f"{prefix}：{target.project_alias}｜{record.public_id}\n\n```sh\n{params['command']}\n```\n\n"
                        f"/approve {record.public_id}\n/deny {record.public_id}")
            else:
                lines = []
                for question in params["questions"]:
                    labels = "／".join(option["label"] for option in question.get("options") or [])
                    lines.append(f"{question['id']}：{question.get('question', '')}\n{labels}")
                text = f"追问：{target.project_alias}｜{record.public_id}\n" + "\n".join(lines)
                text += f"\n/answer {record.public_id} <单题回答，或多题 JSON 对象>"
            if len(text) > 7000:
                record.state = "stale"
                await broker.sync(record)
                await self.release_interaction(thread_id, record)
                await self.state.queue_reply(record.public_id + "-native-only",
                    f"交互内容超过微信完整展示上限：{record.public_id}。请在原终端查看并处理；微信不提供截断后的审批或答复。", priority=0)
                return
            await self.state.queue_reply(record.public_id + "-prompt", text, priority=0)
        elif method == "serverRequest/resolved":
            broker = self.brokers.get(thread_id)
            record = broker.resolved(event) if broker else None
            if record:
                await broker.sync(record)
                task = await self.state.tasks(native_turn=(thread_id, record.turn_id))
                if task and task["state"] == "waiting_interaction":
                    await self.state.task_update(task["id"], "running")
                await self.release_interaction(thread_id, record)
                await self.state.queue_reply(record.public_id + "-resolved", f"交互已由原生会话处理：{record.public_id}；迟到答复不再接受。", priority=0)
        elif "id" in event:
            key = hashlib.sha256(json.dumps([thread_id, event["id"], method]).encode()).hexdigest()
            await self.state.queue_reply("unsupported-" + key,
                "当前原生请求类型尚未支持，请在原终端处理；没有发送自动答复。", priority=0)

    def trim_interactions(self):
        closed = sorted(((r.deadline, broker, r) for broker in self.brokers.values()
                         for r in broker.records.values() if r.state in {"resolved", "stale"}), key=lambda v: v[0])
        # Keep a bounded recent handled history and all current unanswered requests.
        for _, broker, record in closed[:-64]:
            broker.records.pop(record.public_id, None)
            broker.native.pop((type(record.native_id), record.native_id), None)
        retained = {public_id for broker in self.brokers.values() for public_id in broker.records}
        for public_id in set(self.interaction_targets) - retained:
            self.interaction_targets.pop(public_id, None)
            self.interaction_sizes.pop(public_id, None)

    async def prune_memory(self):
        active = await self.state.tasks(active_only=True)
        active_ids = {t['id'] for t in active}
        subscriptions = self.controller.subscriptions
        for session_id, roles in tuple(subscriptions.roles.items()):
            for role in tuple(roles):
                if not role.startswith('task-') or role[5:] in active_ids:
                    continue
                rows = await self.state.occupancy_snapshot(task_id=role[5:])
                if rows and rows[0]['state']=='unknown' and rows[0]['occupancy']['state']=='released':
                    session = subscriptions.bound.get(session_id)
                    if session is not None:
                        await subscriptions.release(session.target, role)
        sessions = tuple(self.catalog.sessions.values()) + tuple(self.controller.subscriptions.bound.values())
        valid_ids = {s.target.session_id for s in sessions} | {t["target"]["session_id"] for t in active}
        for key, lock in tuple(self.admission.items()):
            if key not in valid_ids and not lock.locked():
                del self.admission[key]
        valid_queues = {(s.binding.thread_id, s.target.cwd) for s in sessions}
        valid_queues |= {(t["thread_id"], Path(t["target"]["cwd"])) for t in active}
        for key in set(self.queues) - valid_queues:
            del self.queues[key]
        self.turn_tasks = {key: value for key, value in self.turn_tasks.items() if value in active_ids}
        self.observed_turns = {key for key in self.observed_turns if self.observed(key[0])}
        self.trim_interactions()
        bound_threads = {s.binding.thread_id for s in sessions}
        for thread_id, broker in tuple(self.brokers.items()):
            if not broker.records and thread_id not in bound_threads:
                del self.brokers[thread_id]
        agy = self.backend_for("antigravity")
        if agy is not None and agy.runtime_identity is not None and hasattr(agy, "evict_idle_sessions"):
            protected = set()
            focused = self.controller.routes.target
            if focused is not None and focused.agent == "antigravity":
                s = self.catalog.sessions.get(focused.session_id) or subscriptions.bound.get(focused.session_id)
                if s is not None:
                    protected.add(s.binding.thread_id)
            for s in subscriptions.bound.values():
                if getattr(s.binding, "agent", "codex") == "antigravity":
                    protected.add(s.binding.thread_id)
            for t in active:
                if t["target"].get("agent") == "antigravity" and t.get("thread_id"):
                    protected.add(t["thread_id"])
            await agy.evict_idle_sessions(protected_session_ids=protected)

    async def complete_turn(self, thread_id, turn_id):
        await self.complete(thread_id, await self.read_turn(thread_id, turn_id))

    async def consume_events(self):
        while True:
            try:
                event = await self.native.rpc.next_event(timeout=1)
            except TimeoutError:
                continue
            await self.event(event)

    async def consume_agy_events(self):
        while True:
            agy = self.backend_for("antigravity")
            if agy is None or agy.runtime_identity is None:
                await asyncio.sleep(0.2)
                continue
            try:
                event = await agy.next_event(timeout=0.5)
            except TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(0.2)
                continue
            await self.event(event)

    async def run(self):
        self.results = ResultWork(self.complete_turn)
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self.results.run())
                if hasattr(self.native, "rpc"):
                    tasks.create_task(self.consume_events())
                tasks.create_task(self.consume_agy_events())
                tasks.create_task(self.recovery.run())
        finally:
            self.results = None
            for broker in self.brokers.values():
                broker.disconnect()
            await asyncio.shield(self.state.stale_interactions(self.generation))
            await asyncio.shield(self.state.async_close(generation=self.generation, reason='disconnected'))

    async def maintain(self):
        while True:
            if self.image_errors:
                self.image_errors.clear()
            await self.expire_interactions()
            await self.async_questions.expire()
            try:
                await self.drain_admission()
            except HostUnavailable:
                pass  # Frozen received tasks wait; existing native events continue.
            await self.prune_memory()
            await asyncio.sleep(1)

    async def control(self, command):
        return await handle_control(self, command)
