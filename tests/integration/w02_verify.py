"""Explicit read-only verification of controlled live W02 fixtures.

The private record is produced while starting dedicated test terminals. It is
not a success receipt: every assertion below re-reads the host or native runtime.
This file is deliberately outside automatic unit-test discovery.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import iterm2

from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.hosts.connection import close_connection
from wx_clawbot.hosts.discovery import ItermDirectory, TerminalEndpoint, inspect_terminal
from wx_clawbot.hosts.process import ProcessIdentity
from wx_clawbot.sessions import SessionBinding, verify_binding


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def endpoint(row):
    p = row["process"]
    return TerminalEndpoint(row["terminal_id"], ProcessIdentity(
        p["pid"], tuple(p["started"]), p["executable"], p["tty_device"]
    ), "codex_candidate")


def messages(turn, kind):
    if kind == "agentMessage":
        return "\n".join(i["text"] for i in turn["items"] if i["type"] == kind)
    return "\n".join(c.get("text", "") for i in turn["items"] if i["type"] == kind
                     for c in i["content"])


async def verify(record):
    cases = record["cases"]
    require(Path(cases["local-main-one"]["project"]).resolve() !=
            Path(cases["local-main-two"]["project"]).resolve(), "Two distinct projects are required")
    root = Path(__file__).resolve().parents[2] / ".tmp"
    for label in ("local-main-one", "local-main-two", "local-duplicate-one", "independent-runtime-v2"):
        require(Path(cases[label]["project"]).resolve().is_relative_to(root.resolve()),
                "Live verifier is restricted to project-local temporary fixtures")
    native = await CodexConnection.connect(Path(record["socket"]))
    host = None
    try:
        host = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        directory = ItermDirectory(host)
        app = await asyncio.wait_for(iterm2.async_get_app(host), 5)
        ids = []
        for label in ("local-main-one", "local-main-two"):
            row = cases[label]
            require(isinstance(row.get("native_session_id"), str) and bool(row["native_session_id"]),
                    "Native session identity proof is missing")
            binding = SessionBinding(endpoint(row), Path(row["project"]),
                                     tuple(row["runtime_identity"]), row["thread_id"], row["native_session_id"])
            metadata = await verify_binding(binding, directory, native)
            require(metadata.get("model") == row["model"], "Model differs from the original terminal snapshot")
            require(metadata.get("modelProvider") == row["model_provider"], "Provider changed")
            turns = (await native.read_turns(row["thread_id"]))["data"]
            require(len(turns) == 3 and all(t["status"] == "completed" for t in turns),
                    "Expected exactly three completed native turns")
            nonce = row["nonce"]
            bridge = row["bridge_submission"]["marker"]
            desktop = row["desktop_submission"]["marker"]
            require(nonce in messages(turns[0], "userMessage"), "Original terminal input is not attested")
            require(bridge in messages(turns[1], "userMessage"), "Bridge turn identity is missing")
            require(desktop in messages(turns[2], "userMessage"), "Desktop continuation identity is missing")
            require(all(v in messages(turns[1], "agentMessage") for v in (nonce, bridge)),
                    "Bridge did not retain the original terminal context")
            require(all(v in messages(turns[2], "agentMessage") for v in (nonce, bridge, desktop)),
                    "Desktop did not retain both earlier turns")
            require(len({t["id"] for t in turns}) == 3, "Duplicate native turn")
            ids.append(row["thread_id"])

        duplicate = cases["local-duplicate-one"]
        require(duplicate["project"] == cases["local-main-one"]["project"], "Same-directory negative is missing")
        duplicate_meta = await native.inspect(duplicate["thread_id"])
        require(Path(duplicate_meta["cwd"]).resolve() == Path(duplicate["project"]).resolve(), "Duplicate project mismatch")
        turns = (await native.read_turns(duplicate["thread_id"]))["data"]
        require(len(turns) == 1 and turns[0]["status"] == "completed", "Unrelated duplicate received extra tasks")
        require(duplicate["nonce"] in messages(turns[0], "userMessage"), "Duplicate identity is not attested")
        ids.append(duplicate["thread_id"])
        require(len(set(ids)) == 3, "Same-directory sessions were conflated")
        require(not await directory.validate(endpoint(duplicate)), "Exited terminal endpoint still accepted")

        shell = app.get_session_by_id(cases["ordinary-shell"]["terminal_id"])
        require(shell is not None, "Ordinary shell fixture disappeared")
        shell_endpoint = await inspect_terminal(shell)
        require(shell_endpoint.classification == "ordinary_terminal" and
                not await directory.validate(shell_endpoint), "Ordinary shell was accepted")

        independent = cases["independent-runtime-v2"]
        terminal = app.get_session_by_id(independent["terminal_id"])
        require(terminal is not None, "Independent negative terminal disappeared; cannot infer a pass")
        process = (await inspect_terminal(terminal)).process
        require(process is not None and process.pid == independent["process"]["pid"]
                and process.started == tuple(independent["process"]["started"]), "Independent process identity changed")
        metadata = await native.inspect(independent["thread_id"])
        require(metadata["status"]["type"] == "notLoaded", "Independent thread was loaded into the shared runtime")
        turns = (await native.read_turns(independent["thread_id"]))["data"]
        require(any(independent["nonce"] in messages(t, "userMessage") for t in turns),
                "Independent thread identity is not attested")
        try:
            await native.observe_loaded(independent["thread_id"], Path(independent["project"]))
        except ValueError as exc:
            require("not loaded" in str(exc), "Unexpected refusal reason")
        else:
            raise RuntimeError("Independent native thread was incorrectly accepted")
        require((await native.inspect(independent["thread_id"]))["status"]["type"] == "notLoaded",
                "Independent thread was resumed despite refusal")

        config = Path(native.server_info["codexHome"]) / "config.toml"
        require(hashlib.sha256(config.read_bytes()).hexdigest() == record["expected_config_sha256"],
                "Global config differs from the explicitly authorized post-trust baseline")
        return {
            "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M"),
            "runtime_version": native.server_version,
            "projects": 2, "continuity_turns_per_project": 3,
            "same_directory_native_threads_distinct": True,
            "ordinary_shell_rejected": True, "real_exited_endpoint_rejected": True,
            "independent_runtime_refused_without_resume": True,
            "original_terminal_process_runtime_and_native_session_preserved": True,
            "models_and_providers_preserved": True, "authorized_config_baseline_unchanged": True,
            "verification_performed_no_model_tasks": True,
        }
    finally:
        await native.close()
        if host is not None:
            await close_connection(host)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow read-only access to dedicated live terminals")
    parser.add_argument("--record", required=True, type=Path, help="Private fixture launch and native identity record")
    parser.add_argument("--report", type=Path, help="Optional sanitized report, with no paths, identities or messages")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; ordinary unit tests never access terminals")
    result = asyncio.run(verify(json.loads(args.record.read_text())))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
