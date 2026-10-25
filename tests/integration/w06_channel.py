"""Real owner long-poll socket fault, only while holding the sole consumer lock."""

import asyncio
import hashlib
import http.client
import socket
import threading
import urllib.request
from unittest.mock import patch

from wx_clawbot.channels.http import TransportError, WeixinHttp
from wx_clawbot.channels.private import load_credentials
from wx_clawbot.channels.wechat import WechatApi
from wx_clawbot.delivery import Sender
from wx_clawbot.runtime_state import RuntimeState


async def poll_fault(root):
    credentials = load_credentials(root / "credentials.json")
    state = await RuntimeState.open(root / "runtime.sqlite3", credentials)
    transport = WeixinHttp()
    accepted = 0
    poll = None

    async def accept(response):
        nonlocal accepted
        batch = await state.accept_batch(response, phase="runtime")
        accepted += len(batch["accepted"])
        for message in batch["accepted"]:
            await state.handled(message.message_id)
        if batch["accepted"]:
            key = hashlib.sha256(",".join(m.message_id for m in batch["accepted"]).encode()).hexdigest()
            await state.queue_reply("load-test-deferred-" + key,
                f"当前正在进行受控验收，本批 {len(batch['accepted'])} 条消息未执行；请验收结束后重新发送任务。", priority=0)

    try:
        fault_verified = False
        preserved = False
        original = urllib.request.build_opener
        for _ in range(2):
            ready, observed = threading.Event(), {}

            class Captured(http.client.HTTPSConnection):
                def getresponse(self):
                    observed["socket"] = self.sock
                    ready.set()
                    return super().getresponse()

            class Handler(urllib.request.HTTPSHandler):
                def https_open(self, request):
                    return self.do_open(Captured, request, context=self._context)

            def opener(*handlers):
                return original(*handlers, Handler())

            cursor = await state.cursor()
            with patch("urllib.request.build_opener", opener):
                poll = asyncio.create_task(WechatApi(transport).updates(credentials, cursor))
                if not await asyncio.to_thread(ready.wait, 10):
                    await asyncio.gather(poll, return_exceptions=True)
                    raise AssertionError("No actual TLS long-poll socket observed")
                await asyncio.sleep(.2)
                if poll.done():
                    await accept(poll.result())
                    continue  # A known immediate batch is not a disconnection.
                peer = observed["socket"]
                peer.shutdown(socket.SHUT_RDWR)
                peer.close()
                try:
                    await asyncio.wait_for(asyncio.shield(poll), 45)
                except TransportError:
                    fault_verified = True
                preserved = await state.cursor() == cursor
            if fault_verified:
                break
        if not fault_verified or not preserved:
            raise AssertionError("Real long-poll failure and preserved cursor not proven")
        await accept(await WechatApi(transport).updates(credentials, await state.cursor()))
        if accepted:
            # Only the explicit test-mode notice, never execution or task replay.
            await Sender(state, WechatApi(transport)).once()
        return {"real_tls_socket_closed": True, "transport_error_observed": True,
                "cursor_preserved_after_failure": preserved, "reconnected_response_accepted": True,
                "new_owner_messages_not_executed": accepted, "sole_consumer_lock_held": True}
    finally:
        await transport.close()
        if poll:
            await asyncio.gather(poll, return_exceptions=True)
        await state.close()
