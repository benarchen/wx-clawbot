import unittest

from wx_clawbot.commands import CommandError, parse_command


class CommandTests(unittest.TestCase):
    def test_ordinary_text_is_preserved_including_code_and_shell_characters(self):
        text = "检查以下命令，不执行：\n  echo '$HOME'; $(touch NEVER)\n"
        result = parse_command(text)
        self.assertEqual(result.name, "message")
        self.assertEqual(result.text, text)

    def test_aliases_have_the_same_command_meaning(self):
        for short, full, arguments in (("ss", "sessions", " fixture"), ("s", "send", " 2 test"),
                                       ("f", "focus", " 1"), ("uf", "unfocus", ""),
                                       ("a", "attach", " 1"), ("ua", "detach", "")):
            self.assertEqual(parse_command("/" + short + arguments), parse_command("/" + full + arguments))

    def test_send_freezes_index_and_preserves_payload_indentation_and_trailing_newline(self):
        result = parse_command("/send 2   first line\n    second line\n")
        self.assertEqual(result.index, 2)
        self.assertEqual(result.text, "  first line\n    second line\n")

    def test_directory_spaces_and_unicode_title_remain_text(self):
        self.assertEqual(parse_command("/cd /example/project with spaces").argument, "/example/project with spaces")
        self.assertEqual(parse_command("/new 架构分析 $(do-not-run)").argument, "架构分析 $(do-not-run)")

    def test_unknown_commands_and_command_shape_errors_are_not_tasks(self):
        for text in ("/rm -rf example", "/unknown", "/", "/focus 0", "/send -1 task",
                     "/send 1", "/focus 1 task", "/cd", "/help extra", "/detach 1",
                     "/approve", "/deny request extra", "/status first second"):
            with self.subTest(text=text), self.assertRaises(CommandError):
                parse_command(text)

    def test_answers_keep_exact_request_id_and_multi_question_json(self):
        text = '{"q1":["option"],"q2":["自由文本"]}'
        result = parse_command("/answer r-fixture " + text)
        self.assertEqual(result.argument, "r-fixture")
        self.assertEqual(result.text, text)

    def test_empty_control_chars_and_oversized_inputs_are_rejected(self):
        for value in (None, "", "  ", "bad\0input", "x" * 32001, "/new " + "x" * 129,
                      "/answer r-fixture", "/focus 9999999"):
            with self.subTest(value=type(value).__name__), self.assertRaises(CommandError):
                parse_command(value)
