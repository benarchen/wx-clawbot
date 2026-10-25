import unittest

from wx_clawbot.output import RESULT_LIMIT, bounded, format_prose, native_output, split_text


class OutputTests(unittest.TestCase):
    def test_segments_preserve_exact_text_prefer_lines_and_remain_bounded(self):
        text = ("first line\n" * 900) + "甲" * 9000 + "\nlast line"
        chunks = split_text(text)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(0 < len(chunk) <= 7000 for chunk in chunks))
        self.assertTrue(chunks[0].endswith("\n"))

    def test_plain_prose_has_deterministic_spacing_and_chinese_punctuation(self):
        self.assertEqual(format_prose("你好,Codex2测试:完成!\n内存32MB—正常。"),
                         "你好，Codex2 测试：完成！\n内存 32MB--正常。")

    def test_commands_code_paths_urls_and_quoted_values_remain_literal(self):
        samples = ["```python\nprint('中文x,y')\n```\n", "    result = '中文x,y'\n",
                   "$ codex queue --message '中文x,y'\n", "路径 `/fixture/a b.py`，命令 `/focus 1`。\n",
                   "https://example.invalid/path?q=原文,x\n", "/fixture/目录/a.py\n",
                   '{"answer":"中文x,y"}\n', '显示 "中文x,y"。\n', "print(中文x,y)\n", "echo 中文x,y\n",
                   "内容 ``中文x,y`` 测试。\n"]
        for sample in samples:
            self.assertEqual(format_prose(sample), sample)

    def test_native_failure_keeps_error_even_when_agent_output_exceeds_limit(self):
        text = native_output({"status": "failed", "items": [{"type": "agentMessage", "text": "start-" + "x" * 600000 + "-tail"}],
                              "error": {"message": "EXACT_FIXTURE_ERROR"}})
        self.assertTrue(text.startswith("start-"))
        self.assertIn("完整内容请在原终端查看", text)
        self.assertIn("-tail", text)
        self.assertTrue(text.endswith("原生错误：EXACT_FIXTURE_ERROR"))
        self.assertLessEqual(len(text), RESULT_LIMIT + 8020)

    def test_oversized_error_is_explicit_and_keeps_both_ends(self):
        text = bounded("ERROR_START" + "x" * 20000 + "ERROR_END", 8000)
        self.assertEqual(len(text), 8000)
        self.assertTrue(text.startswith("ERROR_START"))
        self.assertTrue(text.endswith("ERROR_END"))
