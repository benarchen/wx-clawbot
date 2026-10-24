"""Independent text-only protocol client. No task execution or implicit identity binding."""

import time
import urllib.parse
from dataclasses import dataclass, field

from .http import ChannelError, ProtocolError, WeixinHttp, api_base, base_info


FIXED_BASE = "https://ilinkai.weixin.qq.com"


class BusinessError(ChannelError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Weixin business error {code}")


class SessionExpired(BusinessError):
    pass


class DeliveryUnknown(ChannelError):
    pass


def business(response: dict, *, require_success: bool = False):
    for key in ("ret", "errcode"):
        value = response.get(key)
        if value is not None and type(value) is not int:
            raise ProtocolError("Invalid Weixin business return code")
        if value == -14:
            raise SessionExpired(value)
        if value:
            raise BusinessError(value)
    if require_success and response.get("ret") != 0:
        raise ProtocolError("Weixin response has no explicit success acknowledgement")


def required_text(response, key, limit=4096):
    value = response.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ProtocolError("Required bounded Weixin field is missing")
    return value


@dataclass(frozen=True)
class Credentials:
    bot_id: str
    owner_id: str
    base: str
    token: str = field(repr=False)

    @classmethod
    def from_response(cls, response):
        token = required_text(response, "bot_token")
        if any(not 33 <= ord(char) <= 126 for char in token):
            raise ProtocolError("Invalid bot credential encoding")
        return cls(required_text(response, "ilink_bot_id"), required_text(response, "ilink_user_id"),
                   api_base(required_text(response, "baseurl")), token)


@dataclass
class Login:
    qrcode: str = field(repr=False)
    display_content: str = field(repr=False)
    started_at: float
    polling_base: str = FIXED_BASE


class WechatApi:
    def __init__(self, http: WeixinHttp):
        self.http = http

    async def start_login(self) -> Login:
        # This project has no access to tokens owned by any other client.
        response = await self.http.request("auth", "POST", FIXED_BASE,
                                           "ilink/bot/get_bot_qrcode?bot_type=3", body={"local_token_list": []})
        business(response)
        return Login(required_text(response, "qrcode"), required_text(response, "qrcode_img_content", 16384), time.time())

    async def login_status(self, login: Login, *, verify_code: str | None = None):
        if not 0 <= time.time() - login.started_at < 300:
            return "expired", None
        query = {"qrcode": login.qrcode}
        if verify_code is not None:
            if not isinstance(verify_code, str) or not verify_code.isascii() or not verify_code.isdigit() or not 4 <= len(verify_code) <= 12:
                raise ValueError("Numeric pairing code required")
            query["verify_code"] = verify_code
        response = await self.http.request("auth", "GET", login.polling_base,
                                           "ilink/bot/get_qrcode_status?" + urllib.parse.urlencode(query), timeout=35)
        business(response)
        status = response.get("status")
        if status == "confirmed":
            return status, Credentials.from_response(response)
        if status == "scaned_but_redirect":
            host = required_text(response, "redirect_host")
            login.polling_base = api_base(host if "://" in host else "https://" + host)
        elif status == "binded_redirect":
            # No project-owned token was issued. Do not claim another client's binding.
            raise ChannelError("Existing binding returned without this project's credentials; review binding")
        elif status not in {"wait", "scaned", "expired", "need_verifycode", "verify_code_blocked"}:
            raise ProtocolError("Unknown Weixin login status")
        return status, None

    async def updates(self, credentials: Credentials, cursor: str):
        if not isinstance(cursor, str) or len(cursor) > 256000:
            raise ValueError("Bounded update cursor required")
        response = await self.http.request("poll", "POST", credentials.base, "ilink/bot/getupdates",
                                           body={"get_updates_buf": cursor, "base_info": base_info()},
                                           token=credentials.token, timeout=35)
        business(response, require_success=True)
        if not isinstance(response.get("msgs", []), list) or len(response.get("msgs", [])) > 1000:
            raise ProtocolError("Invalid Weixin message batch")
        next_cursor = response.get("get_updates_buf")
        if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 256000):
            raise ProtocolError("Invalid Weixin update cursor")
        return response

    async def send_text(self, credentials: Credentials, *, peer: str, text: str,
                        context_token: str, client_id: str):
        if peer != credentials.owner_id:
            raise ValueError("Outbound recipient is not the explicitly bound owner")
        for value, limit in ((text, 8000), (context_token, 16384), (client_id, 128)):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError("Bounded text, reply context and stable delivery identity required")
        body = {"msg": {"from_user_id": "", "to_user_id": peer, "client_id": client_id,
                        "message_type": 2, "message_state": 2, "context_token": context_token,
                        "item_list": [{"type": 1, "text_item": {"text": text}}]}, "base_info": base_info()}
        try:
            response = await self.http.request("send", "POST", credentials.base, "ilink/bot/sendmessage",
                                               body=body, token=credentials.token)
        except ChannelError as exc:
            raise DeliveryUnknown("Send outcome unknown; do not automatically resend") from exc
        try:
            business(response)
        except ProtocolError as exc:
            raise DeliveryUnknown("Send acknowledgement is malformed; do not automatically resend") from exc
        if response.get("ret") != 0:
            raise DeliveryUnknown("Send response has no explicit success acknowledgement")
        return response
