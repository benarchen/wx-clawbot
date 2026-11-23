"""Stateless protocol normalization, image encoding and model catalog helpers for Antigravity ACP."""

import base64
import os
import shutil
import urllib.parse
from pathlib import Path

from ..config import forbidden


EFFORT_SUFFIXES = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def clean_title(value: object, default: str = "Antigravity 会话") -> str:
    if not isinstance(value, str):
        return default
    cleaned = value.replace("\ufffd", "").strip()
    return (cleaned or default)[:128]


def in_hidden_temp(path: Path, roots: set[Path]) -> bool:
    for root in roots:
        if path.is_relative_to(root):
            rel = path.relative_to(root)
            if any(part == ".tmp" or part.startswith(".tmp-") for part in rel.parts):
                return True
    return False


def discover_agy_executable(explicit: Path | None = None) -> Path | None:
    candidates = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    else:
        found = shutil.which("agy")
        if found:
            candidates.append(Path(found))
        local = Path.home() / ".local" / "bin" / "agy"
        if local not in candidates:
            candidates.append(local)
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def canonicalize_agy_cwd(raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw or "\0" in raw:
        return None
    attempts = [raw]
    if "%" in raw:
        decoded = urllib.parse.unquote(raw)
        if decoded != raw and "\0" not in decoded:
            attempts.append(decoded)
    for candidate in attempts:
        path = Path(candidate)
        if not path.is_absolute():
            continue
        try:
            resolved = path.resolve(strict=True)
        except (OSError, ValueError):
            continue
        if resolved.is_dir() and not forbidden(resolved):
            return resolved
    return None


def encode_image_file(path: Path) -> dict:
    raw = path.read_bytes()
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise ValueError("Unsupported image format; only static PNG/JPEG allowed")
    return {
        "type": "image",
        "data": base64.b64encode(raw).decode("ascii"),
        "mimeType": mime,
    }


def extract_config_map(config_options: list | None) -> dict[str, dict]:
    result = {}
    if not isinstance(config_options, list):
        return result
    for item in config_options:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            result[item["id"]] = item
    return result


def permission_command_summary(params: dict) -> str:
    tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
    title = tool_call.get("title")
    raw_input = tool_call.get("rawInput") if isinstance(tool_call.get("rawInput"), dict) else {}
    cmd = raw_input.get("CommandLine") or raw_input.get("command") or title or tool_call.get("name") or "工具调用"
    return str(cmd).strip()[:512] or "工具调用"


def build_model_catalog(available_models: list[dict], config_options: list[dict]) -> dict[str, dict]:
    cfg = extract_config_map(config_options)
    model_cfg = cfg.get("model") or {}
    options = model_cfg.get("options") if isinstance(model_cfg.get("options"), list) else []
    efforts_by_base: dict[str, list[str]] = {}
    for item in available_models:
        mid = item.get("modelId") if isinstance(item, dict) else None
        if not isinstance(mid, str) or not mid:
            continue
        matched_base = None
        matched_effort = None
        for opt in options:
            base = opt.get("value") if isinstance(opt, dict) else None
            if isinstance(base, str) and mid.startswith(base + "-"):
                suffix = mid[len(base) + 1:]
                if suffix in EFFORT_SUFFIXES:
                    matched_base, matched_effort = base, suffix
                    break
        if matched_base and matched_effort:
            efforts_by_base.setdefault(matched_base, [])
            if matched_effort not in efforts_by_base[matched_base]:
                efforts_by_base[matched_base].append(matched_effort)
    catalog: dict[str, dict] = {}
    for opt in options:
        if not isinstance(opt, dict) or not isinstance(opt.get("value"), str):
            continue
        base = opt["value"]
        display = str(opt.get("name") or base)
        efforts = efforts_by_base.get(base, [])
        catalog[base] = {
            "model": base,
            "display": display,
            "efforts": efforts,
            "default_effort": efforts[0] if efforts else None,
        }
    if not catalog:
        for item in available_models:
            if isinstance(item, dict) and isinstance(item.get("modelId"), str):
                mid = item["modelId"]
                catalog[mid] = {
                    "model": mid,
                    "display": str(item.get("name") or mid),
                    "efforts": [],
                    "default_effort": None,
                }
    return catalog
