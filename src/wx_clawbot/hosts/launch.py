"""Build a visible TUI command without relying on the GUI application's PATH."""

import os
import shlex
from pathlib import Path


def native_tui_command(executable: Path, codex_home: Path, project: Path, *, path: str | None = None) -> str:
    executable = executable.resolve(strict=True)
    codex_home = codex_home.resolve(strict=True)
    project = project.resolve(strict=True)
    if not project.is_dir() or not codex_home.is_dir() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Accessible project and executable required")
    with executable.open("rb") as stream:
        magic = stream.read(4)
    # A Node wrapper's /usr/bin/env shebang depends on the GUI's reduced PATH.
    if magic not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        raise ValueError("Use the installed native macOS Codex executable, not a PATH-dependent wrapper")
    # The local daemon mode preserves local repository trust inheritance. --remote
    # treats even a local Unix endpoint as a remote workspace with exact-cwd trust.
    # General -c overrides disable implicit daemon reuse in the verified CLI.
    # Runtime membership must still be checked after launch (fallback is possible).
    return shlex.join([
        "/usr/bin/env", "CODEX_HOME=" + str(codex_home),
        "PATH=" + (os.environ.get("PATH", os.defpath) if path is None else path), str(executable),
        "--cd", str(project),
    ])
