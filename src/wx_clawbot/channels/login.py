"""Foreground, project-owned login and explicit owner confirmation."""

import hashlib
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from .http import ChannelError, ProtocolError, TransportError, WeixinHttp
from .private import load_credentials, private_directory, private_lease, read_json, save_credentials, write_json
from .wechat import Login, WechatApi


def owner_fingerprint(credentials):
    return hashlib.sha256(credentials.owner_id.encode()).hexdigest()[:16]


def confirm_owner(root: Path, fingerprint: str):
    root = private_directory(root)
    with private_lease(root / "login.lock"):
        credentials = load_credentials(root / "credentials.json", require_confirmed=False)
        if fingerprint != owner_fingerprint(credentials):
            raise ProtocolError("Owner confirmation does not match the scanned account")
        data = read_json(root / "credentials.json")
        data["owner_confirmed"] = True
        data["owner_confirmed_at"] = time.time()
        write_json(root / "credentials.json", data, replace=True)
    return {"status": "owner_confirmed", "owner_fingerprint": fingerprint}


def qr_page(root, attempt, content):
    import segno

    if not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise ProtocolError("Invalid private login attempt identity")
    png = root / ("login-" + attempt + ".png")
    page = root / ("login-" + attempt + ".html")
    qr = segno.make_qr(content, error="m")
    fd = os.open(png, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        qr.save(stream, kind="png", scale=8, border=4)
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'">
<title>wx-clawbot 独立登录</title><style>body{{font-family:system-ui;text-align:center;padding:24px}}img{{image-rendering:pixelated;max-width:90vw}}p{{line-height:1.7}}</style>
<h1>wx-clawbot 独立登录</h1><img src="{png.name}" alt="微信登录二维码">
<p>请使用本人的测试微信扫码，并核对手机上的绑定对象。<br>如果提示替换现有连接，请先停止确认并告知具体提示。<br>扫码后仍需明确确认本人身份，程序才允许测试收发。</p></html>"""
    fd = os.open(page, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(html)
    return png, page


async def login(root: Path, *, wait=300, fresh=False, open_page=False, verify_code=None, emit=print):
    import asyncio
    import json

    root = private_directory(root)
    if not 0 <= wait <= 300:
        raise ValueError("Login wait must be between zero and 300 seconds")
    http = WeixinHttp()
    api = WechatApi(http)
    try:
        with private_lease(root / "login.lock"):
            credential_file = root / "credentials.json"
            if credential_file.exists():
                credentials = load_credentials(credential_file, require_confirmed=False)
                confirmed = read_json(credential_file).get("owner_confirmed") is True
                return {"status": "connected" if confirmed else "awaiting_owner_confirmation",
                        "owner_fingerprint": owner_fingerprint(credentials)}
            record_path = root / "login.json"
            record = read_json(record_path) if record_path.exists() else None
            if record is not None:
                if record.get("phase") in {"starting", "unknown"}:
                    raise ChannelError("Previous QR request outcome unknown; inspect before requesting another")
                if record.get("version") != 1:
                    raise ProtocolError("Unsupported project login record")
                expired = record.get("phase") in {"expired", "verify_code_blocked"} or time.time() - record["started_at"] >= 300
                if fresh and not expired:
                    raise ChannelError("An unexpired login already exists; continue that login")
                if expired and not fresh:
                    return {"status": "expired", "refresh_required": True}
                if fresh:
                    record = None
            if record is None:
                record = {"version": 1, "phase": "starting", "attempt_id": uuid.uuid4().hex,
                          "started_at": time.time()}
                write_json(record_path, record, replace=record_path.exists())
                try:
                    current = await api.start_login()
                except BaseException:
                    record["phase"] = "unknown"
                    write_json(record_path, record, replace=True)
                    raise
                record.update(phase="wait", qrcode=current.qrcode, display_content=current.display_content,
                              started_at=current.started_at, polling_base=current.polling_base)
                write_json(record_path, record, replace=True)
                png, page = qr_page(root, record["attempt_id"], current.display_content)
                record.update(qr_file=str(png), page_file=str(page))
                write_json(record_path, record, replace=True)
            attempt = record["attempt_id"]
            if (not re.fullmatch(r"[0-9a-f]{32}", attempt)
                    or record.get("qr_file") != str(root / ("login-" + attempt + ".png"))
                    or record.get("page_file") != str(root / ("login-" + attempt + ".html"))):
                raise ProtocolError("Login display paths escaped private state")
            current = Login(record["qrcode"], record["display_content"], record["started_at"], record["polling_base"])
            emit(json.dumps({"status": "scan_required", "qr_file": record["qr_file"],
                             "page_file": record["page_file"]}, ensure_ascii=False), flush=True)
            if open_page:
                subprocess.run(["open", record["page_file"]], check=True)
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                try:
                    status, credentials = await api.login_status(current, verify_code=verify_code)
                except TransportError:
                    emit(json.dumps({"status": "poll_network_retry"}), flush=True)
                    await asyncio.sleep(1)
                    continue
                record.update(phase=status, polling_base=current.polling_base)
                write_json(record_path, record, replace=True)
                if credentials is not None:
                    save_credentials(credential_file, credentials)
                    return {"status": "awaiting_owner_confirmation", "owner_fingerprint": owner_fingerprint(credentials)}
                if status in {"expired", "need_verifycode", "verify_code_blocked"}:
                    return {"status": status}
                if status == "scaned":
                    verify_code = None
                await asyncio.sleep(1)
            return {"status": "waiting", "resume_existing_login": True}
    finally:
        await http.close()
