import hashlib
import asyncio
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

from wx_clawbot import schema
from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.private import private_directory, private_lease
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.runtime_state import RuntimeState
from wx_clawbot.cli import main


class SchemaTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp" / "schema-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = private_directory(Path(self.temp.name))
        self.path = self.root / "runtime.sqlite3"
        self.path.touch(mode=0o600)
        self.credentials = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript((Path(__file__).parent / "fixtures/runtime-v1.sql").read_text())
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("INSERT INTO channel VALUES(1,'fixture-bot','fixture-owner','saved-cursor')")
            db.execute("INSERT INTO inbox VALUES('7','original input','fixture-context',100,1,1,'handled',0)")
            db.execute("INSERT INTO reply_context VALUES(1,'fixture-context',100,1)")
            db.execute("""INSERT INTO tasks VALUES('fixture-task','7','fixture-client','{}','fixture-thread',
                'original input','queued','fixture-queue',NULL,1,1)""")
            for event_id, state in (("accepted-event", "accepted"), ("unknown-event", "unknown"),
                                     ("sending-event", "sending"), ("pending-event", "pending")):
                db.execute("INSERT INTO outbox VALUES(?,?,1,?,'fixture-context',?,NULL,'reply',1)",
                           (event_id, "original reply", state, str(2**64 - 1) if state == "accepted" else None))
            db.commit()

    def snapshot(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as db:
            return {name: db.execute(f"SELECT {','.join(sorted(columns))} FROM {name} ORDER BY rowid").fetchall()
                    for name, columns in schema.V1_COLUMNS.items()}

    def test_plan_is_read_only_and_preserves_all_rows(self):
        before = self.path.read_bytes(), self.snapshot()
        report = schema.inspect(self.root, self.credentials)
        self.assertEqual(report["status"], "upgrade_available")
        self.assertEqual(report["add_tables"], ["routes", "interactions", "delivery_attempts", "attachments", *schema.V5_COLUMNS, *schema.V6_COLUMNS])
        self.assertEqual(report["row_counts"]["tasks"], 1)
        self.assertFalse((self.root / "backups").exists())
        self.assertEqual((self.path.read_bytes(), self.snapshot()), before)

    def test_upgrade_keeps_task_and_delivery_states_and_a_verified_v1_backup(self):
        before = self.snapshot()
        report = schema.upgrade(self.root, self.credentials)
        self.assertEqual(report["status"], "upgraded")
        self.assertEqual(self.snapshot(), before)
        backup = self.root / report["backup"]
        self.assertEqual(self.snapshot(backup), before)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(schema.validate(db, self.credentials), schema.VERSION)
            digest = db.execute("SELECT body_sha256 FROM inbox").fetchone()[0]
            self.assertEqual(digest, hashlib.sha256(b"original input").hexdigest())
            attempts = db.execute("SELECT state,started_at,finished_at,provenance FROM delivery_attempts ORDER BY state").fetchall()
            self.assertEqual(attempts, [(s, None, None, "legacy-v1") for s in ("accepted", "sending", "unknown")])
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(schema.validate(db, self.credentials), 1)

    def test_transaction_failure_restores_original_schema_and_data_without_overwriting_from_backup(self):
        before = self.snapshot()
        original = schema.apply_steps
        def fail_after_ddl(db, credentials):
            original(db, credentials)
            raise sqlite3.OperationalError("injected transaction failure")
        with patch.object(schema, "apply_steps", side_effect=fail_after_ddl):
            with self.assertRaises(sqlite3.OperationalError):
                schema.upgrade(self.root, self.credentials)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(schema.validate(db, self.credentials), 1)
        backups = list((self.root / "backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.snapshot(backups[0]), before)

    def test_running_consumer_prevents_upgrade(self):
        before = self.snapshot()
        with private_lease(self.root / "channel-consumer.lock"):
            with self.assertRaisesRegex(ProtocolError, "owns"):
                schema.upgrade(self.root, self.credentials)
        self.assertFalse((self.root / "backups").exists())
        self.assertEqual(self.snapshot(), before)

    def test_wrong_binding_or_unknown_schema_refuses_before_backup(self):
        wrong = Credentials("fixture-bot", "another-owner", self.credentials.base, "fixture-token")
        with self.assertRaisesRegex(ProtocolError, "binding"):
            schema.upgrade(self.root, wrong)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ProtocolError, "version"):
            schema.upgrade(self.root, self.credentials)
        self.assertFalse((self.root / "backups").exists())

    def test_backup_timeout_does_not_change_source_schema_or_rows(self):
        before = self.snapshot()
        with patch.object(schema.time, "monotonic", side_effect=[0, 20]):
            with self.assertRaises(TimeoutError):
                schema.upgrade(self.root, self.credentials)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(schema.validate(db, self.credentials), 1)
        self.assertEqual(self.snapshot(), before)

    def test_upgrade_is_idempotent_and_does_not_create_another_backup(self):
        first = schema.upgrade(self.root, self.credentials)
        again = schema.upgrade(self.root, self.credentials)
        self.assertEqual(again["status"], "current")
        self.assertEqual(list((self.root / "backups").glob("*.sqlite3")), [self.root / first["backup"]])

    def test_unexpected_personal_table_is_not_modified(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE personal(value TEXT)")
            db.execute("INSERT INTO personal VALUES('preserve')")
            db.commit()
        with self.assertRaisesRegex(ProtocolError, "tables"):
            schema.upgrade(self.root, self.credentials)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT value FROM personal").fetchone()[0], "preserve")

    def test_runtime_refuses_legacy_schema_without_changing_task_states(self):
        before = self.snapshot()
        async def open_legacy():
            with self.assertRaises(schema.UpgradeRequired):
                await RuntimeState.open(self.path, self.credentials)
        asyncio.run(open_legacy())
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "backups").exists())

    def test_runtime_after_upgrade_classifies_uncertain_sends_without_replaying(self):
        schema.upgrade(self.root, self.credentials)
        async def inspect_runtime():
            state = await RuntimeState.open(self.path, self.credentials)
            try:
                self.assertEqual((await state.tasks(task_id="fixture-task"))["state"], "unknown")
                attempts = await state._call(lambda: state.db.execute("SELECT state FROM delivery_attempts WHERE outbox_id='sending-event'").fetchone())
                self.assertEqual(attempts, ("unknown",))
                # Only the original known-pending reply can be claimed. Accepted
                # and uncertain sends remain separate and are not replayed.
                self.assertEqual((await state.claim_reply())["id"], "pending-event")
                self.assertIsNone(await state.claim_reply())
            finally:
                await state.close()
        asyncio.run(inspect_runtime())

    def test_cli_defaults_to_inspection_and_requires_apply_for_mutation(self):
        output = io.StringIO()
        with patch("wx_clawbot.channels.private.load_credentials", return_value=self.credentials), patch.object(schema, "upgrade") as apply, redirect_stdout(output):
            self.assertEqual(main(["migrate-state", "--state-dir", str(self.root)]), 0)
        apply.assert_not_called()
        self.assertIn("upgrade_available", output.getvalue())
        self.assertNotIn("fixture-owner", output.getvalue())
        with patch("wx_clawbot.channels.private.load_credentials", return_value=self.credentials), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["migrate-state", "--state-dir", str(self.root), "--apply"]), 0)
        self.assertEqual(schema.inspect(self.root, self.credentials)["status"], "current")

    def test_serve_reports_upgrade_required_without_invoking_migration(self):
        output = io.StringIO()
        with patch("wx_clawbot.cli.load_projects", return_value=()), \
                patch("wx_clawbot.service.serve", new=AsyncMock(side_effect=schema.UpgradeRequired("fixture"))), \
                patch.object(schema, "upgrade") as apply, redirect_stdout(output):
            result = main(["serve", "--config", "fixture.json", "--socket", "fixture.sock",
                           "--codex-executable", "fixture-codex"])
        self.assertEqual(result, 2)
        self.assertIn("upgrade_required", output.getvalue())
        apply.assert_not_called()
