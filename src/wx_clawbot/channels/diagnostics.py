"""Explicit owner-only challenge/echo, without agent tasks or automatic send retries."""

import asyncio
import hashlib
import re
import time
from pathlib import Path

from .http import ProtocolError, TransportError, WeixinHttp
from .private import load_credentials, private_directory
from .state import ChannelState
from .wechat import BusinessError, DeliveryUnknown, WechatApi


async def echo(root: Path, *, challenge: str, count: int = 2, timeout: float = 180, emit=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", challenge) or not 1 <= count <= 10 or not 1 <= timeout <= 600:
        raise ValueError("Bounded explicit challenge, count and timeout required")
    root = private_directory(root)
    if (root / "runtime.sqlite3").exists():
        raise ProtocolError("Runtime channel has been initialized; diagnostic cursor cannot be reused")
    credentials = load_credentials(root / "credentials.json")
    state = await ChannelState.open(root / "state.sqlite3", credentials)
    http = WeixinHttp()
    api = WechatApi(http)
    report = {"received_new": 0, "duplicates": 0, "rejected": {}, "sent_accepted": 0,
              "context_present": 0, "cursor_advanced": False, "owner_only": True}
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline and report["sent_accepted"] < count:
            cursor = await state.cursor()
            try:
                response = await api.updates(credentials, cursor)
            except TransportError:
                await asyncio.sleep(1)
                continue  # Same confirmed cursor, no task or outbound send is replayed.
            batch = await state.accept_batch(response, phase="diagnostic")
            report["received_new"] += len(batch["accepted"])
            report["duplicates"] += batch["duplicates"]
            report["cursor_advanced"] |= await state.cursor() != cursor
            for reason, value in batch["rejected"].items():
                report["rejected"][reason] = report["rejected"].get(reason, 0) + value
            for incoming in batch["accepted"]:
                # Historical/personal text is not echoed or dispatched to an agent.
                if incoming.text.strip() != challenge:
                    continue
                if not incoming.context_token:
                    report["status"] = "reply_context_missing"
                    return report
                report["context_present"] += 1
                identity = credentials.bot_id + "\0" + incoming.message_id + "\0" + challenge
                client_id = "wx-clawbot-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
                text = "WX-ACK " + challenge + " #" + str(report["sent_accepted"] + 1)
                if not await state.begin_send(client_id, incoming, text):
                    report["status"] = "previous_delivery_requires_reconciliation"
                    return report
                try:
                    result = await api.send_text(credentials, peer=credentials.owner_id, text=text,
                                                 context_token=incoming.context_token, client_id=client_id)
                except DeliveryUnknown:
                    await state.finish_send(client_id, "unknown")
                    report["status"] = "delivery_unknown"
                    return report
                except BusinessError as exc:
                    await state.finish_send(client_id, "rejected")
                    report.update(status="delivery_rejected", error_code=exc.code)
                    return report
                server_id = result.get("message_id")
                await state.finish_send(client_id, "accepted", server_id)
                report["sent_accepted"] += 1
                if emit is not None:
                    emit({"status": "send_accepted", "count": report["sent_accepted"]})
                if report["sent_accepted"] >= count:
                    break
            await asyncio.sleep(.25)
        report["status"] = "server_accepted_test_replies" if report["sent_accepted"] >= count else "waiting_for_challenge"
        # The report deliberately does not claim that the phone displayed the reply.
        return report
    finally:
        await state.close()
        await http.close()
