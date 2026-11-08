import tempfile
import unittest
from pathlib import Path

from wx_clawbot.config import Project
from wx_clawbot.routing import RouteError, Routes, Target


class RoutingTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp" / "w05-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ("one", "two", "one/sub child", "outside"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.one, self.two = Project("one", self.root / "one"), Project("two", self.root / "two")
        self.now = 0
        self.routes = Routes((self.one, self.two), ttl=10, clock=lambda: self.now)
        self.a = Target("fixture-session-a", "one", self.one.root)
        self.b = Target("fixture-session-b", "two", self.two.root)

    def test_no_target_is_not_guessed(self):
        with self.assertRaises(RouteError):
            self.routes.freeze("task")
        with self.assertRaises(RouteError):
            self.routes.resolve_cd("sub child")

    def test_focus_b_observe_a_and_detach_leave_b_input_target(self):
        r = self.routes
        r.focus(self.b, expected=r.revision)
        r.attach_confirmed(self.a, expected=r.revision)
        self.assertEqual(r.freeze("task").target, self.b)
        self.assertEqual(r.observer, self.a)
        revision = r.revision
        r.attach_confirmed(self.a, expected=revision)
        self.assertEqual(r.revision, revision)
        r.detach_confirmed(expected=r.revision)
        self.assertIsNone(r.observer)
        self.assertEqual(r.freeze("next task").target, self.b)

    def test_admitted_task_does_not_move_after_focus_changes(self):
        r = self.routes
        r.focus(self.a, expected=r.revision)
        admitted = r.freeze("original task")
        r.focus(self.b, expected=r.revision)
        self.assertEqual(admitted.target, self.a)
        self.assertEqual(r.freeze("new task").target, self.b)
        self.assertLess(admitted.route_revision, r.revision)

    def test_old_captured_list_does_not_resolve_using_new_numbering(self):
        old = self.routes.snapshot((self.a, self.b))
        self.routes.snapshot((self.b, self.a))
        self.assertEqual(self.routes.select(1, snapshot=old), self.a)
        self.assertEqual(self.routes.select(1), self.b)

    def test_expired_lists_and_non_integer_indices_are_refused(self):
        self.routes.snapshot((self.a, self.b))
        for index in (0, -1, 3, True, "1"):
            with self.assertRaises(RouteError):
                self.routes.select(index)
        self.now = 10
        with self.assertRaises(RouteError):
            self.routes.select(1)

    def test_list_refresh_preserves_input_observation_directory_mode_and_revision(self):
        r = self.routes
        r.focus(self.b, expected=r.revision)
        r.attach_confirmed(self.a, expected=r.revision)
        before = r.target, r.observer, r.project, r.cwd, r.mode, r.revision
        r.snapshot(())  # Even a filtered/empty list cannot clear a selection.
        self.assertEqual((r.target, r.observer, r.project, r.cwd, r.mode, r.revision), before)
        self.assertEqual(r.freeze("still reaches B").target, self.b)
        self.assertEqual(r.observer, self.a)

    def test_late_async_selection_cannot_overwrite_a_newer_route(self):
        r = self.routes
        older_revision = r.revision
        r.focus(self.b, expected=older_revision)
        with self.assertRaises(RouteError):
            r.focus(self.a, expected=older_revision)
        self.assertEqual(r.target, self.b)

    def test_relative_directory_uses_selected_directory_and_escape_is_refused(self):
        r = self.routes
        r.focus(Target("fixture-child", "one", self.one.root / "sub child"), expected=r.revision)
        project, cwd = r.resolve_cd("..")
        self.assertEqual((project, cwd), (self.one, self.one.root))
        before = r.target, r.cwd, r.revision
        (self.one.root / "escape").symlink_to(self.root / "outside", target_is_directory=True)
        for path in (str(self.one.root / "escape"), str(self.root / "outside"), "missing", ""):
            with self.assertRaises(RouteError):
                r.resolve_cd(path)
        self.assertEqual((r.target, r.cwd, r.revision), before)

    def test_deepest_registered_project_owns_overlapping_directory(self):
        child = Project("child", self.one.root / "sub child")
        routes = Routes((self.one, child))
        self.assertEqual(routes.resolve_cd(str(child.root)), (child, child.root))

    def test_single_send_does_not_change_focus_and_unfocus_does_not_cancel_observer(self):
        r = self.routes
        r.focus(self.b, expected=r.revision)
        r.attach_confirmed(self.a, expected=r.revision)
        self.assertEqual(r.freeze("single task", target=self.a).target, self.a)
        self.assertEqual(r.target, self.b)
        r.unfocus()
        self.assertEqual(r.observer, self.a)
        with self.assertRaises(RouteError):
            r.freeze("no automatic restoration")

    def test_unregistered_or_duplicate_session_targets_are_rejected(self):
        for target in (Target("bad", "unregistered", self.one.root),
                       Target("bad", "one", self.two.root), Target("bad", "one", self.one.root, "unknown")):
            with self.assertRaises(RouteError):
                self.routes.snapshot((target,))
        with self.assertRaises(RouteError):
            self.routes.snapshot((self.a, self.a))
