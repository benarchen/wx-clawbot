"""Files belong to the private attachment ledger, never to a business project."""

import hashlib
import os
import re
from pathlib import Path

from .channels.http import ProtocolError
from .channels.private import private_directory, private_file


FILENAME = re.compile(r"[0-9a-f]{32}\.(png|jpg)\Z")


def image_path(root: Path, filename: str) -> Path:
    if not isinstance(filename, str) or not FILENAME.fullmatch(filename):
        raise ProtocolError("Invalid private attachment filename")
    directory = root / "attachments"
    if not directory.exists() or directory.is_symlink():
        raise ProtocolError("Private attachment directory is missing or invalid")
    private_directory(directory)
    return directory / filename


def verify_image_file(root: Path, filename: str, digest: str, size: int) -> Path:
    path = image_path(root, filename)
    private_file(path)
    if type(size) is not int or not 0 < size <= 10 * 1024 * 1024 or path.stat().st_size != size:
        raise ProtocolError("Private attachment size changed")
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ProtocolError("Private attachment content changed")
    return path


def write_image_file(root: Path, filename: str, content: bytes, digest: str) -> Path:
    private_directory(root / "attachments")
    path = image_path(root, filename)
    if hashlib.sha256(content).hexdigest() != digest or not 0 < len(content) <= 10 * 1024 * 1024:
        raise ProtocolError("Attachment bytes differ from the prepared record")
    if path.exists() or path.is_symlink():
        return verify_image_file(root, filename, digest, len(content))
    temporary = path.with_suffix(path.suffix + ".part")
    # A surviving partial file remains associated with this prepared record.
    # It may only be replaced when its ownership and exact completed bytes match.
    if temporary.exists() or temporary.is_symlink():
        private_file(temporary)
        if temporary.read_bytes() != content:
            raise ProtocolError("Incomplete attachment requires explicit reconciliation")
    else:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    # link is exclusive: never replace a file which unexpectedly appeared.
    os.link(temporary, path, follow_symlinks=False)
    temporary.unlink()
    return verify_image_file(root, filename, digest, len(content))


def remove_released_file(root: Path, filename: str) -> None:
    path = image_path(root, filename)
    for candidate in (path, path.with_suffix(path.suffix + ".part")):
        if candidate.exists() or candidate.is_symlink():
            private_file(candidate)
            candidate.unlink()
