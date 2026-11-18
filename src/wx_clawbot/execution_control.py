"""Control command handling extracted from Execution engine."""

import json

from .commands import CommandError
from .interactions import APPROVAL, QUESTION
from .output import inline_literal, target_description, task_state


async def handle_control(execution, command):
    from .execution import TERMINAL, restore_target

    name = command.name
    if name == 'answer' and command.argument.startswith('q-'):
        return await execution.async_questions.answer(command.argument, command.text)
    if name in {'approve', 'deny'} and command.argument.startswith('q-'):
        raise CommandError('这是异步补充问题，不是审批；请使用 /answer。')
    if name in {"approve", "deny", "answer"}:
        if not execution.native.capabilities.shared_interactions:
            raise CommandError("当前 Agent 不支持共享交互，未发送答复。")
        candidates = [(b, b.records[command.argument]) for b in execution.brokers.values() if command.argument in b.records]
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
        routes = execution.controller.routes
        describe = lambda t: target_description(t) if t else "未选择"
        tasks = await execution.state.tasks(active_only=True)
        active = [f"{'桌面任务 ' if t['target'].get('source') == 'external' else '任务：'}{inline_literal(t['id'])} · {task_state(t['state'])}"
                  for t in tasks if t["state"] not in TERMINAL]
        interactions = [f"待处理交互：{r.public_id}（剩余 {max(0, int(r.deadline-b.clock()))} 秒）"
                        for b in execution.brokers.values() for r in b.records.values()
                        if r.state == "pending" and b.clock() < r.deadline]
        delivery = await execution.state.delivery_counts()
        occupancy = await execution.state.occupancy_counts()
        return (f"**任务总览**\n\n输入会话：{describe(routes.target)}\n\n观察会话：{describe(routes.observer)}\n\n"
                + ("\n\n".join(active[:20]) or "暂无未结束任务。")
                + ("\n\n" + "\n\n".join(interactions[:20]) if interactions else "")
                + ('\n\n' + await execution.async_questions.status())
                + f"\n\n历史未知且已释放占用：{occupancy.get('released_unknown', 0)} 条；结果未改写。"
                + f"\n\n回执：待发 {delivery.get('pending', 0)}，投递未知 {delivery.get('unknown', 0)}，拒绝 {delivery.get('rejected', 0)}。")
    if command.argument:
        task = await execution.state.tasks(task_id=command.argument)
    else:
        target = execution.controller.routes.target
        candidates = [t for t in await execution.state.tasks(active_only=True) if t["state"] not in TERMINAL
                      and target and t["target"]["session_id"] == target.session_id]
        if len(candidates) != 1:
            raise CommandError("请提供准确的任务 ID；不会猜测要停止哪一条任务。")
        task = candidates[0]
    if task is None:
        raise CommandError("任务不存在。")
    if name == "status":
        return (f"**任务状态 · {task_state(task['state'])}**\n\n项目：{inline_literal(task['target']['project_alias'])}\n\n任务：{inline_literal(task['id'])}\n\n"
                + await execution.state.describe_admission(task) + '\n\n' + await execution.async_questions.status(task['id']))
    if task["state"] in TERMINAL:
        return f"任务已结束：{task['id']}｜{task['state']}。"
    if task['state'] == 'unknown':
        holds = await execution.state.occupancy_snapshot(task_id=task['id'])
        if holds and holds[0]['occupancy']['state'] == 'released':
            return (f"历史执行结果仍未知，仓库占用已释放：{task['id']}。"
                    '本次未发送取消或中断，不会因停止查询重新占用仓库；请核对原终端记录。')
    if task["state"] == "received":
        if await execution.state.task_finish(task["id"], "cancelled",
                f"已撤销尚未提交的准入等待：{task['id']}；没有发送原生任务。",
                only_if={"received"}, reply_priority=0):
            if task["id"] in execution.image_jobs:
                execution.image_jobs[task["id"]].cancel()
            return None
        task = await execution.state.tasks(task_id=task["id"])
        if task["state"] in TERMINAL:
            return f"任务已结束：{task['id']}｜{task['state']}。"
    if not execution.native.capabilities.interrupt:
        raise CommandError("当前 Agent 不支持已验证的原生停止操作，未发送中断。")
    target = restore_target(task["target"])
    await execution.catalog.require(target)
    queue = execution.queue(task["thread_id"], target.cwd)
    if task["queue_id"] and await queue.delete(task["queue_id"]):
        await execution.state.task_finish(task["id"], "cancelled", f"原生队列已确认取消：{task['id']}。", reply_priority=0)
        await execution.controller.subscriptions.release(target, "task-" + task["id"])
        return None
    task = await execution.state.tasks(task_id=task["id"])
    if task["state"] in TERMINAL:
        return f"原生任务已结束：{task['id']}｜{task['state']}。"
    if not task["turn_id"]:
        raise CommandError("尚无运行 turn 的准确关联，停止未确认；不会中断其他任务。")
    await execution.state.task_update(task["id"], "stopping")
    current = await execution.state.tasks(task_id=task["id"])
    if current["state"] in TERMINAL:
        return f"原生任务已结束：{task['id']}｜{current['state']}。"
    try:
        await queue.request_interrupt(task["turn_id"])
    except Exception:
        current = await execution.state.tasks(task_id=task["id"])
        if current["state"] in TERMINAL:
            return f"原生任务已结束：{task['id']}｜{current['state']}。"
        raise
    current = await execution.state.tasks(task_id=task["id"])
    if current["state"] in TERMINAL:
        return f"原生任务已结束：{task['id']}｜{current['state']}。"
    return f"已请求中断：{task['id']}；等待原生 interrupted 确认。"
