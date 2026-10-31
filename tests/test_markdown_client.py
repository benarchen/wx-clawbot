"""Regressions for observed Android/Mac text-subset differences, not client emulation."""
import unittest
from markdown_it import MarkdownIt
from wx_clawbot.output import COMPATIBILITY_NOTE, display_text, render_segments


class MarkdownClientTests(unittest.TestCase):
    def test_parenthetical_target_stays_a_real_link_not_only_visible_address_text(self):
        url = 'https://example.invalid/a(b)?q=%20#part'
        result = display_text(f'[目标]({url})')
        links = [c.attrGet('href') for t in MarkdownIt().parse(result) for c in t.children or [] if c.type == 'link_open']
        self.assertEqual(links, [url])

    def test_parenthetical_link_keeps_label_and_exact_target_as_standalone_url(self):
        url = 'https://example.invalid/a(b)?q=1#part'
        result = display_text(f'前文。[括号目标]({url})后文。')
        self.assertEqual(result, f'前文。括号目标\n\n<{url}>\n\n后文。')
        self.assertEqual(display_text(result), result)

    def test_parenthetical_link_continuations_remain_inside_quote_and_list(self):
        url = 'https://example.invalid/a(b)?q=1#part'
        for raw, expected in [(f'- [目标]({url})\n', f'- 目标\n\n  <{url}>\n'),
                              (f'> [目标]({url})\n', f'> 目标\n>\n> <{url}>\n')]:
            result = display_text(raw)
            self.assertEqual(result, expected)
            self.assertEqual(display_text(result), result)

    def test_parenthetical_link_in_code_error_image_or_quoted_literal_stays_literal(self):
        link = '[目标](https://example.invalid/a(b))'
        for raw in [f'```text\n{link}\n```\n', f'原生错误：{link}', f'"{link}"', f'![alt](https://example.invalid/a(b))']:
            self.assertEqual(display_text(raw), raw)

    def test_parenthetical_compatibility_keeps_wrapping_emphasis_and_heading_semantics(self):
        for raw in ['**[目标](https://example.invalid/a(b)) 后文**', '# [目标](https://example.invalid/a(b))\n']:
            result = display_text(raw)
            self.assertIn('目标（<https://example.invalid/a(b)>）', result)
            links = [c.attrGet('href') for t in MarkdownIt().parse(result) for c in t.children or [] if c.type == 'link_open']
            self.assertEqual(links, ['https://example.invalid/a(b)'])
            self.assertTrue('**目标' in result or '**【一级标题】**' in result)
            self.assertEqual(display_text(result), result)

    def test_multiple_parenthetical_targets_and_reference_titles_remain_distinct(self):
        raw = '[一](https://example.invalid/a(b))、[二](https://example.invalid/c(d) "x`y")。'
        result = display_text(raw)
        for target in ['https://example.invalid/a(b)', 'https://example.invalid/c(d)']:
            self.assertEqual(result.count(target), 1)
        self.assertIn('链接标题：``x`y``', result)
        self.assertEqual(display_text(result), result)

    def test_plain_lf_and_two_space_break_become_separate_paragraphs(self):
        self.assertEqual(display_text('第一行。\n第二行。'), '第一行。\n\n第二行。')
        self.assertEqual(display_text('第一行。  \n第二行。'), '第一行。  \n\n第二行。')
        self.assertEqual(display_text('第一行。\\\n第二行。'), '第一行。\n\n第二行。')
        self.assertEqual(display_text('第一行。\r\n第二行。'), '第一行。\r\n\r\n第二行。')

    def test_paragraph_reflow_keeps_code_quoted_values_and_structural_continuations_literal(self):
        for raw in ['**第一行\n第二行**', '*第一行\n第二行*', '> 引用\n懒续行\n',
                    '- 项目\n懒续行\n', '标题\n====\n', '显示 "中文x,y\nA B"。',
                    '```text\nA B\nC  \n```\n', '字面 ``a\n b``。',
                    '{\n  "中文x,y": "value"\n}', 'value = 1\nprint(value)\n']:
            with self.subTest(raw=raw):
                value = display_text(raw)
                if raw == '标题\n====\n':
                    self.assertEqual(value, '**【一级标题】** 标题\n')
                elif raw == '*第一行\n第二行*':
                    self.assertEqual(value, COMPATIBILITY_NOTE + raw)
                else:
                    self.assertEqual(value, raw)
                self.assertEqual(display_text(value), value)

    def test_simple_tilde_code_becomes_three_backticks_with_exact_code_bytes(self):
        for raw, expected in [('~~~text\nA\\B\n  C\n~~~\n', '```text\nA\\B\n  C\n```\n'),
                              ('~~~~python\r\nvalue="中文x,y"  \r\n~~~~~\r\n', '```python\r\nvalue="中文x,y"  \r\n```\r\n')]:
            self.assertEqual(display_text(raw), expected)
            self.assertEqual(display_text(expected), expected)
        nested = '~~~~markdown\n```text\ninside\n```\n~~~~\n'
        self.assertEqual(display_text(nested), nested)  # Do not corrupt code to mask Mac's unsupported case.

    def test_reference_expansion_preserves_target_title_and_following_inline_code(self):
        raw = '[r]: https://example.invalid/中文x,y:1?q=%20#part "title"\n\n[引用][r]\n\n命令 `/focus 1`，变量 `snake_case`。'
        expected = '\n[引用](https://example.invalid/中文x,y:1?q=%20#part "title")\n\n命令 `/focus 1`，变量 `snake_case`。'
        self.assertEqual(display_text(raw), expected)
        self.assertNotIn('[r]:', display_text(raw))
        self.assertEqual(display_text(display_text(raw)), expected)

    def test_collapsed_shortcut_and_table_references_resolve_to_first_definition(self):
        raw = '[R]: https://example.invalid/first?q=1#two\n[r]: https://example.invalid/ignored\n\n[R]、[r][]、[文本][R]\n\n| 名称 | 值 |\n| --- | --- |\n| A | [表格][r] |'
        actual = display_text(raw)
        self.assertEqual(actual.count('](https://example.invalid/first?q=1#two)'), 4)
        self.assertIn('https://example.invalid/ignored', actual)
        self.assertIn('链接定义（原文）', actual)
        self.assertEqual(display_text(actual), actual)

    def test_code_and_native_errors_do_not_supply_or_consume_reference_definitions(self):
        raw = '```text\n[r]: https://example.invalid/code\n[文本][r]\n```\n\n原生错误：literal\n[r]: https://example.invalid/error\n[文本][r]'
        self.assertEqual(display_text(raw), raw)
        code_error = '```text\n原生错误：code literal\n```\n\n# 后续标题\n\n原生错误：actual\n# raw error'
        actual = display_text(code_error)
        self.assertIn('```text\n原生错误：code literal\n```', actual)
        self.assertIn('**【一级标题】** 后续标题', actual)
        self.assertTrue(actual.endswith('原生错误：actual\n# raw error'))

    def test_simple_table_fields_preserve_row_order_code_and_escaped_pipe_value(self):
        raw = '| 名称 | 值 |\n| --- | --- |\n| Alpha | `a_b` |\n| 带竖线 | a\\|b |'
        expected = '表格（字段列表）：\n\n- 第 1 行\n  - 名称：Alpha\n  - 值：`a_b`\n- 第 2 行\n  - 名称：带竖线\n  - 值：a|b\n\n'
        self.assertEqual(display_text(raw), expected)
        self.assertEqual(display_text(expected), expected)

    def test_empty_duplicate_headers_and_empty_cells_remain_distinguishable(self):
        for raw in ['| A | A |\n|---|---|\n| x | y |', '| | Value |\n|---|---|\n| | z |', '| A | B |\n|---|---|']:
            result = display_text(raw)
            self.assertIn('表格（字段列表）', result)
            self.assertEqual(display_text(result), result)
        result = display_text('| A | A |\n|---|---|\n| x | y |')
        self.assertIn('A：x\n  - A：y', result)
        empty = display_text('| | Value |\n|---|---|\n| | z |')
        self.assertIn('第 1 列：（空）', empty)

    def test_table_reference_links_expand_before_field_conversion_with_exact_targets(self):
        raw = '| 名称 | 值 |\n|---|---|\n| A | [链接][r] |\n\n[r]: https://example.invalid/a(b)?q=%20#end'
        result = display_text(raw)
        self.assertIn('值：链接\n\n    <https://example.invalid/a(b)?q=%20#end>', result)
        self.assertNotIn('[r]', result)
        self.assertEqual(display_text(result), result)

    def test_large_repeated_table_header_expansion_stops_at_explicit_source_fallback(self):
        raw = '| ' + 'H' * 8000 + ' | B |\n|---|---|\n' + '| x | y |\n' * 200
        result = display_text(raw)
        self.assertIn('表格字段展开超过展示上限', result)
        self.assertIn(raw, result)
        self.assertLessEqual(len(result), 480000)
        self.assertEqual(display_text(result), result)

    def test_nested_quote_table_keeps_source_structure_without_claiming_mac_field_support(self):
        raw = '> | A | B |\n> |---|---|\n> | x | y |\n'
        self.assertEqual(display_text(raw), raw)

    def test_complex_headers_keep_source_instead_of_changing_inline_or_block_meaning(self):
        for header in ['# heading', '`code`', '**bold**', '[链接](https://example.invalid/x)', '*unclosed']:
            raw = f'| {header} | B |\n|---|---|\n| x | `value` |'
            self.assertEqual(display_text(raw), raw)

    def test_reference_growth_overflow_uses_explicit_literal_source_with_bounded_payloads(self):
        raw = '[x][r]。\n\n' * 1500 + '[r]: https://example.invalid/' + 'a' * 4000
        actual = display_text(raw)
        self.assertIn('引用链接展开超过展示上限', actual)
        self.assertIn(raw, actual)
        self.assertLessEqual(len(actual), 480000)
        parts = render_segments(raw)
        self.assertEqual(''.join(p.source for p in parts), actual)
        self.assertTrue(all(len(p.text) <= 8000 for p in parts))

    def test_reference_semantic_targets_match_without_visiting_or_encoding_urls(self):
        raw = '[引用][r]\n\n[r]: https://example.invalid/a(b)?q=%20&x=中文#part "说明"'
        result = display_text(raw)
        self.assertIn('https://example.invalid/a(b)?q=%20&x=中文#part', result)
        original = [c.attrGet('href') for t in MarkdownIt().parse(raw) for c in t.children or [] if c.type == 'link_open']
        self.assertIn('\n\n<https://example.invalid/a(b)?q=%20&x=中文#part>\n\n链接标题：`说明`', result)
        self.assertEqual(MarkdownIt().normalizeLink('https://example.invalid/a(b)?q=%20&x=中文#part'), original[0])
        rendered = [c.attrGet('href') for t in MarkdownIt().parse(result) for c in t.children or [] if c.type == 'link_open']
        self.assertEqual(rendered, original)
        self.assertEqual(display_text(result), result)
