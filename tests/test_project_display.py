"""Compact project lists retain identity, exceptions and diagnostic detail."""

import unittest

from markdown_it import MarkdownIt

from wx_clawbot.output import display_segments
from wx_clawbot.project_registry import describe


class ProjectDisplayTests(unittest.TestCase):
    def listing(self, rows, workspace="/fixture/projects", **extra):
        return {"status": "ok", "action": "list", "workspace_root": workspace,
                "projects": rows, **extra}

    def test_common_root_is_shown_once_and_names_have_real_line_breaks(self):
        rows = [{"alias": name, "root": "/fixture/projects/" + name, "available": True}
                for name in ("one", "two")]
        text = describe(self.listing(rows))
        rendered = display_segments(text)
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0].count("/fixture/projects"), 1)
        self.assertNotIn("可用", rendered[0])
        self.assertNotIn("/fixture/projects/one", rendered[0])
        html = MarkdownIt().render(rendered[0])
        # The real WeChat client folded Markdown hard breaks in the owner screenshot.
        self.assertIn("<p><strong>one</strong></p>", html)
        self.assertIn("<p><strong>two</strong></p>", html)
        self.assertIn("<strong>已注册项目 · 2 个</strong>", html)
        self.assertIn("/cd 项目名", html)

    def test_alias_mismatch_external_root_and_unavailable_item_keep_exact_paths(self):
        rows = [{"alias": "friendly", "root": "/fixture/projects/actual folder", "available": True},
                {"alias": "external", "root": "/fixture/elsewhere/external", "available": True},
                {"alias": "gone", "root": "/fixture/projects/gone", "available": False}]
        text = describe(self.listing(rows))
        for row in rows:
            self.assertIn(row["root"], text)
        self.assertIn("**gone** · ⚠️ 目录不可访问", text)
        self.assertEqual(text.count("⚠️"), 1)

    def test_legacy_configuration_does_not_guess_a_workspace(self):
        rows = [{"alias": name, "root": "/fixture/projects/" + name, "available": True}
                for name in ("one", "two")]
        text = describe(self.listing(rows, workspace=None))
        self.assertNotIn("总目录：", text)
        for row in rows:
            self.assertIn(row["root"], text)

    def test_empty_registry_is_explicit_and_has_no_enter_session_prompt(self):
        for workspace in (None, "/fixture/projects"):
            with self.subTest(workspace=workspace):
                text = describe(self.listing([], workspace=workspace))
                self.assertIn("0 个", text)
                self.assertIn("暂无已注册项目。", text)
                self.assertNotIn("/cd", text)

    def test_alias_underscores_and_path_backticks_remain_literal_after_rendering(self):
        root = "/fixture/project` space"
        row = {"alias": "_one_", "root": root + "/renamed` folder", "available": True}
        text = display_segments(describe(self.listing([row], workspace=root)))[0]
        html = MarkdownIt().render(text)
        self.assertIn("<strong>_one_</strong>", html)
        self.assertNotIn("<em>", html)
        self.assertIn("<code>" + root + "</code>", html)
        self.assertIn("<code>" + row["root"] + "</code>", html)

    def test_check_preserves_full_paths_status_problems_and_request_record(self):
        rows = [{"alias": "one", "root": "/fixture/projects/one", "available": True}]
        result = self.listing(rows, action="check", problems=["fixture diagnostic"],
                              request={"id": "fixture-request", "revision": 3})
        text = describe(result)
        self.assertIn("one：可用", text)
        self.assertIn(rows[0]["root"], text)
        self.assertIn("fixture diagnostic", text)
        self.assertIn("fixture-request", text)
        self.assertIn('"revision": 3', text)
        self.assertNotIn("/cd", text)

    def test_maximum_registry_segments_without_losing_names_or_bold_boundaries(self):
        names = ["p" + str(i).zfill(3) + "x" * 124 for i in range(256)]
        rows = [{"alias": name, "root": "/fixture/projects/" + name, "available": True}
                for name in names]
        segments = display_segments(describe(self.listing(rows)))
        self.assertGreater(len(segments), 1)
        combined = "".join(segments)
        self.assertNotIn("原文片段", combined)
        for name in names:
            self.assertIn(name, combined)
        bold_count = 0
        for segment in segments:
            self.assertLessEqual(len(segment), 8000)
            html = MarkdownIt().render(segment)
            self.assertEqual(html.count("<strong>"), html.count("</strong>"))
            bold_count += html.count("<strong>")
        self.assertEqual(bold_count, 257)
