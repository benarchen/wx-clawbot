"""Explicit MD01 offline observations; no network, live state, clipboard or host IO.

Run: .venv/bin/python tests/integration/markdown_prepare.py > .tmp/<task>/probe.json
This validates fixtures and reports the old renderer. It does not certify rendering
or intentionally fail the normal suite while MD01 implementation remains pending.
"""

import hashlib
import json
from pathlib import Path

from markdown_it import MarkdownIt

from wx_clawbot.controller import HELP
from wx_clawbot.output import display_segments, display_text, format_prose


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def observe(text, literal_spans, rendered_literal_spans=None):
    rendered = display_text(text)
    segments = display_segments(text)
    # Controller and final-result paths apply display_text again before freezing.
    frozen = [display_text(segment) for segment in segments]
    copied_blocks = [t.content for t in MarkdownIt().parse(rendered) if t.type in {'fence', 'code_block'}]
    return {
        "source_sha256": digest(text),
        "source_chars": len(text),
        "source_lf": text.count("\n"),
        "rendered_lf": rendered.count("\n"),
        "rendered_ls": rendered.count("\u2028"),
        "source_markdown_unchanged": text == rendered,
        "render_idempotent": display_text(rendered) == rendered,
        "second_entry_unchanged": frozen == segments,
        "literal_spans_retained": [span in rendered or any(span in block for block in copied_blocks)
                                   for span in (literal_spans if rendered_literal_spans is None else rendered_literal_spans)],
        "prose_literal_spans_retained": [span in format_prose(text) for span in literal_spans],
        "segments": len(segments),
        "maximum_segment_chars": max(map(len, frozen)),
        "maximum_segment_utf8_bytes": max(len(part.encode("utf-8")) for part in frozen),
        "local_payload_bound": all(0 < len(part) <= 8000 for part in frozen),
        "client_display": "unverified",
        "client_copy": "unverified",
    }


def main():
    fixture = Path(__file__).resolve().parents[1] / "fixtures/wechat-markdown.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert [case["id"] for case in data["cases"]] == [f"F{i:02}" for i in range(1, 15)]
    cases = {}
    for case in data["cases"]:
        assert case["text"] and case["verify"]
        assert all(span and span in case["text"] for span in case["literal_spans"])
        cases[case["id"]] = observe(case["text"], case["literal_spans"], case.get("rendered_literal_spans"))
    mixed = data["cases"][-1]["text"]
    long_cases = {
        "mixed_80": observe((mixed + "\n\n") * 80, []),
        "atomic_url": observe("https://example.invalid/" + "x" * 9000, []),
        "atomic_code_line": observe("```text\n" + "x" * 9000 + "\n```", []),
    }
    result = {
        "scope": "MD01 preparation only; observations, not T01-T23 or A01-A12 passes",
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "fixture_count": len(cases),
        "cases": cases,
        "help": observe(HELP, []),
        "long_cases": long_cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
