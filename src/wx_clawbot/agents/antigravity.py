"""Antigravity (agy) Agent Client Protocol (ACP) backend over stdio JSON-RPC 2.0."""

import asyncio
import copy
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import __version__
from ..config import forbidden
from ..output import RESULT_LIMIT
from .acp_rpc import StdioJsonRpc
from .antigravity_codec import (
    EFFORT_SUFFIXES,
    build_model_catalog,
    canonicalize_agy_cwd,
    clean_title,
    discover_agy_executable,
    encode_image_file,
    extract_config_map,
    in_hidden_temp,
    permission_command_summary,
)
from .base import Capabilities, SubmissionReceipt
from .rpc import ConnectionLost, OutcomeUnknown, RpcError


IDLE_TTL_SECONDS = 24 * 60 * 60

__all__ = [
    "AgySession",
    "AntigravityConnection",
    "EFFORT_SUFFIXES",
    "IDLE_TTL_SECONDS",
    "canonicalize_agy_cwd",
    "discover_agy_executable",
]


@dataclass
class AgySession:
    session_id: str
    cwd: Path
    title: str = "Antigravity 会话"
    loaded: bool = False
    managed: bool = False
    available_models: list[dict] = field(default_factory=list)
    current_model_id: str | None = None
    modes: dict = field(default_factory=dict)
    config_options: list[dict] = field(default_factory=list)
    tier: dict | None = None
    usage: dict | None = None
    active_turn_id: str | None = None
    active_task: asyncio.Task | None = None
    turn_chunks: list[str] = field(default_factory=list)
    turn_chars: int = 0
    last_active_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AntigravityConnection:
    agent_kind = "antigravity"
    capabilities = Capabilities(
        observe=True,
        submit_idle=True,
        queue=False,
        interrupt=True,
        shared_interactions=True,
        image_input=True,
        bridge_queue=True,
        model_control=True,
        external_observe=False,
    )

    def __init__(self, rpc: StdioJsonRpc, *, executable: Path, generation_id: int | None = None,
                 clock=time.monotonic, idle_ttl: float = IDLE_TTL_SECONDS):
        self.rpc = rpc
        self.executable = executable
        self.clock = clock
        self.idle_ttl = idle_ttl
        pid = getattr(rpc.process, "pid", None)
        pid_value = pid if type(pid) is int and pid > 0 else 1
        gen_value = (generation_id if type(generation_id) is int and generation_id > 0
                     else max(1, int(time.time_ns() % (2**31 - 1))))
        self._runtime_identity = (pid_value, gen_value)
        self.server_version = ""
        self.server_info: dict = {}
        self.agent_capabilities: dict = {}
        self._sessions: dict[str, AgySession] = {}
        self._cached_catalog: dict[str, dict] = {}
        self.events: asyncio.Queue[dict] = asyncio.Queue(maxsize=512)
        self.rpc.on_notification = self._handle_notification
        self._pump_task = asyncio.create_task(self._pump())
        self._closed = False

    @property
    def runtime_identity(self) -> tuple[int, int] | None:
        if self._closed or self.rpc.failure is not None:
            return None
        if getattr(self.rpc.process, "returncode", None) is not None:
            self.rpc._fail(ConnectionLost("ACP subprocess exited"))
            return None
        return self._runtime_identity

    def _check_runtime(self) -> None:
        if self.runtime_identity is None:
            raise ConnectionLost("Antigravity ACP runtime is unavailable")

    @classmethod
    async def connect(cls, executable: Path, *, cwd: Path | None = None, spawn=None) -> "AntigravityConnection":
        resolved = discover_agy_executable(executable)
        if resolved is None:
            raise ValueError("Accessible agy executable required")
        launch_cwd = str(cwd) if cwd is not None else str(Path.home())
        if spawn is not None:
            process = await spawn(resolved, launch_cwd)
        else:
            # Security invariant: NEVER pass --dangerously-skip-permissions.
            process = await asyncio.create_subprocess_exec(
                str(resolved),
                "acp",
                "--stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=launch_cwd,
                limit=StdioJsonRpc.MAX_MESSAGE,
            )
        rpc = StdioJsonRpc(process)
        connection = cls(rpc, executable=resolved)
        try:
            result = await rpc.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "wx-clawbot", "version": __version__},
                },
                timeout=20,
            )
            if not isinstance(result, dict) or result.get("protocolVersion") != 1:
                raise ValueError("Unsupported ACP protocol version")
            info = result.get("agentInfo")
            if not isinstance(info, dict) or not isinstance(info.get("version"), str) or not info["version"]:
                raise ValueError("Unsupported Antigravity ACP agentInfo")
            caps = result.get("agentCapabilities")
            if not isinstance(caps, dict):
                raise ValueError("Missing Antigravity ACP agentCapabilities")
            prompt_caps = caps.get("promptCapabilities") if isinstance(caps.get("promptCapabilities"), dict) else {}
            connection.server_version = info["version"]
            connection.server_info = result
            connection.agent_capabilities = caps
            connection.capabilities = replace(
                cls.capabilities,
                image_input=bool(prompt_caps.get("image") is True),
            )
            connection._check_runtime()
            return connection
        except BaseException:
            await connection.close()
            raise

    async def next_event(self, *, timeout: float = 10) -> dict:
        async with asyncio.timeout(timeout):
            while True:
                if self.rpc.failure and self.events.empty():
                    raise self.rpc.failure
                try:
                    return await asyncio.wait_for(self.events.get(), 0.1)
                except TimeoutError:
                    continue

    def _apply_session_payload(self, session: AgySession, payload: dict) -> None:
        models = payload.get("models")
        if isinstance(models, dict):
            if isinstance(models.get("availableModels"), list):
                session.available_models = copy.deepcopy(models["availableModels"])
            if isinstance(models.get("currentModelId"), str):
                session.current_model_id = models["currentModelId"]
        modes = payload.get("modes")
        if isinstance(modes, dict):
            session.modes = copy.deepcopy(modes)
        options = payload.get("configOptions")
        if isinstance(options, list):
            session.config_options = copy.deepcopy(options)
        meta = payload.get("_meta")
        if isinstance(meta, dict):
            agy_meta = meta.get("antigravity")
            if isinstance(agy_meta, dict) and isinstance(agy_meta.get("tier"), dict):
                session.tier = copy.deepcopy(agy_meta["tier"])
        cached = build_model_catalog(session.available_models, session.config_options)
        if cached:
            self._cached_catalog = cached

    def _touch(self, session: AgySession) -> None:
        session.last_active_at = self.clock()

    async def create_session(self, project: Path, *, title: str = "") -> AgySession:
        self._check_runtime()
        cwd = project.resolve(strict=True)
        if not cwd.is_dir() or forbidden(cwd):
            raise ValueError("Existing allowed project directory required")
        result = await self.rpc.request("session/new", {"cwd": str(cwd), "mcpServers": []}, timeout=30)
        self._check_runtime()
        sid = result.get("sessionId") if isinstance(result, dict) else None
        if not isinstance(sid, str) or not 0 < len(sid) <= 256:
            raise ValueError("Invalid Antigravity session identity")
        session = AgySession(
            session_id=sid,
            cwd=cwd,
            title=clean_title(title),
            loaded=True,
            managed=True,
            last_active_at=self.clock(),
        )
        self._apply_session_payload(session, result)
        self._sessions[sid] = session
        return session

    async def resume_session(self, session_id: str, project: Path, *, managed: bool | None = None) -> AgySession:
        self._check_runtime()
        cwd = project.resolve(strict=True)
        if not cwd.is_dir() or forbidden(cwd):
            raise ValueError("Existing allowed project directory required")
        existing = self._sessions.get(session_id)
        if existing is not None and existing.loaded:
            if existing.cwd != cwd:
                raise ValueError("Antigravity session project directory mismatch")
            if managed is not None:
                existing.managed = managed
            self._touch(existing)
            return existing
        result = await self.rpc.request(
            "session/resume",
            {"sessionId": session_id, "cwd": str(cwd), "mcpServers": []},
            timeout=30,
        )
        self._check_runtime()
        returned_id = result.get("sessionId") if isinstance(result, dict) else None
        if returned_id != session_id:
            raise ValueError("Antigravity session identity mismatch on resume")
        title = existing.title if existing else "Antigravity 会话"
        session = existing or AgySession(session_id=session_id, cwd=cwd, title=clean_title(title),
                                         last_active_at=self.clock())
        session.cwd = cwd
        session.loaded = True
        if managed is not None:
            session.managed = managed
        self._touch(session)
        self._apply_session_payload(session, result)
        self._sessions[session_id] = session
        return session

    def list_active_sessions(self, allowed_roots: set[Path]) -> list[dict]:
        """Return only currently loaded active sessions within registered roots."""
        self._check_runtime()
        ordered: list[dict] = []
        for sid, session in self._sessions.items():
            if not session.loaded:
                continue
            if not any(session.cwd.is_relative_to(root) for root in allowed_roots):
                continue
            if in_hidden_temp(session.cwd, allowed_roots):
                continue
            ordered.append(
                self._thread_dict(
                    sid,
                    session.cwd,
                    title=session.title,
                    loaded=True,
                    active=session.active_turn_id is not None,
                )
            )
        return ordered

    async def evict_idle_sessions(self, *, protected_session_ids: set[str] | frozenset[str] = frozenset(),
                                  ttl: float | None = None) -> list[str]:
        """Close unfocused, idle in-memory session handles past TTL; never deletes disk history."""
        if self.runtime_identity is None:
            return []
        limit = self.idle_ttl if ttl is None else ttl
        now = self.clock()
        evicted: list[str] = []
        for sid, session in list(self._sessions.items()):
            if sid in protected_session_ids or session.active_turn_id is not None:
                continue
            if now - session.last_active_at < limit:
                continue
            self._sessions.pop(sid, None)
            evicted.append(sid)
            try:
                await self.rpc.request("session/close", {"sessionId": sid}, timeout=5)
            except Exception:
                pass
        return evicted

    def _thread_dict(self, session_id: str, cwd: Path, *, title: str = "Antigravity 会话",
                     loaded: bool = False, active: bool = False) -> dict:
        return {
            "id": session_id,
            "sessionId": session_id,
            "cwd": str(cwd),
            "name": title[:128],
            "preview": title[:128],
            "status": {"type": "active" if active else ("idle" if loaded else "notLoaded")},
            "canAcceptDirectInput": True,
            "agent": "antigravity",
        }

    async def inspect(self, thread_id: str) -> dict:
        self._check_runtime()
        session = self._sessions.get(thread_id)
        if session is not None:
            return self._thread_dict(
                session.session_id,
                session.cwd,
                title=session.title,
                loaded=session.loaded,
                active=session.active_turn_id is not None,
            )
        raise ValueError("Antigravity session identity not found in active sessions")

    async def is_loaded(self, thread_id: str) -> bool:
        self._check_runtime()
        session = self._sessions.get(thread_id)
        return bool(session is not None and session.loaded)

    async def loaded_threads(self) -> frozenset[str]:
        self._check_runtime()
        return frozenset(sid for sid, s in self._sessions.items() if s.loaded)

    async def observe_loaded(self, thread_id: str, project: Path) -> dict:
        session = await self.resume_session(thread_id, project)
        return self._thread_dict(
            session.session_id,
            session.cwd,
            title=session.title,
            loaded=session.loaded,
            active=session.active_turn_id is not None,
        )

    async def unsubscribe(self, thread_id: str) -> str:
        # Keep the loaded session metadata; do not force-close mid-turn.
        return "unsubscribed"

    def is_busy(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        return bool(session is not None and session.active_turn_id is not None)

    async def submit_idle(
        self,
        thread_id: str,
        project: Path,
        text: str,
        client_submission_id: str,
        *,
        input_items: list[dict] | None = None,
    ) -> SubmissionReceipt:
        self._check_runtime()
        if not isinstance(text, str) or not text.strip() or not isinstance(client_submission_id, str) or not client_submission_id:
            raise ValueError("Nonempty input and stable submission identity required")
        session = await self.resume_session(thread_id, project)
        async with session.lock:
            if session.active_turn_id is not None:
                raise ValueError("Antigravity session is busy; bridge FIFO queue required")
            self._touch(session)
            prompt_blocks = await self._build_prompt_blocks(text, input_items)
            turn_id = "agy-turn-" + uuid.uuid4().hex[:24]
            session.active_turn_id = turn_id
            session.turn_chunks = []
            session.turn_chars = 0
            session.active_task = asyncio.create_task(
                self._run_prompt(session, turn_id, client_submission_id, prompt_blocks)
            )
            return SubmissionReceipt(client_submission_id, turn_id)

    async def _build_prompt_blocks(self, text: str, input_items: list[dict] | None) -> list[dict]:
        if not input_items:
            return [{"type": "text", "text": text}]
        blocks: list[dict] = []
        images = 0
        for item in input_items:
            if not isinstance(item, dict):
                raise ValueError("Invalid input item")
            if item.get("type") == "text":
                t = item.get("text")
                if not isinstance(t, str) or len(t) > 32000:
                    raise ValueError("Invalid bounded text input")
                blocks.append({"type": "text", "text": t})
            elif item.get("type") == "localImage":
                images += 1
                if images > 1:
                    raise ValueError("Only one image per task is supported")
                if not self.capabilities.image_input:
                    raise ValueError("Antigravity runtime does not advertise image input capability")
                raw_path = item.get("path")
                if not isinstance(raw_path, str):
                    raise ValueError("Verified local image path required")
                path = Path(raw_path)
                if not path.is_absolute() or path.is_symlink() or not path.is_file():
                    raise ValueError("Verified local image path required")
                blocks.append(await asyncio.to_thread(encode_image_file, path))
            else:
                raise ValueError("Unsupported input item type")
        if not any(b["type"] == "text" and b["text"].strip() for b in blocks):
            blocks.append({"type": "text", "text": text})
        return blocks

    async def _run_prompt(self, session: AgySession, turn_id: str, client_id: str, prompt_blocks: list[dict]) -> None:
        status = "unknown"
        error_text = None
        usage = None
        stop_reason = None
        try:
            # Long-running prompt: timeout=None so multi-minute agent runs aren't prematurely cut off.
            result = await self.rpc.request(
                "session/prompt",
                {"sessionId": session.session_id, "prompt": prompt_blocks},
                timeout=None,
            )
            stop_reason = result.get("stopReason") if isinstance(result, dict) else None
            usage = result.get("usage") if isinstance(result, dict) else None
            if isinstance(usage, dict):
                session.usage = copy.deepcopy(usage)
            if stop_reason == "cancelled":
                status = "interrupted"
            else:
                status = "completed"
        except RpcError as exc:
            status = "failed"
            error_text = f"ACP 错误（{exc.code}）：{exc}"
        except (ConnectionLost, OutcomeUnknown):
            status = "unknown"
        except asyncio.CancelledError:
            status = "unknown"
            raise
        finally:
            final_text = "".join(session.turn_chunks)
            session.turn_chunks = []
            session.turn_chars = 0
            if session.active_turn_id == turn_id:
                session.active_turn_id = None
                session.active_task = None
            self._touch(session)
            if status in {"completed", "failed", "interrupted"}:
                await self.events.put({
                    "method": "agy/turn/completed",
                    "params": {
                        "threadId": session.session_id,
                        "turnId": turn_id,
                        "clientId": client_id,
                        "status": status,
                        "text": final_text,
                        "error": error_text,
                        "usage": usage,
                        "stopReason": stop_reason,
                    },
                })

    async def cancel_turn(self, session_id: str) -> None:
        self._check_runtime()
        if session_id not in self._sessions:
            raise ValueError("Antigravity session is not active")
        await self.rpc.notify("session/cancel", {"sessionId": session_id})

    def _handle_notification(self, event: dict) -> None:
        """Process server notifications synchronously in stdout wire order."""
        if event.get("method") != "session/update":
            return
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        sid = params.get("sessionId")
        upd = params.get("update") if isinstance(params.get("update"), dict) else {}
        kind = upd.get("sessionUpdate")
        session = self._sessions.get(sid) if isinstance(sid, str) else None
        if session is None:
            return
        if kind == "agent_message_chunk":
            if session.active_turn_id is None:
                return
            content = upd.get("content")
            pieces: list[str] = []
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                pieces.append(content["text"])
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        pieces.append(item["text"])
            for chunk in pieces:
                if chunk and session.turn_chars < RESULT_LIMIT * 2:
                    remaining = RESULT_LIMIT * 2 - session.turn_chars
                    piece = chunk[:remaining]
                    session.turn_chunks.append(piece)
                    session.turn_chars += len(piece)
        elif kind == "session_info_update":
            title = upd.get("title")
            if isinstance(title, str) and title.strip():
                session.title = clean_title(title, default=session.title)
        elif kind == "config_option_update":
            options = upd.get("configOptions")
            if isinstance(options, list):
                session.config_options = copy.deepcopy(options)
                cached = build_model_catalog(session.available_models, session.config_options)
                if cached:
                    self._cached_catalog = cached
        elif kind == "usage_update":
            used = upd.get("used")
            size = upd.get("size")
            if type(used) is int and type(size) is int:
                session.usage = {"used": used, "size": size}

    async def _pump(self) -> None:
        try:
            while True:
                try:
                    event = await self.rpc.next_event(timeout=5)
                except TimeoutError:
                    continue
                try:
                    method = event.get("method")
                    params = event.get("params") if isinstance(event.get("params"), dict) else {}
                    if method == "session/update":
                        self._handle_notification(event)
                    elif method == "session/request_permission" and "id" in event:
                        sid = params.get("sessionId")
                        session = self._sessions.get(sid) if isinstance(sid, str) else None
                        tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
                        item_id = str(tool_call.get("toolCallId") or f"perm-{event['id']}")[:128]
                        turn_id = (session.active_turn_id if session and session.active_turn_id else "agy-turn-pending")
                        normalized = {
                            "id": event["id"],
                            "method": "session/request_permission",
                            "params": {
                                "threadId": sid,
                                "turnId": turn_id,
                                "itemId": item_id,
                                "sessionId": sid,
                                "command": permission_command_summary(params),
                                "toolCall": tool_call,
                                "options": params.get("options") or [],
                            },
                        }
                        await self.events.put(normalized)
                    elif "id" in event:
                        # Unknown server request: refuse explicitly, never auto-approve.
                        await self.rpc.respond_error(event["id"], -32601, "Unsupported ACP client request")
                except (asyncio.CancelledError, ConnectionLost):
                    raise
                except Exception:
                    continue
        except asyncio.CancelledError:
            raise
        except ConnectionLost:
            return

    async def read_settings(self, session_id: str, project: Path) -> dict:
        self._check_runtime()
        session = await self.resume_session(session_id, project)
        self._touch(session)
        cfg = extract_config_map(session.config_options)
        model_opt = cfg.get("model") or {}
        effort_opt = cfg.get("thought_level") or {}
        mode_opt = cfg.get("mode") or {}
        model_value = model_opt.get("currentValue") or session.current_model_id
        effort_value = effort_opt.get("currentValue")
        mode_value = mode_opt.get("currentValue") or (
            session.modes.get("currentModeId") if isinstance(session.modes, dict) else None
        )
        return {
            "model": model_value,
            "reasoningEffort": effort_value,
            "mode": mode_value,
            "tier": copy.deepcopy(session.tier),
            "usage": copy.deepcopy(session.usage),
            "configOptions": copy.deepcopy(session.config_options),
            "availableModels": copy.deepcopy(session.available_models),
        }

    def model_catalog(self, session_id: str | None = None) -> dict[str, dict]:
        self._check_runtime()
        session = self._sessions.get(session_id) if session_id else next(iter(self._sessions.values()), None)
        if session is not None:
            catalog = build_model_catalog(session.available_models, session.config_options)
            if catalog:
                self._cached_catalog = catalog
            return catalog
        if self._cached_catalog:
            return copy.deepcopy(self._cached_catalog)
        raise ValueError("No loaded Antigravity session available to inspect model catalog")

    def resolve_model_request(self, session_id: str, model_name: str, reasoning: str | None = None) -> tuple[str, str | None, dict]:
        catalog = self.model_catalog(session_id)
        target_base = None
        target_effort = reasoning
        if model_name in catalog:
            target_base = model_name
        else:
            for base, entry in catalog.items():
                for eff in entry["efforts"]:
                    if model_name == f"{base}-{eff}":
                        target_base = base
                        if target_effort is None:
                            target_effort = eff
                        break
                if target_base:
                    break
        if target_base is None:
            raise KeyError(model_name)
        entry = catalog[target_base]
        if target_effort is not None and entry["efforts"] and target_effort not in entry["efforts"]:
            raise LookupError(",".join(entry["efforts"]))
        return target_base, target_effort, entry

    async def set_model_and_effort(
        self,
        session_id: str,
        project: Path,
        model_name: str,
        reasoning: str | None = None,
    ) -> dict:
        self._check_runtime()
        session = await self.resume_session(session_id, project)
        if session.active_turn_id is not None:
            raise ValueError("Antigravity session is busy; cannot change model while running")
        self._touch(session)
        target_base, target_effort, entry = self.resolve_model_request(session_id, model_name, reasoning)
        res1 = await self.rpc.request(
            "session/set_config_option",
            {"sessionId": session_id, "configId": "model", "value": target_base},
            timeout=15,
        )
        if isinstance(res1, dict) and isinstance(res1.get("configOptions"), list):
            session.config_options = copy.deepcopy(res1["configOptions"])
        cfg = extract_config_map(session.config_options)
        if (cfg.get("model") or {}).get("currentValue") != target_base:
            raise ValueError("Antigravity model change was not confirmed by server")
        effort_cfg = cfg.get("thought_level") or {}
        valid_efforts = [
            o["value"] for o in (effort_cfg.get("options") or [])
            if isinstance(o, dict) and isinstance(o.get("value"), str)
        ]
        if target_effort is not None:
            if valid_efforts and target_effort not in valid_efforts:
                raise LookupError(",".join(valid_efforts))
            res2 = await self.rpc.request(
                "session/set_config_option",
                {"sessionId": session_id, "configId": "thought_level", "value": target_effort},
                timeout=15,
            )
            if isinstance(res2, dict) and isinstance(res2.get("configOptions"), list):
                session.config_options = copy.deepcopy(res2["configOptions"])
            cfg = extract_config_map(session.config_options)
            if (cfg.get("thought_level") or {}).get("currentValue") != target_effort:
                raise ValueError("Antigravity thinking level change was not confirmed by server")
        else:
            target_effort = (cfg.get("thought_level") or {}).get("currentValue")
        return {
            "model": target_base,
            "display": entry["display"],
            "reasoningEffort": target_effort,
            "mode": (cfg.get("mode") or {}).get("currentValue"),
        }

    async def close(self) -> None:
        self._closed = True
        for session in list(self._sessions.values()):
            if session.active_task is not None and not session.active_task.done():
                session.active_task.cancel()
        tasks = [s.active_task for s in self._sessions.values() if s.active_task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._pump_task.cancel()
        await asyncio.gather(self._pump_task, return_exceptions=True)
        await self.rpc.close()
