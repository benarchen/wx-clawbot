"""Explicit MD01 offline capacity/reconstruction measurements; no account or host I/O."""
import asyncio
import hashlib
import importlib.metadata
import json
import resource
import time
from pathlib import Path

from wx_clawbot.output import RESULT_LIMIT, display_text, render_segments


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


async def main():
    fixtures = json.loads((Path(__file__).parents[1] / 'fixtures/wechat-markdown.json').read_text())['cases']
    mixed = fixtures[-1]['text'] + '\n\n'
    examples = {
        'maximum_plain': '汉字 English 123。\n\n' * (RESULT_LIMIT // len('汉字 English 123。\n\n')),
        'maximum_code': '```python\n' + '  value = "A\\B"  \n\n' * 24000 + '```\n',
        'dense_small_blocks': '- 项目\n\n> 引用\n\n' * 20000,
        'mixed': (mixed * (RESULT_LIMIT // len(mixed))),
        'maximum_heading_expansion': '# x\n' * 120000,
        'unclosed_delimiters': ('*`[_~~\\字' * 40000),
    }
    cases = {}
    for name, raw in examples.items():
        raw = raw[:RESULT_LIMIT]
        started = time.perf_counter()
        ticks = []
        worker = asyncio.create_task(asyncio.to_thread(render_segments, raw))
        while not worker.done():
            ticks.append(time.perf_counter())
            await asyncio.sleep(.01)
        segments = await worker
        duration = time.perf_counter() - started
        rendered = display_text(raw)
        rebuilt = ''.join(part.source for part in segments)
        assert rebuilt == rendered
        assert all(0 < len(part.text) <= 8000 for part in segments)
        cases[name] = {
            'source_chars': len(raw), 'source_utf8_bytes': len(raw.encode()),
            'seconds': round(duration, 4), 'segments': len(segments),
            'maximum_payload_chars': max(len(p.text) for p in segments),
            'maximum_payload_utf8_bytes': max(len(p.text.encode()) for p in segments),
            'source_sha256': digest(raw), 'rendered_sha256': digest(rendered),
            'rebuilt_sha256': digest(rebuilt), 'reconstructed_exactly': True,
            'event_loop_maximum_tick_gap_seconds': round(max((b-a for a,b in zip(ticks,ticks[1:])), default=0), 4),
        }
        assert duration < 20, (name, duration)
    result = {'scope': 'Offline implementation evidence only; no WeChat display/copy acceptance',
              'dependencies': {p: importlib.metadata.version(p) for p in ['markdown-it-py', 'mdurl']},
              'result_limit': RESULT_LIMIT, 'case_timeout_seconds': 20,
              'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'cases': cases}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
