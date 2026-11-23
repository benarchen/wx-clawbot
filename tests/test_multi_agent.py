"""Multi-agent routing, independent lifecycles, FIFO queuing, controls and shared occupancy tests."""

import asyncio
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_antigravity_acp import FakeAcpServerProcess, FIXTURE, png_bytes
from test_runtime_state import RuntimeFixture
from test_wechat_state import message

from wx_clawbot.agents.antigravity import AntigravityConnection
from wx_clawbot.agents.base import Capabilities
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.commands import CommandError, parse_command
from wx_clawbot.config import ConfigError, Project, load_config
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution
from wx_clawbot.project_registry import ProjectStore
from wx_clawbot.runtime_lifecycle import UnavailableNative
from wx_clawbot.sessions import SessionBinding


class FakeDirectory:
    async def discover(self):
        return []

    async def validate(self, endpoint):
        return False

    async def cwd(self, endpoint):
        return None


class FakeStarter:
    def __init__(self, root: Path):
        self.calls = []
        self.registry = SimpleNamespace(root=root / "launches")
        self.registry.root.mkdir(parents=True, exist_ok=True)

    async def start(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("Codex iTerm2 starter must never be called for Antigravity")


class FakeCodexAgent:
    agent_kind = "codex"
    server_version = "0.169.0"
    capabilities = Capabilities(observe=True, submit_idle=True, queue=True, interrupt=True,
                                shared_interactions=True, image_input=True, model_control=True, external_observe=True)

    def __init__(self, cwd: Path, *, online=True):
        self.cwd = cwd
        self._online = online
        self.threads = {
            "codex-thread-1": {
                "id": "codex-thread-1",
                "sessionId": "codex-sess-1",
                "cwd": str(cwd),
                "name": "Codex 对话",
                "status": {"type": "idle"},
                "canAcceptDirectInput": True,
            }
        }
        self.rpc = SimpleNamespace(request=self._rpc_request, next_event=self._next_event)

    @property
    def runtime_identity(self):
        return (11, 22) if self._online else None

    async def loaded_threads(self):
        return frozenset(self.threads) if self._online else frozenset()

    async def list_project_threads(self, cwd: Path, cursor=None):
        return {"data": [t for t in self.threads.values() if Path(t["cwd"]) == cwd]}

    async def inspect(self, thread_id: str):
        return self.threads[thread_id]

    async def is_loaded(self, thread_id: str):
        return self._online and thread_id in self.threads

    async def observe_loaded(self, thread_id: str, project: Path):
        return self.threads[thread_id]

    async def unsubscribe(self, thread_id: str):
        return "unsubscribed"

    async def _rpc_request(self, method, params, **kwargs):
        if method == "thread/queue/add":
            return {"id": "q-codex-1"}
        if method == "thread/queue/list":
            return {"data": []}
        return {}

    async def _next_event(self, timeout=1):
        await asyncio.sleep(timeout)
        raise TimeoutError()


class MultiAgentTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = self.root.resolve(strict=True)
        self.proj = self.root / "wx-clawbot"
        self.proj.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.proj, check=True)
        self.fake_bin = self.root / "agy"
        self.fake_bin.write_text("#!/bin/sh\nexit 0\n")
        self.fake_bin.chmod(0o755)
        self.projects = (Project("wx-clawbot", self.proj),)
        self._msg_seq = 0
        self.agy = None
        self.engine_tasks = []

    async def asyncTearDown(self):
        for task in self.engine_tasks:
            task.cancel()
        if self.engine_tasks:
            await asyncio.gather(*self.engine_tasks, return_exceptions=True)
        if self.agy is not None:
            await self.agy.close()
        await super().asyncTearDown()

    async def start_agy(self, *, prompt_hook=None, sessions_list=None):
        counter = {"n": 0}
        state = {"session_new": copy.deepcopy(FIXTURE["session_new_result"]), "model": "gemini-4-neon",
                 "thought_level": "high", "cancel": asyncio.Event()}

        async def handle(proc: FakeAcpServerProcess, msg: dict):
            method = msg.get("method")
            req_id = msg.get("id")
            params = msg.get("params") or {}
            if method is None:
                if prompt_hook is not None:
                    await prompt_hook(proc, msg, state)
                return
            if method == "initialize":
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": copy.deepcopy(FIXTURE["initialize_result"])})
            elif method == "session/new":
                counter["n"] += 1
                res = copy.deepcopy(state["session_new"])
                res["sessionId"] = f"agy-sess-{counter['n']}"
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": res})
            elif method == "session/resume":
                res = copy.deepcopy(state["session_new"])
                res["sessionId"] = params["sessionId"]
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": res})
            elif method == "session/list":
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": {"sessions": list(sessions_list or [])}})
            elif method == "session/set_config_option":
                cid, val = params["configId"], params["value"]
                opts = copy.deepcopy(state["session_new"]["configOptions"])
                if cid == "model":
                    state["model"] = val
                    if val == "gemini-3.8-flash":
                        opts[1]["options"] = [o for o in opts[1]["options"] if o["value"] != "xhigh"]
                elif cid == "thought_level":
                    state["thought_level"] = val
                opts[0]["currentValue"] = state["model"]
                opts[1]["currentValue"] = state["thought_level"]
                state["session_new"]["configOptions"] = opts
                proc.send({"jsonrpc": "2.0", "id": req_id, "result": {"configOptions": opts}})
            elif method == "session/cancel":
                state["cancel"].set()
            elif method == "session/prompt":
                if prompt_hook is not None:
                    await prompt_hook(proc, msg, state)
                else:
                    sid = params["sessionId"]
                    prompt_text = next((b.get("text", "") for b in params["prompt"] if b.get("type") == "text"), "")
                    proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                        "sessionId": sid,
                        "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": f"AGY_REPLY:{prompt_text}"}},
                    }})
                    proc.send({"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "end_turn"}})

        proc = FakeAcpServerProcess(handler=handle)

        async def spawn(_exe, _cwd):
            return proc

        self.agy = await AntigravityConnection.connect(self.fake_bin, cwd=self.proj, spawn=spawn)
        return self.agy, proc, state

    async def send_wx(self, controller: Controller, text: str, *, content=()):
        self._msg_seq += 1
        raw = message(self._msg_seq, text=text, created=self._msg_seq * 100)
        if content:
            raw["item_list"] = list(content)
        batch = await self.state.accept_batch({"ret": 0, "msgs": [raw], "get_updates_buf": f"c-{self._msg_seq}"}, phase="runtime")
        msg = batch["accepted"][0]
        await controller.prepare(msg)
        return str(self._msg_seq)

    async def latest_outbox(self):
        return await self.state._call(lambda: [r[0] for r in self.state.db.execute("SELECT text FROM outbox ORDER BY rowid")])

    def test_command_parsing_for_multi_agent(self):
        self.assertEqual(parse_command("/cd wx-clawbot agy"), parse_command("/cd wx-clawbot antigravity"))
        cd_agy = parse_command("/cd wx-clawbot agy")
        self.assertEqual((cd_agy.name, cd_agy.argument, cd_agy.agent), ("cd", "wx-clawbot", "antigravity"))
        cd_codex = parse_command("/cd wx-clawbot codex")
        self.assertEqual((cd_codex.name, cd_codex.argument, cd_codex.agent), ("cd", "wx-clawbot", "codex"))
        cd_default = parse_command("/cd wx-clawbot")
        self.assertIsNone(cd_default.agent)

        new_agy = parse_command("/new agy 架构讨论")
        self.assertEqual((new_agy.name, new_agy.argument, new_agy.agent), ("new", "架构讨论", "antigravity"))
        new_agy_bare = parse_command("/new agy")
        self.assertEqual((new_agy_bare.name, new_agy_bare.argument, new_agy_bare.agent), ("new", "", "antigravity"))
        new_default = parse_command("/new 普通标题")
        self.assertEqual((new_default.name, new_default.argument, new_default.agent), ("new", "普通标题", None))

        self.assertEqual(parse_command("/agy status").name, "agy")
        self.assertEqual(parse_command("/agent status").name, "agent")
        with self.assertRaises(CommandError):
            parse_command("/agy other")

    def test_config_default_agent_and_project_store_preservation(self):
        cfg_path = self.root / "config.json"
        cfg_path.write_text(json.dumps({
            "version": 1,
            "workspace_root": str(self.root),
            "revision": 1,
            "default_agent": "agy",
            "projects": [{"alias": "wx-clawbot", "root": str(self.proj)}],
            "operations": [],
        }))
        cfg_path.chmod(0o600)
        cfg = load_config(cfg_path)
        self.assertEqual(cfg.default_agent, "antigravity")
        self.assertTrue(cfg.has_default_agent)

        # ProjectStore preserves default_agent on commit
        proj2 = self.root / "proj-two"
        proj2.mkdir()
        store = ProjectStore(cfg_path, self.root)
        _, payload = store.plan("add", name="proj-two", request="req-add-1")
        self.assertEqual(payload["default_agent"], "antigravity")
        committed = store.commit(payload)
        self.assertEqual(committed.default_agent, "antigravity")

        # Invalid default_agent rejected
        bad_path = self.root / "bad-config.json"
        bad_path.write_text(json.dumps({"projects": [{"alias": "wx-clawbot", "root": str(self.proj)}], "default_agent": "invalid"}))
        with self.assertRaises(ConfigError):
            load_config(bad_path)

    async def test_cd_agy_without_iterm_and_works_when_codex_offline(self):
        agy, _, _ = await self.start_agy()
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), UnavailableNative(), extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root)
        controller.native_ready = False
        controller.agy_ready = True
        controller.agy_generation = 1
        engine = Execution(controller)
        self.engine_tasks = [asyncio.create_task(engine.run()), asyncio.create_task(engine.maintain())]

        # /cd wx-clawbot agy works even though Codex is offline and never touches iTerm2
        await self.send_wx(controller, "/cd wx-clawbot agy")
        self.assertEqual(starter.calls, [])
        self.assertIsNotNone(controller.routes.target)
        self.assertEqual(controller.routes.target.agent, "antigravity")
        first_sid = controller.routes.target.session_id

        # Second /cd wx-clawbot agy reuses the same managed session
        await self.send_wx(controller, "/cd wx-clawbot agy")
        self.assertEqual(controller.routes.target.session_id, first_sid)

        # /sessions lists it with 〔agy〕 badge
        await self.send_wx(controller, "/sessions")
        texts = await self.latest_outbox()
        self.assertTrue(any("〔agy〕" in t for t in texts))

        # /new agy creates a fresh second session
        await self.send_wx(controller, "/new agy 第二会话")
        self.assertNotEqual(controller.routes.target.session_id, first_sid)

        # /attach on Antigravity session is explicitly refused
        await self.send_wx(controller, "/sessions")
        await self.send_wx(controller, "/attach 1")
        self.assertIsNone(controller.routes.observer)

    async def test_default_agent_agy_and_fifo_queue_and_controls(self):
        first_hold = asyncio.Event()
        prompt_order = []

        async def hook(proc, msg, _state):
            params = msg["params"]
            text = next(b["text"] for b in params["prompt"] if b["type"] == "text")
            prompt_order.append(text)
            if text == "FIRST_TASK":
                await first_hold.wait()
            proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": params["sessionId"],
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": f"OUT:{text}"}},
            }})
            proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}})

        agy, _, _ = await self.start_agy(prompt_hook=hook)
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), UnavailableNative(), extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root,
                                default_agent="antigravity")
        controller.native_ready = False
        controller.agy_ready = True
        controller.agy_generation = 1
        engine = Execution(controller)
        self.engine_tasks = [asyncio.create_task(engine.run()), asyncio.create_task(engine.maintain())]

        # default_agent=antigravity means bare /cd wx-clawbot creates an Antigravity session
        await self.send_wx(controller, "/cd wx-clawbot")
        self.assertEqual(controller.routes.target.agent, "antigravity")

        # Controls: /model, /model list, /model set, /agy status, /agent status, /fast refusal, /codex status refusal
        await self.send_wx(controller, "/model list")
        await self.send_wx(controller, "/model set gemini-3.8-flash low")
        await self.send_wx(controller, "/model")
        await self.send_wx(controller, "/agy status")
        await self.send_wx(controller, "/agent status")
        await self.send_wx(controller, "/fast on")
        await self.send_wx(controller, "/codex status")
        texts = await self.latest_outbox()
        self.assertTrue(any("Antigravity 可用模型" in t for t in texts))
        self.assertTrue(any("设置已确认" in t and "gemini-3.8-flash" in t for t in texts))
        self.assertTrue(any("Antigravity 状态" in t and "Google AI Pro" in t for t in texts))
        self.assertTrue(any("不支持 Codex 专属的 /fast" in t for t in texts))
        self.assertTrue(any("请使用 /agy status" in t for t in texts))

        # Submit two tasks back-to-back: 1st runs, 2nd waits in SQLite FIFO, busy /model set rejected
        await self.send_wx(controller, "FIRST_TASK")
        await self.send_wx(controller, "SECOND_TASK")
        await asyncio.sleep(0.1)
        self.assertEqual(prompt_order, ["FIRST_TASK"])
        active = await self.state.tasks(active_only=True)
        self.assertEqual(sorted(t["state"] for t in active), ["received", "running"])

        # Busy /model set must be rejected
        await self.send_wx(controller, "/model set gemini-4-neon high")
        texts = await self.latest_outbox()
        self.assertTrue(any("忙碌或尚有排队任务" in t for t in texts))

        # Release 1st task -> 2nd dispatches automatically via drain_admission
        first_hold.set()
        for _ in range(40):
            if len(await self.state.tasks(active_only=True)) == 0:
                break
            await asyncio.sleep(0.1)
        self.assertEqual(prompt_order, ["FIRST_TASK", "SECOND_TASK"])
        texts = await self.latest_outbox()
        self.assertTrue(any("OUT:FIRST_TASK" in t for t in texts))
        self.assertTrue(any("OUT:SECOND_TASK" in t for t in texts))

    async def test_agy_approval_stop_and_codex_repository_mutex(self):
        perm_replies = []
        perm_done = asyncio.Event()

        async def hook(proc, msg, state):
            if "method" not in msg and msg.get("id") == 99:
                perm_replies.append(msg)
                perm_done.set()
                return
            if msg.get("method") == "session/prompt":
                req = copy.deepcopy(FIXTURE["permission_request"])
                req["params"]["sessionId"] = msg["params"]["sessionId"]
                proc.send(req)
                await perm_done.wait()
                proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                    "sessionId": msg["params"]["sessionId"],
                    "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "APPROVED_OK"}},
                }})
                proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}})

        agy, _, _ = await self.start_agy(prompt_hook=hook)
        codex = FakeCodexAgent(self.proj, online=True)
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), codex, extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root)
        controller.native_ready = True
        controller.native_generation = 1
        controller.agy_ready = True
        controller.agy_generation = 1
        engine = Execution(controller)
        self.engine_tasks = [asyncio.create_task(engine.run()), asyncio.create_task(engine.maintain())]

        # Start Antigravity task that requests permission
        await self.send_wx(controller, "/cd wx-clawbot agy")
        await self.send_wx(controller, "RUN_WITH_PERM")
        for _ in range(30):
            if any(engine.brokers.values()):
                break
            await asyncio.sleep(0.05)
        broker = next(iter(engine.brokers.values()))
        pub_id = next(iter(broker.records))

        # Meanwhile, focus Codex session on the SAME repo and submit a task -> MUST block in received!
        await self.send_wx(controller, "/sessions")
        codex_idx = next(i for i, t in enumerate(controller.routes.list.targets, 1) if t.agent == "codex")
        await self.send_wx(controller, f"/focus {codex_idx}")
        await self.send_wx(controller, "CODEX_SAME_REPO_TASK")
        active = await self.state.tasks(active_only=True)
        codex_task = next(t for t in active if t["target"].get("agent", "codex") == "codex")
        self.assertEqual(codex_task["state"], "received")

        # Cancel the queued Codex task cleanly via /stop
        await self.send_wx(controller, f"/stop {codex_task['id']}")
        self.assertEqual((await self.state.tasks(task_id=codex_task["id"]))["state"], "cancelled")

        # Approve the Antigravity permission via /approve
        await self.send_wx(controller, f"/approve {pub_id}")
        for _ in range(30):
            if len(await self.state.tasks(active_only=True)) == 0:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(perm_replies[0]["result"], {"outcome": {"outcome": "selected", "optionId": "allow_once_id"}})
        texts = await self.latest_outbox()
        self.assertTrue(any("APPROVED_OK" in t for t in texts))

    async def test_agent_scoped_disconnect_and_agy_route_restore(self):
        agy, _, _ = await self.start_agy(sessions_list=[
            {"sessionId": "agy-sess-1", "cwd": str(self.proj), "title": "持久对话"},
        ])
        codex = FakeCodexAgent(self.proj, online=True)
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), codex, extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root)
        controller.native_ready = True
        controller.agy_ready = True
        controller.agy_generation = 1
        Execution(controller)

        # Create & focus agy session -> persists route snapshot
        await self.send_wx(controller, "/cd wx-clawbot agy")
        saved_sid = controller.routes.target.session_id

        # Simulate two running tasks: one codex, one agy
        t_codex = await self.state.task_intent(
            await self._insert_inbox("codex-run"),
            {"session_id": "s-c", "project_alias": "wx-clawbot", "cwd": str(self.proj), "origin": "original",
             "thread_id": "codex-thread-1", "native_session_id": "codex-sess-1", "runtime_identity": [11, 22]},
            "codex work",
        )
        await self.state.task_update(t_codex["id"], "running", turn_id="ct-1")
        t_agy = await self.state.task_intent(
            await self._insert_inbox("agy-run"),
            {"session_id": saved_sid, "project_alias": "wx-clawbot", "cwd": str(self.proj), "origin": "managed",
             "agent": "antigravity", "thread_id": "agy-sess-1", "native_session_id": "agy-sess-1", "runtime_identity": [42, 1]},
            "agy work",
        )
        await self.state.task_update(t_agy["id"], "running", turn_id="at-1")

        # Disconnecting Antigravity marks ONLY Antigravity task unknown; Codex stays running!
        await self.state.native_disconnected(agent="antigravity")
        self.assertEqual((await self.state.tasks(task_id=t_agy["id"]))["state"], "unknown")
        self.assertEqual((await self.state.tasks(task_id=t_codex["id"]))["state"], "running")

        # Restore route with a NEW Antigravity runtime_identity and EMPTY in-memory _sessions -> resumes cleanly!
        agy._sessions.clear()
        agy._runtime_identity = (99999, 88888)
        catalog2 = SessionCatalog(self.projects, FakeDirectory(), codex, extra_agents={"antigravity": agy})
        controller2 = Controller(self.projects, catalog2, self.state, starter, self.fake_bin, self.root)
        controller2.native_ready = True
        controller2.agy_ready = True
        await controller2.restore()
        self.assertIsNotNone(controller2.routes.target)
        self.assertEqual(controller2.routes.target.session_id, saved_sid)
        self.assertEqual(controller2.routes.target.agent, "antigravity")

        # Cold-start race: Codex restore() runs BEFORE agy connects, then watch_agy connects and calls restore_agy_target()
        agy._sessions.clear()
        agy._runtime_identity = (77777, 66666)
        catalog3 = SessionCatalog(self.projects, FakeDirectory(), codex, extra_agents={})
        controller3 = Controller(self.projects, catalog3, self.state, starter, self.fake_bin, self.root)
        controller3.native_ready = True
        controller3.agy_ready = False
        await controller3.restore()
        self.assertIsNone(controller3.routes.target)
        self.assertIsNotNone(controller3.unrestored_selection)
        # Now agy finishes connecting after Codex
        catalog3.extra_agents["antigravity"] = agy
        controller3.agy_ready = True
        restored = await controller3.restore_agy_target()
        self.assertTrue(restored)
        self.assertIsNotNone(controller3.routes.target)
        self.assertEqual(controller3.routes.target.session_id, saved_sid)
        self.assertIsNone(controller3.unrestored_selection)

    async def test_codex_idle_check_inspects_coexisting_agy_via_agy_backend(self):
        agy, _, _ = await self.start_agy()
        codex = FakeCodexAgent(self.proj, online=True)
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), codex, extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root)
        controller.native_ready = True
        controller.agy_ready = True
        controller.agy_generation = 1
        engine = Execution(controller)

        # Create active agy session in same project, then focus Codex session
        await self.send_wx(controller, "/cd wx-clawbot agy")
        sessions = await catalog.discover()
        codex_session = next(s for s in sessions if s.target.agent == "codex")
        # idle() must inspect the co-existing agy session via agy backend (not codex.inspect!)
        await engine.native_controls.idle(codex_session.target, codex_session)
        # When agy session is active, idle() must reject Codex setting change
        agy._sessions["agy-sess-1"].active_turn_id = "agy-turn-busy"
        with self.assertRaises(CommandError):
            await engine.native_controls.idle(codex_session.target, codex_session)
        agy._sessions["agy-sess-1"].active_turn_id = None

    async def test_model_list_follows_focused_agy_and_sessions_active_only_and_handoff_hint(self):
        # Populate 5 historical disk sessions to prove /sessions does NOT dump them
        history = [{"sessionId": f"hist-{i}", "cwd": str(self.proj), "title": f"历史 {i}"} for i in range(5)]
        agy, _, _ = await self.start_agy(sessions_list=history)
        codex = FakeCodexAgent(self.proj, online=True)
        # Teach fake codex to respond to model/list so we can verify Codex vs Antigravity routing!
        orig_req = codex._rpc_request

        async def codex_req(method, params, **kwargs):
            if method == "model/list":
                return {"data": [{"model": "codex-fixture-model", "displayName": "Codex Model",
                                  "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                                  "defaultReasoningEffort": "high"}]}
            return await orig_req(method, params, **kwargs)

        codex.rpc.request = codex_req
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), codex, extra_agents={"antigravity": agy})
        # default_agent stays "codex"
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root,
                                default_agent="codex")
        controller.native_ready = True
        controller.native_generation = 1
        controller.agy_ready = True
        controller.agy_generation = 1
        Execution(controller)

        # 1. /cd wx-clawbot agy shows copyable fenced code block `agy --conversation agy-sess-1`
        await self.send_wx(controller, "/cd wx-clawbot agy")
        texts = await self.latest_outbox()
        self.assertIn("```sh\nagy --conversation agy-sess-1\n```", texts[-1])

        # 2. While focused on agy (even with default_agent="codex"), /model list returns Antigravity models!
        await self.send_wx(controller, "/model list")
        texts = await self.latest_outbox()
        self.assertIn("Antigravity 可用模型", texts[-1])
        self.assertNotIn("codex-fixture-model", texts[-1])

        # 3. Explicit /model list codex still returns Codex models
        await self.send_wx(controller, "/model list codex")
        texts = await self.latest_outbox()
        self.assertIn("codex-fixture-model", texts[-1])

        # 4. /agy status includes copyable fenced desktop handoff command
        await self.send_wx(controller, "/agy status")
        texts = await self.latest_outbox()
        self.assertIn("```sh\nagy --conversation agy-sess-1\n```", texts[-1])

        # 5. /sessions lists ONLY active sessions (1 codex + 1 agy) with explicit agent labels, NOT 5 historical ones
        await self.send_wx(controller, "/sessions")
        texts = await self.latest_outbox()
        self.assertIn("会话列表 · 2 个", texts[-1])
        self.assertIn("〔agy〕", texts[-1])
        self.assertIn("〔codex〕", texts[-1])
        self.assertNotIn("历史 0", texts[-1])

        # 6. /unfocus then /model list agy still works via cached catalog
        await self.send_wx(controller, "/unfocus")
        await self.send_wx(controller, "/model list agy")
        texts = await self.latest_outbox()
        self.assertIn("Antigravity 可用模型", texts[-1])

    async def test_agy_stop_interrupts_active_turn(self):
        async def hook(proc, msg, state):
            await state["cancel"].wait()
            proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "cancelled"}})

        agy, _, _ = await self.start_agy(prompt_hook=hook)
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), UnavailableNative(), extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root)
        controller.native_ready = False
        controller.agy_ready = True
        controller.agy_generation = 1
        engine = Execution(controller)
        self.engine_tasks = [asyncio.create_task(engine.run()), asyncio.create_task(engine.maintain())]

        await self.send_wx(controller, "/cd wx-clawbot agy")
        await self.send_wx(controller, "LONG_RUNNING_AGY_TASK")
        await asyncio.sleep(0.1)
        active = await self.state.tasks(active_only=True)
        self.assertEqual(len(active), 1)
        task_id = active[0]["id"]
        await self.send_wx(controller, "/stop")
        for _ in range(30):
            current = await self.state.tasks(task_id=task_id)
            if current["state"] == "interrupted":
                break
            await asyncio.sleep(0.05)
        self.assertEqual((await self.state.tasks(task_id=task_id))["state"], "interrupted")

    async def test_agy_wechat_single_image_end_to_end_pipeline(self):
        from unittest.mock import patch
        from test_antigravity_acp import png_bytes
        seen_blocks = []

        async def hook(proc, msg, _state):
            seen_blocks.append(msg["params"]["prompt"])
            proc.send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": msg["params"]["sessionId"],
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "IMAGE_E2E_OK"}},
            }})
            proc.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}})

        agy, _, _ = await self.start_agy(prompt_hook=hook)
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), UnavailableNative(), extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root)
        controller.native_ready = False
        controller.agy_ready = True
        controller.agy_generation = 1
        engine = Execution(controller)
        raw_png = png_bytes()
        import hashlib
        meta = {"format": "PNG", "byte_size": len(raw_png), "sha256": hashlib.sha256(raw_png).hexdigest(), "width": 1, "height": 1}
        with patch("wx_clawbot.images.download_image", return_value=(raw_png, meta)):
            self.engine_tasks = [asyncio.create_task(engine.run()), asyncio.create_task(engine.maintain())]
            await self.send_wx(controller, "/cd wx-clawbot agy")
            await self.send_wx(
                controller,
                "",
                content=[{"type": 2, "image_item": {"media": {"encrypt_query_param": "p", "aes_key": "00" * 16}, "mid_size": len(raw_png)}}],
            )
            texts = await self.latest_outbox()
            self.assertTrue(any("尚未进入桥接队列" in t for t in texts))
            for _ in range(60):
                texts = await self.latest_outbox()
                if any("IMAGE_E2E_OK" in t for t in texts):
                    break
                await asyncio.sleep(0.05)
            self.assertTrue(any("IMAGE_E2E_OK" in t for t in texts))
            self.assertTrue(any(b.get("type") == "image" and b.get("mimeType") == "image/png" for b in seen_blocks[0]))

    async def test_agy_model_set_uses_control_journal_for_idempotency_and_partial_write_unknown(self):
        set_calls = []
        fail_thought = False
        agy, proc, _ = await self.start_agy()
        orig_req = agy.rpc.request

        async def spy_request(method, params=None, **kwargs):
            if method == "session/set_config_option":
                set_calls.append((params.get("configId"), params.get("value")))
                if fail_thought and params.get("configId") == "thought_level":
                    raise RuntimeError("boom")
            return await orig_req(method, params, **kwargs)

        agy.rpc.request = spy_request
        starter = FakeStarter(self.root)
        catalog = SessionCatalog(self.projects, FakeDirectory(), UnavailableNative(), extra_agents={"antigravity": agy})
        controller = Controller(self.projects, catalog, self.state, starter, self.fake_bin, self.root)
        controller.native_ready = False
        controller.agy_ready = True
        controller.agy_generation = 1
        engine = Execution(controller)

        await self.send_wx(controller, "/cd wx-clawbot agy")
        target = controller.routes.target
        rev = controller.routes.revision

        # 1. First write succeeds and journals confirmed reply
        cmd = parse_command("/model set gemini-3.8-flash low")
        r1 = await engine.native_controls.execute(cmd, target, rev, message_id="wx-agy-set-1")
        self.assertIn("设置已确认", r1)
        count_after_first = len(set_calls)
        self.assertEqual(count_after_first, 2)

        # 2. Replay same message_id returns frozen reply WITHOUT sending any new RPC
        r2 = await engine.native_controls.execute(cmd, target, rev, message_id="wx-agy-set-1")
        self.assertEqual(r2, r1)
        self.assertEqual(len(set_calls), count_after_first)

        # 3. Same message_id with different setting is rejected
        with self.assertRaises(CommandError):
            await engine.native_controls.execute(parse_command("/model set gemini-4-neon high"), target, rev, message_id="wx-agy-set-1")

        # 4. Same setting with new message_id records unchanged without RPC
        r_same = await engine.native_controls.execute(cmd, target, rev, message_id="wx-agy-set-2")
        self.assertIn("当前已是该设置，无变更", r_same)
        self.assertEqual(len(set_calls), count_after_first)

        # 5. Failure on second RPC (thought_level) records unknown and never replays
        from wx_clawbot.agents.rpc import RpcError
        async def fail_second(method, params=None, **kwargs):
            if method == "session/set_config_option" and params.get("configId") == "thought_level":
                raise RpcError(-32000, "partial failure")
            return await orig_req(method, params, **kwargs)
        agy.rpc.request = fail_second
        r_unk = await engine.native_controls.execute(parse_command("/model set gemini-4-neon high"), target, rev, message_id="wx-agy-set-3")
        self.assertIn("设置结果待核对", r_unk)
        record = engine.native_controls.journal().read("wx-agy-set-3")
        self.assertEqual(record["phase"], "unknown")

    async def test_watch_agy_crash_cleans_catalog_and_brokers_and_reconnect_restores_focus(self):
        from unittest.mock import patch
        from wx_clawbot.hosts.lifecycle import HostLifecycle
        from wx_clawbot.interactions import ACP_APPROVAL, InteractionBroker
        from wx_clawbot.runtime_lifecycle import BridgeRuntime

        orig_connect = AntigravityConnection.connect
        procs = []
        connect_calls = 0

        async def fake_connect(_exe):
            nonlocal connect_calls
            connect_calls += 1

            async def handle(proc, msg):
                method, req_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
                if method == "initialize":
                    proc.send({"jsonrpc": "2.0", "id": req_id, "result": copy.deepcopy(FIXTURE["initialize_result"])})
                elif method in {"session/new", "session/resume"}:
                    res = copy.deepcopy(FIXTURE["session_new_result"])
                    res["sessionId"] = params.get("sessionId") or "agy-sess-1"
                    proc.send({"jsonrpc": "2.0", "id": req_id, "result": res})

            proc = FakeAcpServerProcess(handler=handle)

            async def spawn(_e, _c):
                return proc

            agy = await orig_connect(self.fake_bin, cwd=self.proj, spawn=spawn)
            procs.append((agy, proc))
            return agy

        host = HostLifecycle()
        runtime = BridgeRuntime(self.projects, self.state, FakeStarter(self.root), host,
                                None, None, None, agy_executable=self.fake_bin, default_agent="antigravity")
        with patch("wx_clawbot.runtime_lifecycle.AntigravityConnection.connect", side_effect=fake_connect):
            watch_task = asyncio.create_task(runtime.watch_agy())
            run_task = asyncio.create_task(runtime.run())
            try:
                for _ in range(40):
                    if runtime.agy_state == "ready":
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(runtime.agy_state, "ready")
                self.assertEqual(runtime.native_state, "unavailable")

                # Focus an agy session and register an ACP approval broker
                await self.send_wx(runtime.controller, "/cd wx-clawbot agy")
                saved_sid = runtime.controller.routes.target.session_id
                broker = InteractionBroker(procs[0][0].rpc, "agy-sess-1")
                broker.register({
                    "id": 9, "method": ACP_APPROVAL,
                    "params": {"threadId": "agy-sess-1", "turnId": "t1", "itemId": "i1",
                               "command": "echo hi", "options": [{"optionId": "a", "kind": "allow_once"}]},
                })
                runtime.controller.engine.brokers["agy-sess-1"] = broker
                self.assertTrue(any(s.target.agent == "antigravity" for s in runtime.controller.catalog.sessions.values()))

                # Simulate ACP subprocess crash!
                procs[0][1].crash()
                for _ in range(40):
                    if not broker.connected and runtime.agy_state == "unavailable":
                        break
                    await asyncio.sleep(0.05)
                self.assertFalse(broker.connected)
                self.assertFalse(any(s.target.agent == "antigravity" for s in runtime.controller.catalog.sessions.values()))

                # Clear target to verify reconnect triggers restore_agy_target() cleanly
                runtime.controller.routes.target = None
                for _ in range(60):
                    if connect_calls >= 2 and runtime.agy_state == "ready" and runtime.controller.routes.target is not None:
                        break
                    await asyncio.sleep(0.05)
                self.assertGreaterEqual(connect_calls, 2)
                self.assertIsNotNone(runtime.controller.routes.target)
                self.assertEqual(runtime.controller.routes.target.session_id, saved_sid)
            finally:
                watch_task.cancel()
                run_task.cancel()
                await asyncio.gather(watch_task, run_task, return_exceptions=True)
                await runtime._stop_agy_engine()
                for agy_conn, _ in procs:
                    await agy_conn.close()

    async def _insert_inbox(self, tag: str) -> str:
        self._msg_seq += 1
        raw = message(self._msg_seq, text=tag, created=self._msg_seq * 100)
        await self.state.accept_batch({"ret": 0, "msgs": [raw], "get_updates_buf": f"c-{self._msg_seq}"}, phase="runtime")
        return str(self._msg_seq)
