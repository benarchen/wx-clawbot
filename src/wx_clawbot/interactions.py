"""Connection-scoped native interactions; the native runtime decides the winner."""

import asyncio
import copy
import math
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .agents.rpc import JsonRpc


APPROVAL = "item/commandExecution/requestApproval"
QUESTION = "item/tool/requestUserInput"


@dataclass
class Interaction:
    public_id: str
    native_id: int | str
    thread_id: str
    turn_id: str
    method: str
    params: dict
    deadline: float
    state: str = "pending"


class InteractionBroker:
    def __init__(self, rpc: JsonRpc, thread_id: str, *, ttl: float = 600,
                 clock: Callable[[], float] = time.monotonic, generation=None, persist=None):
        if not thread_id or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("Thread identity and positive finite lifetime required")
        self.rpc, self.thread_id, self.ttl, self.clock = rpc, thread_id, ttl, clock
        self.generation = generation or uuid.uuid4().hex
        self.persist = persist
        self.records: dict[str, Interaction] = {}
        self.native: dict[tuple[type, int | str], str] = {}
        self.connected = True
        self.lock = asyncio.Lock()

    def register(self, event: dict) -> Interaction:
        if not self.connected:
            raise ValueError("Disconnected interaction generation")
        method, params = event.get("method"), event.get("params")
        if method not in {APPROVAL, QUESTION}:
            raise ValueError("Unsupported native interaction; never auto-approve")
        key = JsonRpc.key(event.get("id"))
        if not isinstance(params, dict) or params.get("threadId") != self.thread_id or any(
            not isinstance(params.get(name), str) or not params[name]
            for name in ("threadId", "turnId", "itemId")
        ):
            raise ValueError("Interaction identity mismatch")
        existing = self.native.get(key)
        if existing:
            record = self.records[existing]
            if record.method != method or record.params != params:
                raise ValueError("Native request ID reused within one connection")
            return record
        if method == APPROVAL:
            if not isinstance(params.get("command"), str) or not params["command"].strip():
                raise ValueError("Approval has no explicit command; cannot approve")
            if params.get("availableDecisions") is not None and not isinstance(params["availableDecisions"], list):
                raise ValueError("Invalid native approval decisions")
        if method == QUESTION:
            questions = params.get("questions")
            if not isinstance(questions, list) or not 1 <= len(questions) <= 20:
                raise ValueError("Invalid native question list")
            ids = []
            for question in questions:
                if not isinstance(question, dict) or not isinstance(question.get("id"), str) or not question["id"]:
                    raise ValueError("Invalid native question identity")
                ids.append(question["id"])
                options = question.get("options")
                if options is not None and (not isinstance(options, list) or any(
                    not isinstance(option, dict) or not isinstance(option.get("label"), str)
                    for option in options
                )):
                    raise ValueError("Invalid native question options")
            if len(set(ids)) != len(ids):
                raise ValueError("Duplicate native question identity")
        # Retain a bounded recent history, without evicting an unanswered request.
        if len(self.records) >= 256:
            for public_id, record in list(self.records.items()):
                if record.state in {"resolved", "stale"}:
                    del self.records[public_id]
                    self.native.pop(JsonRpc.key(record.native_id), None)
                    break
            else:
                raise ValueError("Too many pending native interactions")
        record = Interaction("r-" + uuid.uuid4().hex, event["id"], self.thread_id,
                             params["turnId"], method, copy.deepcopy(params),
                             self.clock() + self.ttl)
        self.records[record.public_id], self.native[key] = record, record.public_id
        return record

    def resolved(self, event: dict) -> Interaction | None:
        params = event.get("params", {})
        if event.get("method") != "serverRequest/resolved" or params.get("threadId") != self.thread_id:
            return None
        public_id = self.native.get(JsonRpc.key(params.get("requestId")))
        if public_id is None:
            return None
        record = self.records[public_id]
        record.state = "resolved"  # The notification does not identify the winning client.
        return record

    @staticmethod
    def _result(record: Interaction, answer: object) -> dict:
        if record.method == APPROVAL:
            # Only one-time actions. Session grants and policy amendments are not accepted.
            if answer not in ("accept", "cancel", "decline"):
                raise ValueError("One-time native approval decision required")
            available = record.params.get("availableDecisions")
            if available is not None and answer not in available:
                raise ValueError("Decision is not offered by the native request")
            return {"decision": answer}
        questions = {q["id"]: q for q in record.params["questions"]}
        if not isinstance(answer, dict) or set(answer) != set(questions):
            raise ValueError("Answer must address exactly the displayed questions")
        result = {}
        for question_id, values in answer.items():
            if not isinstance(values, list) or not 1 <= len(values) <= 2 or any(
                not isinstance(value, str) or not value.strip() or len(value) > 4000
                for value in values
            ):
                raise ValueError("Nonempty bounded question answer required")
            question = questions[question_id]
            labels = {option["label"] for option in question.get("options") or []}
            selected = [value for value in values if value in labels]
            notes = [value for value in values if value not in labels]
            if len(selected) > 1 or len(notes) > 1 or (notes and labels and not question.get("isOther")):
                raise ValueError("Native question permits one choice and optional free text")
            result[question_id] = {"answers": list(values)}
        return {"answers": result}

    async def answer(self, public_id: str, answer: object, *, generation: str,
                     thread_id: str) -> Interaction:
        async with self.lock:
            record = self.records.get(public_id)
            if (not self.connected or generation != self.generation or thread_id != self.thread_id
                    or record is None or record.state != "pending"):
                raise ValueError("Interaction is unavailable or already handled")
            if self.clock() >= record.deadline:
                record.state = "stale"
                await self.sync(record)
                raise ValueError("Interaction has expired; refresh native state")
            result = self._result(record, answer)
            record.state = "sending"
            try:
                await self.sync(record)  # Durable send intent must precede the wire response.
                if record.state != "sending" or not self.connected:
                    raise ValueError("Interaction was handled while persisting the response")
                if self.clock() >= record.deadline:
                    record.state = "stale"
                    await self.sync(record)
                    raise ValueError("Interaction expired while persisting the response")
                await self.rpc.respond(record.native_id, result)
            except BaseException:
                if record.state == "sending":
                    record.state = "unknown"
                    await self.sync(record)
                raise  # Sending may have succeeded; never send an opposite decision.
            if record.state == "sending":
                record.state = "awaiting_native"
            await self.sync(record)
            return record

    async def sync(self, record):
        if self.persist:
            state = await self.persist(record)
            # A native resolution may have arrived during the database await.
            if record.state != "resolved":
                record.state = state

    def disconnect(self) -> None:
        self.connected = False
        for record in self.records.values():
            if record.state not in {"resolved", "stale"}:
                record.state = "stale"
