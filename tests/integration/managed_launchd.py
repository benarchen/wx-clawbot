"""Explicit launchd test using an owned, network-free stub; never runs serve."""

import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time


def control(*args):
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=10)


def main():
    root = Path(__file__).resolve().parents[2]
    directory = root / ".tmp/bridge-supervision/launchd-probe"
    directory.mkdir(parents=True, exist_ok=False)
    label = f"local.wx-clawbot.selftest-{os.getpid()}"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    if control("print", target).returncode == 0:
        raise RuntimeError("Test label already present; refusing to modify it")
    counter = directory / "starts.json"
    worker = directory / "worker.py"
    worker.write_text(
        "import json, pathlib, sys, time\n"
        "path = pathlib.Path(sys.argv[1])\n"
        "starts = json.loads(path.read_text()) if path.exists() else []\n"
        "starts.append(time.time())\n"
        "path.write_text(json.dumps(starts))\n"
        "raise SystemExit(7 if len(starts) == 1 else 0)\n"
    )
    value = plistlib.loads((root / "config/launchd.example.plist").read_bytes())
    value.update(Label=label, ProgramArguments=[sys.executable, str(worker), str(counter)],
                 WorkingDirectory=str(directory))
    plist = directory / "probe.plist"
    plist.write_bytes(plistlib.dumps(value))
    loaded = False
    result = {}
    try:
        reply = control("bootstrap", domain, str(plist))
        if reply.returncode:
            raise RuntimeError(f"Test bootstrap failed with code {reply.returncode}")
        loaded = True
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            starts = json.loads(counter.read_text()) if counter.exists() else []
            if len(starts) >= 2:
                break
            time.sleep(.25)
        else:
            raise TimeoutError("Owned failure did not restart within 65 seconds")
        gap = starts[1] - starts[0]
        assert gap >= 25, gap
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            assert len(json.loads(counter.read_text())) == 2, "Successful exit was restarted"
            time.sleep(.25)
        report = control("print", target)
        assert report.returncode == 0 and "last exit code = 0" in report.stdout
        result = {"result": "passed", "starts": 2, "first_exit": 7, "second_exit": 0,
                  "restart_gap_seconds": round(gap, 3), "normal_exit_observation_seconds": 35,
                  "native_calls": 0, "wechat_calls": 0, "business_process_signals": 0}
    finally:
        if loaded:
            removed = control("bootout", target)
            result["owned_label_removed"] = removed.returncode == 0
    if not result.get("owned_label_removed"):
        raise RuntimeError("Owned test label cleanup failed")
    (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
