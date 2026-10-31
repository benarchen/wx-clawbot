"""Validate a one-to-one text message before it can enter routing or execution."""

from dataclasses import dataclass, field
import hashlib
import json

from .wechat import Credentials, normalize_message_id


@dataclass(frozen=True)
class IncomingText:
    message_id: str
    text: str = field(repr=False)
    context_token: str | None = field(repr=False)
    created_ms: int
    sequence: int
    content: tuple[dict, ...] = field(default=(), repr=False)
    error: str | None = None
    body_sha256: str = field(default="", repr=False)


def parse_text(raw: dict, credentials: Credentials) -> tuple[IncomingText | None, str | None]:
    return _parse(raw, credentials, allow_images=False)


def parse_message(raw: dict, credentials: Credentials) -> tuple[IncomingText | None, str | None]:
    return _parse(raw, credentials, allow_images=True)


def _parse(raw: dict, credentials: Credentials, *, allow_images: bool):
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
    native_id = normalize_message_id(raw.get("message_id"))
    if native_id is None:
        return None, "missing_stable_message_id"
    items = raw.get("item_list")
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        return None, "invalid_items"
    texts, content, images, error = [], [], 0, None
    for item in items:
        if not isinstance(item, dict) or type(item.get("type")) is not int:
            return None, "invalid_items"
        if item["type"] != 1:
            if not allow_images:
                return None, "non_text_message"
            if item["type"] != 2:
                error = "unsupported_media"
                continue
            images += 1
            image = item.get("image_item")
            if not isinstance(image, dict) or not isinstance(image.get("media"), dict):
                error = "invalid_image"
                continue
            normalized, media = {}, {}
            for key, limit in (("full_url", 32768), ("encrypt_query_param", 16384), ("aes_key", 128)):
                if key in image["media"]:
                    value = image["media"][key]
                    if not isinstance(value, str) or not value or len(value) > limit:
                        error = "invalid_image"
                    else:
                        media[key] = value
            if "aeskey" in image:
                value = image["aeskey"]
                if not isinstance(value, str) or not value or len(value) > 128:
                    error = "invalid_image"
                else:
                    normalized["aeskey"] = value
            normalized["media"] = media
            content.append({"type": "image", "image": normalized})
            continue
        text_item = item.get("text_item")
        text = text_item.get("text") if isinstance(text_item, dict) else None
        if not isinstance(text, str) or "\0" in text:
            return None, "invalid_text"
        texts.append(text)
        content.append({"type": "text", "text": text})
    text = "\n".join(texts)
    if images > 1:
        error = "multiple_images"
    if (not text.strip() and not images and not error) or len(text) > 16000:
        return None, "invalid_text_length"
    context = raw.get("context_token")
    if context is not None and (not isinstance(context, str) or not context or len(context) > 16384):
        return None, "invalid_context"
    timestamp, sequence = raw.get("create_time_ms", 0), raw.get("seq", 0)
    if (type(timestamp) is not int or not 0 <= timestamp < 2**53
            or type(sequence) is not int or not 0 <= sequence < 2**53):
        return None, "invalid_order_metadata"
    if error:
        digest = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return IncomingText(native_id, "", context, timestamp, sequence, error=error, body_sha256=digest), None
    structured = tuple(content) if images else ()
    digest = hashlib.sha256((json.dumps(content, sort_keys=True, ensure_ascii=False) if images else text).encode()).hexdigest()
    return IncomingText(native_id, text, context, timestamp, sequence, structured, body_sha256=digest), None
