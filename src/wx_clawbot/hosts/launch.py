"""Build a visible TUI command without relying on the GUI application's PATH."""

import os
import shlex
from pathlib import Path


def native_tui_command(executable: Path, socket: Path, project: Path) -> str:
    executable = executable.resolve(strict=True)
    project = project.resolve(strict=True)
    if not project.is_dir() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Accessible project and executable required")
    with executable.open("rb") as stream:
        magic = stream.read(4)
    # A Node wrapper's /usr/bin/env shebang depends on the GUI's reduced PATH.
    if magic not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        raise ValueError("Use the installed native macOS Codex executable, not a PATH-dependent wrapper")
    return shlex.join([str(executable), "--remote", "unix://" + str(socket), "--cd", str(project)])
