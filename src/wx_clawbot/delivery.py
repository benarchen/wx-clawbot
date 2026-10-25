"""Delivery consumes durable replies, never invokes or retries native tasks."""

import asyncio

from .channels.wechat import BusinessError, DeliveryUnknown, SessionExpired


class Sender:
    def __init__(self, state, api, *, emit=None):
        self.state, self.api, self.emit = state, api, emit

    async def once(self):
        reply = await self.state.claim_reply()
        if reply is None:
            return False
        credentials = self.state.credentials
        try:
            result = await self.api.send_text(credentials, peer=credentials.owner_id,
                                              text=reply["text"], context_token=reply["context"],
                                              client_id=reply["client_id"])
        except DeliveryUnknown:
            await self.state.finish_reply(reply["id"], "unknown")
            status = "delivery_unknown"
        except BusinessError as exc:
            await self.state.finish_reply(reply["id"], "rejected")
            if isinstance(exc, SessionExpired):
                raise
            status = "delivery_rejected"
        except BaseException:
            # Cancellation or unexpected send failures can occur after bytes were sent.
            await asyncio.shield(self.state.finish_reply(reply["id"], "unknown"))
            raise
        else:
            await self.state.finish_reply(reply["id"], "accepted", result.get("message_id"))
            status = "send_accepted"
        if self.emit:
            self.emit({"status": status})
        return True

    async def run(self):
        while True:
            if not await self.once():
                await asyncio.sleep(.2)
