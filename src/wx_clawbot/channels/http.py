"""Bounded HTTPS JSON transport for the documented Weixin bot protocol."""

import asyncio
import base64
import json
import secrets
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .. import __version__


class ChannelError(RuntimeError):
    """Error messages must not include bodies, query strings, or credentials."""


class ProtocolError(ChannelError):
    pass


class TransportError(ChannelError):
    def __init__(self, message, *, category="network"):
        self.category = category
        super().__init__(message)


class HttpStatusError(ChannelError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"Weixin HTTP status {status}")


def api_base(value: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError("Invalid Weixin API base URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ProtocolError("Invalid Weixin API base URL") from None
    if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
            or not parsed.hostname or not parsed.hostname.endswith(".weixin.qq.com")
            or port not in (None, 443) or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ProtocolError("Untrusted Weixin API base URL")
    return "https://" + parsed.hostname + "/"


def encoded_version(version: str) -> str:
    try:
        parts = [int(part) for part in version.split(".")[:3]]
    except (AttributeError, ValueError) as exc:
        raise ValueError("Three numeric version components required") from exc
    if len(parts) != 3 or any(part < 0 or part > 255 for part in parts):
        raise ValueError("Version components must fit uint8")
    return str((parts[0] << 16) | (parts[1] << 8) | parts[2])


def base_info() -> dict:
    return {"channel_version": __version__, "bot_agent": "wx-clawbot/" + __version__}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise ProtocolError("HTTP redirect refused; credentials remain on the verified origin")


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolError("Duplicate JSON key in Weixin response")
        value[key] = item
    return value


class WeixinHttp:
    MAX_RESPONSE = 1024 * 1024

    def __init__(self):
        # A cancelled caller cannot free a lane while its blocking worker is alive.
        self.executors = {name: ThreadPoolExecutor(max_workers=1, thread_name_prefix="wx-" + name)
                          for name in ("auth", "poll", "send")}
        self.slots = {name: asyncio.Semaphore(1) for name in self.executors}
        self.inflight = set()
        self.closed = False

    def _blocking(self, method, url, body, token, timeout):
        headers = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": encoded_version(__version__)}
        data = None
        if method == "POST":
            headers.update({"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
                            "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
            if token:
                if not isinstance(token, str) or any(not 33 <= ord(char) <= 126 for char in token):
                    raise ProtocolError("Invalid bot credential encoding")
                headers["Authorization"] = "Bearer " + token
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            if len(data) > self.MAX_RESPONSE:
                raise ProtocolError("Weixin request exceeds size bound")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(self.MAX_RESPONSE + 1)
                if len(raw) > self.MAX_RESPONSE:
                    raise ProtocolError("Weixin response exceeds size bound")
        except urllib.error.HTTPError as exc:
            exc.close()
            raise HttpStatusError(exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            category = ("tls" if isinstance(reason, ssl.SSLError) else
                        "dns" if isinstance(reason, socket.gaierror) else
                        "timeout" if isinstance(reason, TimeoutError) else "network")
            raise TransportError("Weixin transport outcome requires reconciliation", category=category) from None
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("Invalid JSON number")))
        except (UnicodeError, ValueError):
            raise ProtocolError("Malformed Weixin JSON response") from None
        if not isinstance(value, dict):
            raise ProtocolError("Weixin response must be an object")
        return value

    async def request(self, lane: str, method: str, base: str, endpoint: str, *,
                      body: dict | None = None, token: str | None = None, timeout: float = 15):
        if lane not in self.executors or method not in {"GET", "POST"} or not 0 < timeout <= 40:
            raise ValueError("Valid request lane, method and bounded timeout required")
        if (not endpoint.startswith("ilink/bot/") or "#" in endpoint or "\r" in endpoint or "\n" in endpoint
                or (method == "GET" and (token is not None or body is not None))):
            raise ProtocolError("Invalid Weixin endpoint or authentication shape")
        url = api_base(base) + endpoint
        await self.slots[lane].acquire()
        if self.closed:
            self.slots[lane].release()
            raise ChannelError("Weixin transport is closed")
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self.executors[lane], self._blocking, method, url, body, token, timeout)
        self.inflight.add(future)

        def done(completed):
            self.inflight.discard(completed)
            self.slots[lane].release()
            if not completed.cancelled():
                completed.exception()  # A cancelled caller still has its worker observed.

        future.add_done_callback(done)
        return await asyncio.shield(future)

    async def close(self):
        self.closed = True
        for executor in self.executors.values():
            executor.shutdown(wait=False, cancel_futures=True)
        if self.inflight:
            try:
                async with asyncio.timeout(41):
                    await asyncio.shield(asyncio.gather(*tuple(self.inflight), return_exceptions=True))
            except TimeoutError:
                raise ChannelError("Weixin workers are still draining; shutdown is not confirmed") from None
