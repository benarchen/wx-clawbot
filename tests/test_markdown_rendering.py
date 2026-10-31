"""MD01 source fidelity, structural boundaries and bounded failure paths; no real I/O."""
import json
import random
import time
import unittest
from pathlib import Path

from markdown_it import MarkdownIt

from wx_clawbot.controller import HELP
from wx_clawbot.output import COMPATIBILITY_NOTE, display_text, format_prose, render_segments, native_output


class MarkdownRenderingTests(unittest.TestCase):
    def test_list_continuation_and_code_use_explicit_item_association(self):
        raw = ('3. 第三项\n4. 第四项\n\n   续段。\n\n'
               '       value = 4\n       print(value)\n\n5. 第五项\n')
        rendered = display_text(raw)
        self.assertIn('3. 第三项\n4. 第四项', rendered)
        self.assertIn('**第 4 项续段：**\n\n续段。', rendered)
        self.assertIn('**第 4 项代码：**', rendered)
        self.assertIn('5. 第五项', rendered)
        codes = [t for t in MarkdownIt().parse(rendered) if t.type == 'fence']
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0].level, 0)
        self.assertEqual(codes[0].content, '       value = 4\n       print(value)\n')
        parts = self.rebuild(raw)
        self.assertFalse(any('续段。' in p.text and 'value = 4' in p.text for p in parts))
        self.assertEqual(display_text(rendered), rendered)

    def test_list_fence_promotion_preserves_crlf_language_and_literal_content(self):
        raw = '- 项目\r\n\r\n  ```python\r\n  x = "A\\B"  \r\n\r\n    y = 2\r\n  ```\r\n'
        rendered = display_text(raw)
        self.assertIn('**第 1 项代码：**', rendered)
        self.assertIn('```python\r\nx = "A\\B"  \r\n\r\n  y = 2\r\n```\r\n', rendered)
        self.assertEqual(display_text(rendered), rendered)
        self.rebuild(raw)

    def test_list_code_promotion_keeps_unsupported_nested_structure_and_raw_errors(self):
        samples = ['- 父项\n  - 子项\n\n    ```text\n    child\n    ```\n',
                   '- 项目\n\n  续段\n\n  ```text\n  unclosed\n']
        for raw in samples:
            self.assertEqual(display_text(raw), raw)
            self.assertNotIn('项代码：', display_text(raw))
        error = '原生错误：exact\n- item\n\n  ```text\n  x\n  ```\n'
        self.assertEqual(display_text(error), error)

    def test_complex_list_code_and_inline_prose_are_in_independent_messages(self):
        raw = ('3. 项目三\n4. 项目四\n\n   续段。\n\n       value = 4\n       print(value)\n\n'
               '命令 `/focus 1`，变量 `snake_case`。\n\n'
               '````markdown\n```text\nINNER\n```\n````\n\nEND')
        parts = render_segments(raw, prefix=lambda i, n: f'〔测试 {i}/{n}〕\n\n')
        self.assertGreaterEqual(len(parts), 3)
        self.assertEqual(''.join(p.source for p in parts), display_text(raw))
        for part in parts:
            self.assertFalse('value = 4' in part.text and 'snake_case' in part.text)
            self.assertFalse('INNER' in part.text and 'snake_case' in part.text)
            self.assertLessEqual(len(part.text), 8000)

    def test_simple_code_and_inline_prose_do_not_gain_unnecessary_messages(self):
        raw = '命令 `/focus 1`。\n\n```python\nx = 1\n```\n\n结束。'
        self.assertEqual(len(render_segments(raw)), 1)

    def test_many_complex_containers_use_bounded_explicit_literal_fragments(self):
        raw = ('- 项目\n\n    ```text\n    x\n    ```\n\n结束。\n\n' * 80)
        parts = render_segments(raw)
        self.assertEqual(''.join(p.source for p in parts), display_text(raw))
        self.assertLess(len(parts), 20)
        self.assertTrue(all('复杂代码容器过多' in p.text for p in parts))
        self.assertTrue(all(len(p.text) <= 8000 for p in parts))

    def rebuild(self, raw, **kwargs):
        segments = render_segments(raw, **kwargs)
        self.assertEqual(''.join(p.source for p in segments), display_text(raw))
        for p in segments:
            self.assertLessEqual(len(p.text), 8000)
            wire = json.dumps({'text_item': {'text': p.text}}, ensure_ascii=False).encode('utf-8')
            self.assertGreaterEqual(len(wire), len(p.text))
            right = len(p.text) - len(p.after) if p.after else len(p.text)
            self.assertEqual(p.text[len(p.before):right], p.source)
        return segments

    def test_all_fourteen_fixtures_are_stable_with_literal_spans_and_reconstruction(self):
        cases = json.loads((Path(__file__).parent / 'fixtures/wechat-markdown.json').read_text())['cases']
        self.assertEqual(len(cases), 14)
        for case in cases:
            with self.subTest(case=case['id']):
                rendered = display_text(case['text'])
                self.assertEqual(display_text(rendered), rendered)
                copied_blocks = [t.content for t in MarkdownIt().parse(rendered) if t.type in {'fence', 'code_block'}]
                for literal in case.get('rendered_literal_spans', case['literal_spans']):
                    self.assertTrue(literal in rendered or any(literal in block for block in copied_blocks), literal)
                self.rebuild(case['text'])

    def test_prose_lf_uses_paragraph_boundaries_without_growing_existing_empty_lines(self):
        raw = '\n第一行。  \n第二行。\n\n段落。\n\n\n尾段。\n\n'
        self.assertEqual(display_text(raw), '\n第一行。  \n\n第二行。\n\n段落。\n\n\n尾段。\n\n')
        self.rebuild(raw)

    def test_six_headings_setext_and_nested_container_keep_explicit_levels(self):
        raw = ''.join('#' * i + f' 标题 {i}\n\n' for i in range(1, 7))
        result = display_text(raw)
        for n in '一二三四五六':
            self.assertIn(f'**【{n}级标题】**', result)
        self.assertEqual(display_text('> 引用标题\n> ========\n'), '> **【一级标题】** 引用标题\n')
        self.assertEqual(display_text('- ## 列表标题\n'), '- **【二级标题】** 列表标题\n')
        code = '```text\n# literal title\n---\n```\n'
        self.assertEqual(display_text(code), code)

    def test_literals_multiline_code_backticks_links_escapes_quotes_are_unchanged(self):
        samples = ['内容 ````中文x,y ` a```` 测试。', '内容 ``中文x,y\n a`` 测试。',
                   '![中文x,y](https://example.invalid/a.png)',
                   '显示 "中文x,y\\\"z"。', r'\*\*字面星号\*\*',
                   '```python\r\nvalue="中文x,y"\u2028\u2029\r\n```\r\n']
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(format_prose(sample), sample)
                self.assertEqual(display_text(sample), sample)
        linked = '这是[链接](https://example.invalid/中文x,y:1(a)?q=%20#x)文字。'
        self.assertEqual(format_prose(linked), linked)
        self.assertEqual(display_text(linked), '这是链接\n\n<https://example.invalid/中文x,y:1(a)?q=%20#x>\n\n文字。')

    def test_prose_changes_around_but_not_inside_literal_nodes(self):
        self.assertEqual(display_text('中文Codex2测试,完成!'), '中文 Codex2 测试，完成！')
        raw = '重点 **中文Codex2测试**，字面 `中文x,y`。'
        self.assertEqual(display_text(raw), '重点 **中文 Codex2 测试**，字面 `中文x,y`。')
        error = '原生错误：中文x,y:1\nline 中文x,y'
        self.assertEqual(display_text('说明!\n\n' + error), '说明！\n\n' + error)
        self.assertEqual(display_text('原生错误：exact\n# 中文x,y\n\n    x,y\n'), '原生错误：exact\n# 中文x,y\n\n    x,y\n')

    def test_extension_labels_remain_explicit_without_changing_code_or_link_literals(self):
        raw = '*中文*、***中文粗斜体***、*English*、~~删除线~~。\n\n`~~中文~~`，[~~链接~~](https://example.invalid/x)'
        result = display_text(raw)
        self.assertTrue(result.startswith(COMPATIBILITY_NOTE))
        self.assertIn('*中文*', result)
        self.assertIn('***中文粗斜体***', result)
        self.assertIn('、*English*、', result)
        self.assertIn('~~删除线~~', result)
        self.assertIn('`~~中文~~`，[~~链接~~](https://example.invalid/x)', result)
        self.assertEqual(display_text(result), result)

    def test_heading_followed_by_setext_rule_stays_a_rule_after_repeated_render(self):
        for raw in ['# Title\n---\n', '> # Title\n> ---\n']:
            result = display_text(raw)
            self.assertEqual(display_text(result), result)
            self.assertTrue(any(t.type == 'hr' for t in MarkdownIt().parse(result)))

    def test_indented_and_container_code_converts_to_fence_without_losing_source_spaces(self):
        for raw, literal in [('说明。\n\n    a = 1\n    b = 2\n', '    a = 1\n    b = 2\n'),
                             ('- 项目\n\n      a = 1\n      b = 2\n', '      a = 1\n      b = 2\n'),
                             ('> 引用\n>\n>     a = 1\n', '>     a = 1\n')]:
            result = display_text(raw)
            copied = ''.join(t.content for t in MarkdownIt().parse(result) if t.type == 'fence')
            expected = ''.join(line[2:] for line in literal.splitlines(keepends=True)) if literal.startswith('> ') else literal
            self.assertEqual(copied, expected)
            self.assertEqual(display_text(result), result)

    def test_actual_code_content_keeps_deep_and_list_structural_indentation(self):
        for raw, expected in [('        value = 4\n', '        value = 4\n'),
                              ('- 项目\n\n      a = 1\n      b = 2\n', '      a = 1\n      b = 2\n'),
                              ('3. 项目\n\n       a = 1\n', '       a = 1\n')]:
            tokens = MarkdownIt().parse(display_text(raw))
            copied = ''.join(t.content for t in tokens if t.type == 'fence')
            self.assertEqual(copied, expected)

    def test_multi_message_code_copies_exact_lines_and_has_no_repair_inside_code(self):
        code = ''.join(f'  value_{i} = "A\\B"  \n\n' for i in range(1800))
        raw = '说明。\n\n~~~~python\n' + code + '~~~~\n\n结束。'
        segments = self.rebuild(raw, prefix=lambda i, n: f'〔测试 {i}/{n}〕\n\n')
        copied = []
        for part in segments:
            tokens = MarkdownIt().parse(part.text)
            copied.extend(t.content for t in tokens if t.type == 'fence')
            self.assertEqual(len([t for t in tokens if t.type == 'fence']), int('value_' in part.text))
        self.assertEqual(''.join(copied), code)
        self.assertGreater(len(segments), 3)

    def test_reference_links_expand_before_segments_without_rewriting_targets(self):
        definition = '[ref]: https://example.invalid/a(b)?q=%20#two "中文x,y"\n'
        raw = ('引用 [目标][ref]。\n\n' * 700) + definition
        parts = self.rebuild(raw)
        self.assertEqual(sum(p.source.count('https://example.invalid/a(b)?q=%20#two') for p in parts), 700)
        self.assertEqual(sum(p.source.count('链接标题：`中文x,y`') for p in parts), 700)
        self.assertTrue(all('[ref]' not in p.text for p in parts))
        for part in parts:
            self.assertNotIn('[目标](', part.text)

    def test_oversized_atomic_units_are_labelled_and_can_be_rebuilt_exactly(self):
        for raw in ['https://example.invalid/' + 'a' * 16000,
                    '`' + '字' * 16000 + '`', '**' + '字' * 16000 + '**',
                    '```python\nvalue = "' + 'a' * 16000 + '"\n```\n',
                    '- ' + '字' * 16000, '| A | B |\n|---|---|\n| ' + 'a' * 16000 + ' | b |']:
            with self.subTest(prefix=raw[:20]):
                parts = self.rebuild(raw)
                if raw.startswith('| A |'):
                    self.assertIn('表格（字段列表）', parts[0].text)
                    self.assertTrue(any('原文片段' in p.text for p in parts))
                else:
                    self.assertTrue(all('原文片段' in p.text for p in parts))
                self.assertGreater(len(parts), 1)

    def test_unknown_syntax_unicode_and_unclosed_delimiters_are_bounded_and_literal(self):
        rng = random.Random(731)
        alphabet = ['中', 'a', '\n', '\\', '*', '~', '`', '[', ']', '(', ')', '>', '😀', '\u0301', '\u200d']
        samples = [''.join(rng.choices(alphabet, k=14000)) for _ in range(5)]
        samples += ['`' * 10000 + '\nx\n' + '`' * 10000, ('>' * 70 + ' text\n') * 400,
                    '\n'.join(['[a]: /b'] * 1200), 'A\rB', 'A\r\nB\nC\u2028D\u2029E',
                    '```text\n' + 'abc\n' * 10000]
        started = time.monotonic()
        for raw in samples:
            self.rebuild(raw)
            self.assertEqual(display_text(display_text(raw)), display_text(raw))
        self.assertLess(time.monotonic() - started, 10)

    def test_compatibility_expansion_is_bounded_and_keeps_raw_error_tail(self):
        raw = '# x\n' * 45000 + '\n原生错误：EXACT_ERROR_TAIL'
        rendered = display_text(raw)
        self.assertLessEqual(len(rendered), 480000)
        self.assertIn('完整内容请在原终端查看', rendered)
        self.assertTrue(rendered.endswith('原生错误：EXACT_ERROR_TAIL'))
        self.assertEqual(display_text(rendered), rendered)
        self.rebuild(raw)

    def test_emoji_combining_boundary_and_prefix_budget(self):
        raw = ('汉字👩\u200d💻e\u0301\n\n' * 5000)
        parts = self.rebuild(raw, prefix=lambda i, n: '来' * 384)
        for p in parts[:-1]:
            self.assertFalse(p.source.endswith('\u200d'))
        with self.assertRaises(ValueError):
            render_segments(raw, prefix=lambda i, n: 'p' * 385)
        for raw in ['', None, 'x' * 512001]:
            with self.assertRaises(ValueError):
                render_segments(raw)

    def test_help_only_groups_existing_commands_as_literal_copyable_text(self):
        expected = ['projects', 'cd', 'new', 'sessions', 'focus', 'unfocus', 'send', 'attach', 'detach',
                    'status', 'stop', 'approve', 'deny', 'answer']
        rendered = display_text(HELP)
        for command in expected:
            self.assertEqual(rendered.count('`/' + command + ('`' if command in ['projects','unfocus','detach'] else ' ')), 1)
        for title in ['项目与会话', '任务控制', '审批与追问']:
            self.assertIn(title, rendered)
        self.assertNotIn('\u2028', rendered)

    def test_final_result_source_and_errors_stay_native_until_display(self):
        body = '# 标题\n中文Codex2,完成!\n\n```text\n中文x,y\n```'
        turn = {'status': 'failed', 'items': [{'type': 'agentMessage', 'text': body},
                {'type': 'agentMessage', 'phase': 'commentary', 'text': 'DO_NOT_SEND'}],
                'error': {'message': '中文x,y:1'}}
        extracted = native_output(turn)
        self.assertTrue(extracted.startswith(body))
        rendered = display_text(extracted)
        self.assertNotIn('DO_NOT_SEND', rendered)
        self.assertTrue(rendered.endswith('原生错误：中文x,y:1'))
