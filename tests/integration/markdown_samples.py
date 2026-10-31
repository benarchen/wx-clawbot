"""Prepare reviewable, artificial MD01 acceptance payloads; never sends anything."""
import hashlib
import json
from pathlib import Path

from wx_clawbot.output import render_segments


def prepare():
    cases = json.loads((Path(__file__).parents[1] / 'fixtures/wechat-markdown.json').read_text())['cases']
    sources = {
        'Q01': 'MD01 新渲染样例：核心结构，只核对显示，不执行任务。\n\n' + '\n\n'.join(c['text'] for c in cases[:8]),
        'Q02': 'MD01 新渲染样例：代码与扩展，只核对显示和复制，不执行代码。\n\n' + '\n\n'.join(c['text'] for c in cases[8:13]),
        'Q03': '## 长文开始\n\nMD01-LONG-START\n\n- 第一项\n  - 第二层\n\n```text\n' +
               ''.join(f'  line_{i:04} = "中文x,y {i:04}"  \n' for i in range(600)) +
               '```\n\n> MD01-LONG-END\n\n结束。',
    }
    result = {'purpose': 'Offline review only; sending requires fresh concrete authorization', 'samples': []}
    for name, source in sources.items():
        segments = render_segments(source, prefix=lambda i,n: f'〔MD01 {name} {i}/{n}〕\n\n')
        result['samples'].append({'id': name, 'source': source, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'payloads': [{'text': p.text, 'characters': len(p.text), 'utf8_bytes': len(p.text.encode()),
                          'sha256': hashlib.sha256(p.text.encode()).hexdigest()} for p in segments]})
    result['messages'] = sum(len(sample['payloads']) for sample in result['samples'])
    return result


if __name__ == '__main__':
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
