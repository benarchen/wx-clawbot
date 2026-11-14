"""Reasoned, role-specific session notices; never grant native routing authority."""

import asyncio
import copy
import math
import time
import uuid

from .channels.http import ProtocolError
from .output import inline_literal


REASONS = {
    "runtime_changed": "Codex 原生运行时已变化",
    "native_identity_changed": "原生会话身份已变化",
    "not_loaded": "原会话已不在原生运行时中加载",
    "cwd_changed": "原会话的项目目录已变化或不再符合注册范围",
    "evidence_missing": "原会话身份核验证据不足",
    "subscription_unconfirmed": "原会话的原生订阅尚未确认",
    "verification_pending": "会话恢复核验尚未完成",
}
ROLES = {"target": ("输入目标", "focus"), "observer": ("观察订阅", "attach")}


def label(record):
    return inline_literal(str(record.get("project_alias") or "未知项目")[:128]) + " · " + inline_literal(
        str(record.get("session_id") or "未知会话")[:128])


def selection_text(failures, *, restored=False, retained=()):
    lines = ["**会话选择未恢复**" if restored else "**所选会话暂不可用**"]
    for role, record, reason in failures:
        name, command = ROLES[role]
        lines.append(f"{name}：{label(record)}。\n{REASONS.get(reason, REASONS['evidence_missing'])}。")
        lines.append(f"请先发送 `/sessions`，再用 `/{command} <序号>` 重新选择。")
    if retained:
        lines.append("、".join(ROLES[role][0] for role in retained) + "保留。")
    lines.append("不会自动切换到其他会话或重跑已提交任务；任务请用 `/status` 核对。"
                 "列表没有所需会话时，请先在原生客户端打开该对话再刷新。")
    return "\n\n".join(lines)


class SessionNotifications:
    DELAY = 30

    def __init__(self, state, *, wall=time.time, clock=time.monotonic):
        self.state, self.wall, self.clock = state, wall, clock
        self.lock = asyncio.Lock()
        self.timer = None

    async def load(self):
        snapshot = await self.state.load_routes() or {}
        value = copy.deepcopy(snapshot.get("session_notifications", {"version": 1, "outage": None, "issues": {}}))
        if (not isinstance(value, dict) or set(value) != {"version", "outage", "issues"}
                or type(value.get("version")) is not int or value["version"] != 1
                or not isinstance(value.get("issues"), dict) or set(value["issues"]) - ROLES.keys()
                or value.get("outage") is not None and not isinstance(value["outage"], dict)):
            raise ProtocolError("Invalid session notification state")
        outage = value["outage"]
        if outage is not None and (
                not isinstance(outage.get("id"), str) or len(outage["id"]) != 32
                or type(outage.get("since")) not in (int, float) or not math.isfinite(outage["since"])
                or not isinstance(outage.get("roles"), dict) or set(outage["roles"]) - ROLES.keys()
                or any(not isinstance(r, dict) for r in outage["roles"].values())
                or type(outage.get("tasks")) is not bool or type(outage.get("selection_lost")) is not bool
                or not isinstance(outage.get("reason"), str)
                or outage["reason"] not in {"connection_lost", "verification_pending"}
                or not isinstance(outage.get("sent"), list) or len(outage["sent"]) > 2
                or any(not isinstance(r, str) or r not in {"connection_lost", "verification_pending"}
                       for r in outage["sent"])):
            raise ProtocolError("Invalid session outage record")
        if any(not isinstance(issue, dict) or not isinstance(issue.get("reason"), str) or issue["reason"] not in REASONS
               or not isinstance(issue.get("reasons"), list) or len(issue["reasons"]) > len(REASONS)
               or any(not isinstance(r, str) or r not in REASONS for r in issue["reasons"])
               for issue in value["issues"].values()):
            raise ProtocolError("Invalid session selection issue")
        return snapshot, value

    def start_timer(self, outage):
        if self.timer is None or self.timer[0] != outage["id"]:
            self.timer = (outage["id"], self.clock() - max(0, self.wall() - outage["since"]))

    async def select(self, snapshot, roles):
        async with self.lock:
            await self.state.save_routes(snapshot, reset_notice_roles=roles)

    async def begin(self, reason="connection_lost", *, snapshot=None):
        if reason not in {"connection_lost", "verification_pending"}:
            raise ValueError("Explicit session outage reason required")
        async with self.lock:
            saved, value = await self.load()
            snapshot = saved if snapshot is None else snapshot
            roles = {role: {key: snapshot[role].get(key) for key in ("session_id", "project_alias")}
                     for role in ROLES if isinstance(snapshot.get(role), dict)}
            tasks = bool(await self.state.tasks(active_only=True))
            outage = value["outage"]
            previous = copy.deepcopy(outage)
            if outage is None:
                if not roles and not tasks:
                    return
                value["outage"] = {"id": uuid.uuid4().hex, "since": self.wall(), "roles": roles,
                                   "tasks": tasks, "reason": reason, "sent": [], "selection_lost": False}
            else:
                outage["roles"] = {role: record for role, record in outage["roles"].items()
                                   if role in roles and roles[role] == record}
                if not outage["roles"] and not tasks:
                    value["outage"] = None
                    await self.state.save_notice_state(value, close_outage=outage["id"])
                    self.timer = None
                    return
                outage["reason"] = reason
            if value["outage"] != previous:
                await self.state.save_notice_state(value)
            self.start_timer(value["outage"])

    async def tick(self):
        async with self.lock:
            snapshot, value = await self.load()
            outage = value["outage"]
            if outage is None:
                self.timer = None
                return
            self.start_timer(outage)
            if self.clock() - self.timer[1] < self.DELAY or outage["reason"] in outage["sent"]:
                return
            roles = {role: record for role, record in outage["roles"].items()
                     if isinstance(snapshot.get(role), dict)
                     and snapshot[role].get("session_id") == record.get("session_id")}
            tasks = bool(await self.state.tasks(active_only=True))
            if not roles and not tasks:
                return
            verification = outage["reason"] == "verification_pending"
            text = ("**会话恢复核验尚未完成**\n\n尚未完成原会话的准确身份及订阅核验，正在重试。"
                    if verification else "**Codex 连接暂时不可用**\n\n正在自动重连，暂时无法提交新任务或接收相关原生事件。")
            for role, record in roles.items():
                text += f"\n\n{ROLES[role][0]}：{label(record)}。"
            if tasks:
                text += "\n\n已提交任务的执行状态待核验，不会自动重跑；请用 `/status` 查询。"
            else:
                text += "\n\n请等待核验结果；可用 `/status` 查看最后记录。"
            outage["sent"].append(outage["reason"])
            await self.state.save_notice_state(value, [(f"session-outage-{outage['id']}-{outage['reason']}", text)])

    async def restore(self, snapshot, failures):
        async with self.lock:
            _, value = await self.load()
            changed = []
            for role in ROLES:
                if snapshot.get(role) is not None:
                    value["issues"].pop(role, None)
            for role, record, reason in failures:
                issue = {"session_id": record.get("session_id"), "project_alias": record.get("project_alias"),
                         "reason": reason}
                prior = value["issues"].get(role, {})
                seen = prior.get("reasons", []) if all(prior.get(k) == issue[k]
                       for k in ("session_id", "project_alias")) else []
                if reason not in seen:
                    changed.append((role, record, reason))
                issue["reasons"] = list(dict.fromkeys([*seen, reason]))
                value["issues"][role] = issue
            replies = []
            if changed:
                retained = [role for role in ROLES if snapshot.get(role) is not None]
                replies.append(("session-selection-" + uuid.uuid4().hex,
                                selection_text(changed, restored=True, retained=retained)))
            if failures and value["outage"] is not None:
                value["outage"]["selection_lost"] = True
            await self.state.save_routes(snapshot, notice_state=value, replies=replies)

    async def recovered(self):
        async with self.lock:
            snapshot, value = await self.load()
            outage = value["outage"]
            if outage is None:
                return
            replies = []
            matches = all(isinstance(snapshot.get(role), dict)
                          and snapshot[role].get("session_id") == record.get("session_id")
                          for role, record in outage["roles"].items())
            relevant_issue = any(role in value["issues"] for role in outage["roles"])
            if outage["sent"] and not outage["selection_lost"] and matches and not relevant_issue:
                text = "**Codex 连接已恢复**"
                for role, record in outage["roles"].items():
                    text += f"\n\n{ROLES[role][0]}：{label(record)}，已重新核验并恢复。"
                text += "\n\n任务结果继续独立核对，不代表任务已完成，不会自动重跑任务。"
                replies.append(("session-recovered-" + outage["id"], text))
            value["outage"] = None
            await self.state.save_notice_state(value, replies, close_outage=outage["id"])
            self.timer = None
