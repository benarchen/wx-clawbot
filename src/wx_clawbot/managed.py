"""launchd entry point: one bridge, bounded private diagnostics, no task retries."""

import argparse
import contextlib
from dataclasses import asdict
import datetime
import hashlib
import json
import logging
import logging.handlers
import os
from pathlib import Path
import re
import signal
import time

from .channels.private import private_directory, private_file, private_lease, read_json, write_json
from .cli import main as cli_main
from .operations import existing_root
from .hosts.process import read_process


LOG_LIMIT = 1024 * 1024
LOG_BACKUPS = 3
STATUSES = {"foreground_ready", "capabilities", "receive_disconnected", "failed", "stopped", "upgrade_required"}
STATES = {"not_running", "connecting", "verifying", "ready", "unavailable", "stopped"}


def source_digest():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


class PrivateRotatingHandler(logging.handlers.RotatingFileHandler):
    def _open(self):
        path = Path(self.baseFilename)
        if path.exists() or path.is_symlink():
            private_file(path)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)


def open_log(root, *, limit=LOG_LIMIT):
    directory = private_directory(root / "logs")
    path = directory / "bridge.jsonl"
    for candidate in [path, *(directory / f"bridge.jsonl.{i}" for i in range(1, LOG_BACKUPS + 1))]:
        if candidate.exists() or candidate.is_symlink():
            private_file(candidate)
    handler = PrivateRotatingHandler(path, maxBytes=limit, backupCount=LOG_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.Logger("wx-clawbot-managed", logging.INFO)
    logger.addHandler(handler)
    return logger, handler


def record(logger, event, **fields):
    logger.info(json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "event": event, **fields}, ensure_ascii=False))


def error_name(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value) else "UnknownError"


class EventStream:
    """Only known structured lifecycle fields reach disk; arbitrary output is dropped."""

    def __init__(self, logger):
        self.logger, self.buffer, self.dropping = logger, "", False

    def write(self, text):
        for part in text.splitlines(keepends=True):
            if len(self.buffer) + len(part) > 8192:
                self.buffer, self.dropping = "", True
            elif not self.dropping:
                self.buffer += part
            if part.endswith("\n"):
                if not self.dropping:
                    self.consume(self.buffer)
                self.buffer, self.dropping = "", False
        return len(text)

    def consume(self, text):
        try:
            value = json.loads(text)
        except (ValueError, RecursionError):
            return
        if not isinstance(value, dict) or not isinstance(value.get("status"), str) or value["status"] not in STATUSES:
            return
        fields = {}
        if "error_type" in value:
            fields["error_type"] = error_name(value["error_type"])
        if isinstance(value.get("failures"), list):
            fields["failures"] = [{"component": error_name(item.get("component")),
                                    "error_type": error_name(item.get("error_type"))}
                                   for item in value["failures"][:8] if isinstance(item, dict)]
        for name in ("host", "native"):
            item = value.get(name)
            if isinstance(item, dict) and isinstance(item.get("state"), str) and item["state"] in STATES:
                fields[name] = {"state": item["state"]}
        record(self.logger, value["status"], **fields)

    def flush(self):
        pass


class ErrorStream:
    def __init__(self, logger):
        self.logger, self.reported = logger, False

    def write(self, text):
        if text and not self.reported:
            record(self.logger, "stderr_suppressed")
            self.reported = True
        return len(text)

    def flush(self):
        pass


def run(config, state_dir):
    root = existing_root(state_dir)
    with private_lease(root / "managed.lock"):
        path = root / "managed.json"
        previous = read_json(path) if path.exists() else {}
        identity = read_process(os.getpid())
        if identity is None:
            raise RuntimeError("Cannot establish managed process identity")
        logger, handler = open_log(root)
        value = {"version": 1, "state": "running", "pid": os.getpid(), "process": asdict(identity), "started_at": time.time(),
                 "source_sha256": source_digest(), "previous_exit_unobserved": previous.get("state") == "running"}
        write_json(path, value, replace=path.exists())
        record(logger, "process_start", pid=value["pid"], source_sha256=value["source_sha256"],
               previous_exit_unobserved=value["previous_exit_unobserved"])
        received_signal = None
        old_handler = signal.getsignal(signal.SIGTERM)

        def terminate(number, frame):
            nonlocal received_signal
            received_signal = number
            record(logger, "process_signal", signal=number)
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, terminate)
        code = 1
        try:
            with contextlib.redirect_stdout(EventStream(logger)), contextlib.redirect_stderr(ErrorStream(logger)):
                code = cli_main(["serve", "--config", str(config), "--state-dir", str(root)])
                if type(code) is not int or not 0 <= code <= 255:
                    code = 1
        except KeyboardInterrupt:
            code = 130
        except SystemExit as exc:
            code = exc.code if type(exc.code) is int and 0 <= exc.code <= 255 else 1
        except Exception as exc:
            record(logger, "managed_failure", error_type=type(exc).__name__)
            code = 1
        finally:
            signal.signal(signal.SIGTERM, old_handler)
            if received_signal is not None:
                code = 128 + received_signal
            value.update(state="exited", finished_at=time.time(), exit_code=code, signal=received_signal)
            try:
                write_json(path, value, replace=True)
                record(logger, "process_exit", exit_code=code, signal=received_signal)
            finally:
                handler.close()
        return code


def main(argv=None):
    parser = argparse.ArgumentParser(description="wx-clawbot 的 launchd 托管入口")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path)
    args = parser.parse_args(argv)
    # New rotated files, SDK children and any state created by serve stay private.
    os.umask(0o077)
    try:
        from .release import verify_active
        verify_active(args.release_manifest)
        return run(args.config, args.state_dir)
    except Exception:
        # launchctl retains the nonzero status even if logging could not initialize.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
