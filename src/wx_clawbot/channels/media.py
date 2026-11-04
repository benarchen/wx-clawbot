"""Bounded owner-image retrieval from the frozen Weixin CDN protocol."""

import base64
import hashlib
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PIL import Image


MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
DOWNLOAD_SECONDS = 30
CDN_HOST = "novac2c.cdn.weixin.qq.com"
ERROR_TEXT = {
    "untrusted_origin": "图片下载地址未通过微信 CDN 核验",
    "invalid_key": "图片解密信息无效",
    "invalid_image": "图片损坏或不是支持的静态 JPEG／PNG",
    "image_limit": "图片超过字节、像素或单图限制",
    "download_failed": "图片下载失败，请核对网络",
    "download_timeout": "图片下载超过时限",
    "capacity": "私有附件存储预算已满",
    "file_unavailable": "私有图片文件缺失或内容已变化",
}


class ImageError(ValueError):
    def __init__(self, code):
        if code not in ERROR_TEXT:
            raise ValueError("A public image failure category is required")
        self.code = code
        super().__init__(ERROR_TEXT[code])


def media_url(image):
    media = image.get("media")
    if not isinstance(media, dict):
        raise ImageError("invalid_image")
    url = media.get("full_url")
    if not url:
        query = media.get("encrypt_query_param")
        if not isinstance(query, str) or not query or len(query) > 16384:
            raise ImageError("invalid_image")
        url = "https://" + CDN_HOST + "/c2c/download?" + urllib.parse.urlencode({"encrypted_query_param": query})
    if not isinstance(url, str) or len(url) > 32768 or any(ord(c) < 33 for c in url):
        raise ImageError("untrusted_origin")
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == CDN_HOST and parsed.port in (None, 443)
                 and parsed.username is None and parsed.password is None and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ImageError("untrusted_origin")
    return url


def image_key(image):
    value = image.get("aeskey")
    if value:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", value):
            raise ImageError("invalid_key")
        return bytes.fromhex(value)
    media = image.get("media")
    if not isinstance(media, dict):
        raise ImageError("invalid_image")
    encoded = media.get("aes_key")
    if not encoded:
        return None
    if not isinstance(encoded, str) or len(encoded) > 128:
        raise ImageError("invalid_key")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ImageError("invalid_key") from None
    if len(raw) == 16:
        return raw
    if len(raw) == 32 and re.fullmatch(b"[0-9a-fA-F]{32}", raw):
        return bytes.fromhex(raw.decode("ascii"))
    raise ImageError("invalid_key")


def decrypt_image(raw, key):
    if not raw or len(raw) > MAX_BYTES:
        raise ImageError("image_limit")
    if key is None:
        return raw
    if len(raw) % 16:
        raise ImageError("invalid_key")
    try:
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        padded = decryptor.update(raw) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
    except ValueError:
        raise ImageError("invalid_key") from None
    if not plain or len(plain) > MAX_BYTES:
        raise ImageError("image_limit")
    return plain


def validate_image(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ImageError("image_limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG"]) as image:
                kind, (width, height) = image.format, image.size
                if width * height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                    raise ImageError("image_limit")
                image.verify()
            with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG"]) as image:
                image.load()
    except ImageError:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageError("invalid_image") from None
    return {"format": kind, "width": width, "height": height, "byte_size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


class NoMediaRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise ImageError("untrusted_origin")


def public_connection(address, timeout=30, source_address=None):
    """Connect to the checked address itself, without a second DNS lookup."""
    started = time.monotonic()
    addresses = socket.getaddrinfo(*address, type=socket.SOCK_STREAM)
    for _, _, _, _, sockaddr in addresses:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global or getattr(ip, "ipv4_mapped", None) and not ip.ipv4_mapped.is_global:
            raise ImageError("untrusted_origin")
    last = None
    for family, kind, protocol, _, sockaddr in addresses:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ImageError("download_timeout")
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(remaining)
            if source_address:
                connection.bind(source_address)
            connection.connect(sockaddr)
            return connection
        except OSError as exc:
            last = exc
            connection.close()
    if last:
        raise last
    raise ImageError("download_failed")


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # HTTPConnection's factory hook in the pinned Python 3.14 runtime.
        self._create_connection = public_connection


class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(PublicHTTPSConnection, request, context=self._context)


def download_opener():
    proxies = urllib.request.getproxies()
    proxy = proxies.get("https") if not urllib.request.proxy_bypass(CDN_HOST) else None
    context = ssl.create_default_context()
    if proxy:
        parsed = urllib.parse.urlsplit(proxy)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ImageError("untrusted_origin")
        # Preserve the existing CONNECT route; its origin DNS is resolved by the
        # proxy. The fixed CDN hostname and TLS certificate still must match.
        return urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy}),
                                          urllib.request.HTTPSHandler(context=context), NoMediaRedirect())
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                      PublicHTTPSHandler(context=context), NoMediaRedirect())


def _download_image(image):
    url, key = media_url(image), image_key(image)
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "wx-clawbot/image-input"}, method="GET")
    try:
        with download_opener().open(request, timeout=30) as response:
            chunks, total = [], 0
            while True:
                remaining = 30 - (time.monotonic() - started)
                if remaining <= 0:
                    raise ImageError("download_timeout")
                # read1 returns after a single underlying read, so slow trickles
                # cannot hide the elapsed deadline inside an accumulating read.
                sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if sock is not None:
                    sock.settimeout(remaining)
                chunk = response.read1(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ImageError("image_limit")
                chunks.append(chunk)
        plain = decrypt_image(b"".join(chunks), key)
        return plain, validate_image(plain)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ImageError("download_failed") from None
    except (urllib.error.URLError, OSError):
        raise ImageError("download_failed") from None


def download_image(image):
    """Bound DNS, proxy, TLS and decoding together, and reap timed-out work."""
    payload = json.dumps(image, ensure_ascii=False).encode()
    if len(payload) > 65536:
        raise ImageError("invalid_image")
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", "wx_clawbot.channels.media"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        output, _ = process.communicate(payload, timeout=DOWNLOAD_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise ImageError("download_timeout") from None
    except BaseException:
        process.kill()
        process.communicate()
        raise
    try:
        header, raw = output.split(b"\n", 1)
        if len(header) > 1024 or len(raw) > MAX_BYTES:
            raise ValueError()
        metadata = json.loads(header)
        if process.returncode:
            raise ImageError(metadata.get("error", "download_failed"))
        if (metadata["format"] not in {"JPEG", "PNG"}
                or not 0 < len(raw) == metadata["byte_size"] <= MAX_BYTES
                or not 0 < metadata["width"] * metadata["height"] <= MAX_PIXELS
                or hashlib.sha256(raw).hexdigest() != metadata["sha256"]):
            raise ValueError()
        return raw, metadata
    except ImageError:
        raise
    except (ValueError, TypeError, KeyError):
        raise ImageError("download_failed") from None


if __name__ == "__main__":
    from ..release import verify_active
    verify_active()
    try:
        payload = sys.stdin.buffer.read(65537)
        if len(payload) > 65536:
            raise ImageError("invalid_image")
        data, info = _download_image(json.loads(payload))
        sys.stdout.buffer.write(json.dumps(info).encode() + b"\n" + data)
    except ImageError as exc:
        sys.stdout.buffer.write(json.dumps({"error": exc.code}).encode() + b"\n")
        raise SystemExit(1)
