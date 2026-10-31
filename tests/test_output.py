import unittest

from wx_clawbot.output import RESULT_LIMIT, bounded, display_text, display_segments, format_prose, native_output, split_text, render_segments


class OutputTests(unittest.TestCase):
    def test_terminal_output_excludes_commentary_but_keeps_final_and_legacy_text(self):
        turn = {"status": "completed", "items": [
            {"type": "agentMessage", "phase": "commentary", "text": "still running"},
            {"type": "agentMessage", "phase": "final_answer", "text": "final result"},
            {"type": "agentMessage", "text": "legacy result"}]}
        self.assertEqual(native_output(turn), "final result\nlegacy result")

    def test_interrupted_commentary_is_not_a_final_result_and_failure_error_survives(self):
        turn = {"status": "interrupted", "items": [
            {"type": "agentMessage", "phase": "commentary", "text": "still running"}]}
        self.assertEqual(native_output(turn), "原生任务已结束，没有最终文本结果。")
        failed = native_output({**turn, "status": "failed", "error": {"message": "EXACT_ERROR"}})
        self.assertEqual(failed, "原生错误：EXACT_ERROR")

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
                   "内容 ``中文x,y`` 测试。\n", "````markdown\n```text\n中文x,y\n```\n中文x,y\n````\n"]
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

    def test_display_standard_lf_leaves_code_bytes_literal_and_rendering_is_idempotent(self):
        code = 'value = "A B"\nprint(value)\n'
        text = "项目：fixture-one\n状态：仅展示\n\n```python\n" + code + "```\n\n结束。"
        result = display_text(text)
        self.assertIn("fixture-one\n\n状态", result)
        self.assertNotIn("\u2028", result)
        self.assertIn("\n\n```python\n" + code + "```\n\n结束。", result)
        self.assertEqual(display_text(result), result)

    def test_long_code_segments_are_individually_fenced_without_losing_any_code_lines(self):
        lines = [f"value_{index} = {index}\n" for index in range(3000)]
        chunks = display_segments("说明。\n\n```python\n" + "".join(lines) + "```\n\n结束。")
        actual = []
        for chunk in chunks:
            self.assertLess(len(chunk), 8000)
            if "value_" in chunk:
                self.assertEqual(chunk.count("```"), 2)
            actual.extend(line for line in chunk.splitlines(keepends=True) if line.startswith("value_"))
        self.assertEqual(actual, lines)

    def test_excessive_code_fence_cannot_overflow_transport_or_silently_lose_original_result(self):
        text = "`" * 10000 + "text\noriginal result\n" + "`" * 10000
        chunks = render_segments(text)
        self.assertTrue(all(len(chunk.text) < 8000 for chunk in chunks))
        self.assertTrue(all("原文片段" in chunk.text for chunk in chunks))
        self.assertEqual("".join(chunk.source for chunk in chunks), text)
        for chunk in chunks:
            self.assertEqual(chunk.text[len(chunk.before):len(chunk.text)-len(chunk.after)], chunk.source)
