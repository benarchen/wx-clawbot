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


def normalize_message_id(value) -> str | None:
    if type(value) is int:
        return str(value) if 0 < value < 2**64 else None
    if (isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 20
            and 0 < int(value) < 2**64):
        return str(int(value))
    return None


def business(response: dict):
    for key in ("ret", "errcode"):
        if key not in response:
            continue
        value = response[key]
        if type(value) is not int:
            raise ProtocolError("Invalid Weixin business return code")
        if value == -14:
            raise SessionExpired(value)
        if value:
            raise BusinessError(value)


def validate_updates(response: dict):
    business(response)
    messages, cursor = response.get("msgs", []), response.get("get_updates_buf")
    if (not isinstance(messages, list) or len(messages) > 1000
            or (cursor is not None and (not isinstance(cursor, str) or len(cursor) > 256000))):
        raise ProtocolError("Invalid Weixin update batch")
    # The observed server omits optional ret on a valid message/cursor envelope.
    # Empty or unrecognized JSON still cannot advance the durable receive state.
    if "ret" not in response and not (isinstance(response.get("msgs"), list) and cursor):
        raise ProtocolError("Weixin response has no recognizable update acknowledgement")


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
        validate_updates(response)
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
        if response.get("ret") != 0 and normalize_message_id(response.get("message_id")) is None:
            raise DeliveryUnknown("Send response has no explicit success acknowledgement")
        return response
