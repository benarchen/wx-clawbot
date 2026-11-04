"""Bounded display-only subprocess; no credentials, native client or filesystem writes."""

from dataclasses import asdict
import json
import resource
import sys

from .output import render_segments


def main():
    from .release import verify_active
    verify_active()
    raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Display worker input exceeds bound")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"text"}:
        raise ValueError("Invalid display worker input")
    parts = render_segments(value["text"])
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak *= 1024
    payload = json.dumps({"parts": [asdict(part) for part in parts], "peak_rss_bytes": peak},
                         ensure_ascii=False).encode()
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("Display worker output exceeds bound")
    sys.stdout.buffer.write(payload)


if __name__ == "__main__":
    main()
