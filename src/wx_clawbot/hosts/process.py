"""Read-only macOS process identity from libproc; never reads process arguments."""

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    started: tuple[int, int]
    executable: str
    tty_device: int


class _BsdInfo(ctypes.Structure):
    # Darwin SDK sys/proc_info.h: struct proc_bsdinfo (PROC_PIDTBSDINFO = 3).
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved",
    )] + [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)] + [
        (name, ctypes.c_uint32) for name in (
            "nfiles", "pgid", "pjobc", "tty_device", "tty_pgid",
        )
    ] + [("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64),
         ("start_usec", ctypes.c_uint64)]


def read_process(pid: int) -> ProcessIdentity | None:
    if type(pid) is not int or not 0 < pid <= 2**31 - 1:
        return None
    if sys.platform != "darwin":
        raise NotImplementedError("Native terminal process identity requires macOS")
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int

    def snapshot() -> _BsdInfo | None:
        info = _BsdInfo()
        size = ctypes.sizeof(info)
        if lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), size) != size:
            return None
        if info.pid != pid or info.uid != os.getuid() or info.flags & 4 or info.status == 5:
            return None  # Wrong owner, exiting or zombie process.
        return info

    before = snapshot()
    if before is None:
        return None
    path = ctypes.create_string_buffer(4096)  # PROC_PIDPATHINFO_MAXSIZE.
    if lib.proc_pidpath(pid, path, len(path)) <= 0:
        return None
    after = snapshot()
    if after is None or (before.start_sec, before.start_usec, before.tty_device) != (
        after.start_sec, after.start_usec, after.tty_device
    ):
        return None
    return ProcessIdentity(pid, (after.start_sec, after.start_usec),
                           os.fsdecode(path.value), after.tty_device)


def read_process_directory(identity: ProcessIdentity) -> Path | None:
    """Read only the cwd descriptor of the same process generation, never argv/env."""
    if read_process(identity.pid) != identity:
        return None
    try:
        result = subprocess.run(["/usr/sbin/lsof", "-a", "-p", str(identity.pid), "-d", "cwd", "-F0n"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode or len(result.stdout) > 65536 or read_process(identity.pid) != identity:
        return None
    paths = [os.fsdecode(part[1:]) for part in result.stdout.split(b"\0") if part.startswith(b"n/")]
    if len(paths) != 1:
        return None
    try:
        path = Path(paths[0]).resolve(strict=True)
        return path if path.is_dir() else None
    except (OSError, ValueError):
        return None
