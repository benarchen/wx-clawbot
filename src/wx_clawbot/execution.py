"""One native event stream, durable submission identities and explicit terminal receipts."""

import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

from .agents.queue import NativeQueue, QueueFull
from .admission import conflict, repository_key
from .commands import CommandError
from .controller import target_record
from .interactions import APPROVAL, QUESTION, InteractionBroker
from .routing import Target
from .sessions import SessionUnbound


TERMINAL = {"completed", "failed", "interrupted", "cancelled"}


def restore_target(record):
    return Target(record["session_id"], record["project_alias"], Path(record["cwd"]), record["origin"])


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
        self.admission_gate = asyncio.Lock()

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

    def queue(self, thread_id, cwd):
        key = (thread_id, cwd)
        if key not in self.queues:
            self.queues[key] = NativeQueue(self.native, thread_id, cwd)
        return self.queues[key]

    async def submit(self, message_id, dispatch):
        # This lock is obtained before the first external await, preserving receive
        # order even if later endpoint verification takes different amounts of time.
        lock = self.admission.setdefault(dispatch.target.session_id, asyncio.Lock())
        async with lock:
            async with self.admission_gate:
                await self._submit_locked(message_id, dispatch)

    async def _submit_locked(self, message_id, dispatch):
        if not self.native.capabilities.queue:
            raise CommandError("当前 Agent 未提供已验证的原生队列能力，任务未接收。")
        session = await self.catalog.require(dispatch.target)
        record = target_record(session)
        record["repository"] = await repository_key(dispatch.target.cwd,
                                  self.controller.routes.projects[dispatch.target.project_alias].root)
        active = await self.state.tasks(active_only=True)
        if sum(t["target"]["session_id"] == dispatch.target.session_id and t["state"] not in {"running", "stopping"}
               for t in active) >= 10:
            raise CommandError("该会话的桥接排队或准入等待已达十条，新任务未接收。")
        task = await self.state.task_intent(message_id, record, dispatch.text)
        if task is None:
            return  # A source native message is never submitted a second time.
        task = await self.state.tasks(task_id=task["id"])
        await self.state.task_update(task["id"], "received")
        try:
            reason = await conflict(task, active, self.catalog, self.controller.routes.projects)
        except BaseException:
            await asyncio.shield(self.state.task_finish(task["id"], "failed",
                f"仓库或桌面活动核验失败，任务未提交：{task['id']}。"))
            raise
        if reason:
            await self.state.queue_reply(task["id"] + "-waiting",
                f"任务已接收，等待准入：{task['id']}。{reason}；尚未进入原生队列。",
                priority=2, task_id=task["id"], kind="progress")
            return
        await self.dispatch(task)

    async def dispatch(self, task):
        target = restore_target(task["target"])
        record, text = task["target"], task["input"]
        task_id, thread_id = task["id"], record["thread_id"]
        attempted = False
        try:
            await self.controller.subscriptions.acquire(target, "task-" + task_id)
            await self.catalog.require(target)
            await self.state.task_update(task_id, "dispatching")
            attempted = True
            receipt = await self.queue(thread_id, target.cwd).add(text, task["client_id"])
            current = await self.state.tasks(task_id=task_id)
            if current["state"] not in TERMINAL:
                await self.state.task_update(task_id, "queued", queue_id=receipt["id"])
            await self.state.queue_reply(task_id + "-accepted",
                f"已进入原生队列：{target.project_alias}｜{task_id}。",
                priority=4, task_id=task_id, kind="accepted")
        except QueueFull:
            await self.state.task_finish(task_id, "failed", f"原生队列已满，任务未提交：{task_id}；请等待队列空位。")
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
        async with self.admission_gate:
            active = await self.state.tasks(active_only=True)
            for task in active:
                if task["state"] != "received":
                    continue
                target = restore_target(task["target"])
                try:
                    await self.catalog.require(target)
                    current_key = await repository_key(target.cwd,
                        self.controller.routes.projects[target.project_alias].root)
                    if current_key != task["target"].get("repository"):
                        raise SessionUnbound("Repository changed during admission wait")
                except (SessionUnbound, ValueError):
                    await self.state.task_finish(task["id"], "failed", f"准入等待期间会话或仓库已变化，未提交任务：{task['id']}。")
                    continue
                if await conflict(task, active, self.catalog, self.controller.routes.projects) is None:
                    await self.state.supersede_reply(task["id"] + "-waiting")
                    await self.dispatch(task)
                    active = await self.state.tasks(active_only=True)

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

    async def reconcile(self):
        """Only read the original runtime; this path never adds a native task."""
        tasks = [t for t in await self.state.tasks(active_only=True) if t["state"] == "unknown"]
        groups = {}
        for task in tasks:
            target = restore_target(task["target"])
            try:
                session = await self.catalog.require(target)
            except SessionUnbound:
                continue
            if session.binding.thread_id != task["thread_id"]:
                raise ValueError("Stored task thread differs from current native identity")
            await self.controller.subscriptions.acquire(target, "task-" + task["id"])
            groups.setdefault(task["thread_id"], []).append(task)
        for thread_id, group in groups.items():
            queued = await self.queue(thread_id, restore_target(group[0]["target"]).cwd).list()
            clients = {t["client_id"] for t in group}
            matches = {c: [] for c in clients}
            # Keep only identity/status metadata, not hundreds of historical outputs.
            async for turn in self.turns(thread_id):
                users = [i for i in turn["items"] if i.get("type") == "userMessage"]
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
        users = [item for item in turn.get("items", []) if item.get("type") == "userMessage"]
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
            self.turn_tasks[(thread_id, turn["id"])] = matches[0]["id"]
            return matches[0]
        return None

    async def complete(self, thread_id, turn):
        task = await self.map_turn(thread_id, turn)
        status = turn.get("status")
        if status not in {"completed", "failed", "interrupted"}:
            return
        output = "\n".join(item.get("text", "") for item in turn.get("items", []) if item.get("type") == "agentMessage")
        error = turn.get("error")
        if status == "failed" and isinstance(error, dict) and isinstance(error.get("message"), str) and error["message"].strip():
            output = (output + "\n\n原生错误：" + error["message"]).strip()
        if task:
            text = f"{task['target']['project_alias']}｜{task['id']}｜{status}\n" + (output or "原生任务已结束，没有文本结果。")
            await self.state.task_finish(task["id"], status, text, turn_id=turn["id"])
            await self.controller.subscriptions.release(restore_target(task["target"]), "task-" + task["id"])
        elif (thread_id, turn["id"]) in self.observed_turns:
            observer = self.controller.routes.observer
            session = self.catalog.sessions.get(observer.session_id) if observer else None
            if session and session.binding.thread_id == thread_id:
                key = hashlib.sha256((thread_id + turn["id"]).encode()).hexdigest()
                text = f"观察：{observer.project_alias}｜{status}\n" + (output or "原生任务已结束，没有文本结果。")
                # Observation output uses the same bounded transport segmentation.
                for index in range(0, len(text), 7000):
                    await self.state.queue_reply(f"observe-{key}-{index // 7000}", text[index:index + 7000], priority=2)
            self.observed_turns.discard((thread_id, turn["id"]))
        self.turn_tasks.pop((thread_id, turn["id"]), None)
        self.observed_turns.discard((thread_id, turn["id"]))

    def observed(self, thread_id):
        target = self.controller.routes.observer
        session = self.catalog.sessions.get(target.session_id) if target else None
        return target if session and session.binding.thread_id == thread_id else None

    async def event(self, event):
        method, params = event.get("method"), event.get("params", {})
        thread_id, turn_id = params.get("threadId"), params.get("turnId")
        if not isinstance(thread_id, str):
            return
        if not any(s.binding.thread_id == thread_id for s in self.controller.subscriptions.bound.values()):
            return  # Never read turns for unrelated runtime-wide notifications.
        if method == "turn/started":
            turn_id = params.get("turn", {}).get("id")
            if turn_id and self.observed(thread_id):
                self.observed_turns.add((thread_id, turn_id))
                await self.state.queue_reply("observe-start-" + hashlib.sha256((thread_id + turn_id).encode()).hexdigest(),
                                            f"观察：{self.observed(thread_id).project_alias} 的桌面任务已开始。", priority=3)
        elif method == "item/started" and params.get("item", {}).get("type") == "userMessage":
            task = await self.map_turn(thread_id, {"id": turn_id, "items": [params["item"]]})
            if task and task["state"] not in TERMINAL:
                await self.state.task_update(task["id"], "running", turn_id=turn_id)
                await self.state.queue_reply(task["id"] + "-running",
                    f"任务正在原生会话执行：{task['target']['project_alias']}｜{task['id']}。",
                    priority=3, task_id=task["id"], kind="progress")
        elif method == "turn/completed":
            turn_id = params.get("turn", {}).get("id")
            if turn_id:
                await self.complete(thread_id, await self.read_turn(thread_id, turn_id))
        elif method in {APPROVAL, QUESTION}:
            task_id = self.turn_tasks.get((thread_id, turn_id))
            target = self.observed(thread_id)
            if task_id:
                task = await self.state.tasks(task_id=task_id)
                target = restore_target(task["target"])
            if target is None:
                # Map using the exact native turn, without adopting unrelated desktop tasks.
                turn = await self.read_turn(thread_id, turn_id)
                task = await self.map_turn(thread_id, turn)
                if task:
                    target = restore_target(task["target"])
            if target is None:
                return  # No approval is synthesized for an unobserved desktop task.
            broker = self.brokers.setdefault(thread_id, InteractionBroker(self.native.rpc, thread_id,
                                            generation=self.generation, persist=self.persist_interaction))
            record = broker.register(event)
            if record.public_id not in self.interaction_targets:
                session = await self.catalog.require(target)
                self.interaction_targets[record.public_id] = (target_record(session), time.time() + broker.ttl)
            await broker.sync(record)
            if record.state != "pending":
                return
            await self.controller.subscriptions.acquire(target, "interaction-" + record.public_id)
            if method == APPROVAL:
                text = (f"审批：{target.project_alias}｜{record.public_id}\n{params['command']}\n"
                        f"/approve {record.public_id}\n/deny {record.public_id}")
            else:
                lines = []
                for question in params["questions"]:
                    labels = "／".join(option["label"] for option in question.get("options") or [])
                    lines.append(f"{question['id']}：{question.get('question', '')}\n{labels}")
                text = f"追问：{target.project_alias}｜{record.public_id}\n" + "\n".join(lines)
                text += f"\n/answer {record.public_id} <单题回答，或多题 JSON 对象>"
            await self.state.queue_reply(record.public_id + "-prompt", text, priority=0)
        elif method == "serverRequest/resolved":
            broker = self.brokers.get(thread_id)
            record = broker.resolved(event) if broker else None
            if record:
                await broker.sync(record)
                await self.release_interaction(thread_id, record)
                await self.state.queue_reply(record.public_id + "-resolved", f"交互已由原生会话处理：{record.public_id}；迟到答复不再接受。", priority=0)

    async def run(self):
        try:
            while True:
                try:
                    event = await self.native.rpc.next_event(timeout=1)
                except TimeoutError:
                    continue
                await self.event(event)
        finally:
            for broker in self.brokers.values():
                broker.disconnect()
            await asyncio.shield(self.state.stale_interactions(self.generation))

    async def maintain(self):
        while True:
            await self.expire_interactions()
            await self.drain_admission()
            await asyncio.sleep(1)

    async def control(self, command):
        name = command.name
        if name in {"approve", "deny", "answer"}:
            if not self.native.capabilities.shared_interactions:
                raise CommandError("当前 Agent 不支持共享交互，未发送答复。")
            candidates = [(b, b.records[command.argument]) for b in self.brokers.values() if command.argument in b.records]
            if len(candidates) != 1:
                raise CommandError("请求不存在、已断连或不属于本次连接。")
            broker, record = candidates[0]
            if name in {"approve", "deny"}:
                if record.method != APPROVAL:
                    raise CommandError("这是追问，请使用 /answer。")
                offered = record.params.get("availableDecisions")
                answer = "accept" if name == "approve" else ("cancel" if offered is not None and "decline" not in offered else "decline")
            else:
                if record.method != QUESTION:
                    raise CommandError("这是审批，请使用 /approve 或 /deny。")
                questions = record.params["questions"]
                try:
                    answer = json.loads(command.text) if command.text.lstrip().startswith("{") else {questions[0]["id"]: [command.text]}
                except (ValueError, TypeError) as exc:
                    raise CommandError("多题回答须为题目 ID 到回答数组的 JSON 对象。") from exc
            try:
                await broker.answer(record.public_id, answer, generation=broker.generation, thread_id=broker.thread_id)
            except ValueError as exc:
                raise CommandError("答复未提交：请求已处理、已过期或回答格式不符合原生选项。") from exc
            return f"答复已发送，等待原生处理确认：{record.public_id}。"
        if name == "status" and not command.argument:
            routes = self.controller.routes
            describe = lambda t: f"{t.project_alias}｜{t.session_id}" if t else "未选择"
            tasks = await self.state.tasks(active_only=True)
            active = [f"{t['id']}：{t['state']}" for t in tasks if t["state"] not in TERMINAL]
            interactions = [f"待处理交互：{r.public_id}（剩余 {max(0, int(r.deadline-b.clock()))} 秒）"
                            for b in self.brokers.values() for r in b.records.values()
                            if r.state == "pending" and b.clock() < r.deadline]
            delivery = await self.state.delivery_counts()
            return (f"执行目标：{describe(routes.target)}\n观察订阅：{describe(routes.observer)}\n"
                    + ("\n".join(active[:20]) or "暂无未结束任务。")
                    + ("\n" + "\n".join(interactions[:20]) if interactions else "")
                    + f"\n回执：待发 {delivery.get('pending', 0)}，投递未知 {delivery.get('unknown', 0)}，拒绝 {delivery.get('rejected', 0)}。")
        if command.argument:
            task = await self.state.tasks(task_id=command.argument)
        else:
            target = self.controller.routes.target
            candidates = [t for t in await self.state.tasks() if t["state"] not in TERMINAL
                          and target and t["target"]["session_id"] == target.session_id]
            if len(candidates) != 1:
                raise CommandError("请提供准确的任务 ID；不会猜测要停止哪一条任务。")
            task = candidates[0]
        if task is None:
            raise CommandError("任务不存在。")
        if name == "status":
            return f"{task['target']['project_alias']}｜{task['id']}：{task['state']}。"
        if task["state"] in TERMINAL:
            return f"任务已结束：{task['id']}｜{task['state']}。"
        if task["state"] == "received":
            if await self.state.task_finish(task["id"], "cancelled",
                    f"已撤销尚未提交的准入等待：{task['id']}。", only_if={"received"}):
                return f"已撤销尚未提交的准入等待：{task['id']}；没有发送原生任务。"
            task = await self.state.tasks(task_id=task["id"])
            if task["state"] in TERMINAL:
                return f"任务已结束：{task['id']}｜{task['state']}。"
        if not self.native.capabilities.interrupt:
            raise CommandError("当前 Agent 不支持已验证的原生停止操作，未发送中断。")
        target = restore_target(task["target"])
        await self.catalog.require(target)
        queue = self.queue(task["thread_id"], target.cwd)
        if task["queue_id"] and await queue.delete(task["queue_id"]):
            await self.state.task_finish(task["id"], "cancelled", f"原生队列已确认取消：{task['id']}。")
            await self.controller.subscriptions.release(target, "task-" + task["id"])
            return f"原生队列已确认取消：{task['id']}。"
        if not task["turn_id"]:
            raise CommandError("尚无运行 turn 的准确关联，停止未确认；不会中断其他任务。")
        await queue.request_interrupt(task["turn_id"])
        await self.state.task_update(task["id"], "stopping")
        return f"已请求中断：{task['id']}；等待原生 interrupted 确认。"
