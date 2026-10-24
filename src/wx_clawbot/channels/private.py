"""Project-owned private state with explicit ownership and permissions."""

import json
import fcntl
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .http import ProtocolError
from .wechat import Credentials


def private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise ProtocolError("Private state directory cannot be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProtocolError("Private directory must be owned by this user with mode 0700")
    return path.resolve()


def private_file(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ProtocolError("Private file must be a user-owned regular file with mode 0600")


def read_json(path: Path) -> dict:
    private_file(path)
    if path.stat().st_size > 65536:
        raise ProtocolError("Private JSON record exceeds bound")
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError):
        raise ProtocolError("Invalid private JSON record") from None
    if not isinstance(value, dict):
        raise ProtocolError("Private JSON record must be an object")
    return value


def write_json(path: Path, value: dict, *, replace=False):
    private_directory(path.parent)
    if not replace:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        return
    private_file(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".private-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def private_lease(path: Path):
    private_directory(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        private_file(path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProtocolError("Another process owns this private operation") from None
        yield
    finally:
        os.close(fd)


def save_credentials(path: Path, credentials: Credentials):
    payload = {"version": 1, "credentials": asdict(credentials), "owner_confirmed": False}
    # Existing bindings are never silently replaced by a fresh scan.
    write_json(path, payload)


def load_credentials(path: Path, *, require_confirmed=True) -> Credentials:
    try:
        payload = read_json(path)
        item = payload["credentials"]
        if payload["version"] != 1 or (require_confirmed and payload["owner_confirmed"] is not True):
            raise ValueError
        return Credentials.from_response({"bot_token": item["token"], "ilink_bot_id": item["bot_id"],
                                          "ilink_user_id": item["owner_id"], "baseurl": item["base"]})
    except (KeyError, TypeError, ValueError):
        raise ProtocolError("Invalid or unconfirmed project credential record") from None
