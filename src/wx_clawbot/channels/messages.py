"""Validate a one-to-one text message before it can enter routing or execution."""

from dataclasses import dataclass, field

from .wechat import Credentials


@dataclass(frozen=True)
class IncomingText:
    message_id: str
    text: str = field(repr=False)
    context_token: str | None = field(repr=False)
    created_ms: int
    sequence: int


def parse_text(raw: dict, credentials: Credentials) -> tuple[IncomingText | None, str | None]:
    if not isinstance(raw, dict):
        return None, "invalid_message"
    if raw.get("from_user_id") != credentials.owner_id:
        return None, "unknown_sender"
    if raw.get("to_user_id") != credentials.bot_id:
        return None, "wrong_recipient"
    if raw.get("group_id"):
        return None, "group_not_supported"
    if type(raw.get("message_type")) is not int or raw["message_type"] != 1:
        return None, "non_user_message"
    if type(raw.get("message_state")) is not int or raw["message_state"] != 2:
        return None, "unfinished_message"
    native_id = raw.get("message_id")
    if type(native_id) is int:
        valid_id = 0 < native_id < 2**64
    else:
        valid_id = isinstance(native_id, str) and native_id.isascii() and native_id.isdigit() and len(native_id) <= 20
        if valid_id:
            valid_id = 0 < int(native_id) < 2**64
    if not valid_id:
        return None, "missing_stable_message_id"
    items = raw.get("item_list")
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        return None, "invalid_items"
    texts = []
    for item in items:
        if not isinstance(item, dict) or type(item.get("type")) is not int or item["type"] != 1:
            return None, "non_text_message"
        text_item = item.get("text_item")
        text = text_item.get("text") if isinstance(text_item, dict) else None
        if not isinstance(text, str):
            return None, "invalid_text"
        texts.append(text)
    text = "\n".join(texts)
    if not text.strip() or len(text) > 16000:
        return None, "invalid_text_length"
    context = raw.get("context_token")
    if context is not None and (not isinstance(context, str) or not context or len(context) > 16384):
        return None, "invalid_context"
    timestamp, sequence = raw.get("create_time_ms", 0), raw.get("seq", 0)
    if (type(timestamp) is not int or not 0 <= timestamp < 2**53
            or type(sequence) is not int or not 0 <= sequence < 2**53):
        return None, "invalid_order_metadata"
    return IncomingText(str(int(native_id)), text, context, timestamp, sequence), None
