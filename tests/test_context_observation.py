import contextlib
import importlib.util
import io
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_runtime_state import RuntimeFixture
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import BusinessError, DeliveryUnknown, SessionExpired


spec = importlib.util.spec_from_file_location("w08_context", Path(__file__).parent / "integration" / "w08_context.py")
observation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observation)


class ContextObservationTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        write_json(self.root / "credentials.json", {"version": 1, "owner_confirmed": True, "credentials": asdict(self.credentials)})
        self.report_dir = private_directory(self.root / "observation")
        self.args = SimpleNamespace(state_dir=self.root, report_dir=self.report_dir, action="run", wait=False)
        self.record = {"phase": "prepared", "binding": [self.credentials.bot_id, self.credentials.owner_id],
                       "old_context": "old-owner-context", "created_ms": int((time.time()-49*3600)*1000),
                       "probe_hours": [24, 36, 48], "attempts": [], "case_id": "FIXTURE"}
        write_json(self.report_dir / "case.json", self.record)
        self.api = SimpleNamespace(send_text=AsyncMock(return_value={"message_id": 7}))

    async def invoke(self):
        with patch.object(observation, "WeixinHttp", return_value=SimpleNamespace(close=AsyncMock())), patch.object(observation, "WechatApi", return_value=self.api), contextlib.redirect_stdout(io.StringIO()):
            await observation.run(self.args)
        return read_json(self.report_dir / "case.json")

    async def test_scheduled_observations_have_distinct_intents_and_completed_case_cannot_repeat(self):
        record = await self.invoke()
        self.assertEqual(record["phase"], "no_rejection_observed_within_schedule")
        self.assertEqual(self.api.send_text.await_count, 3)
        self.assertEqual(len({a["client_id"] for a in record["attempts"]}), 3)
        self.assertEqual([a["planned_age_hours"] for a in record["attempts"]], [24, 36, 48])
        self.assertTrue(all(49 <= a["observation_age_hours"] < 49.1 for a in record["attempts"]))
        self.assertTrue(all("实际源上下文年龄：49." in call.kwargs["text"] for call in self.api.send_text.await_args_list))
        with self.assertRaises(ValueError):
            await self.invoke()
        self.assertEqual(self.api.send_text.await_count, 3)

    async def test_uncertain_send_is_terminal_and_cannot_be_replayed(self):
        self.api.send_text.side_effect = DeliveryUnknown("injected lost ACK")
        record = await self.invoke()
        self.assertEqual(record["phase"], "send_unknown_no_retry")
        self.assertEqual(len(record["attempts"]), 1)
        with self.assertRaises(ValueError):
            await self.invoke()
        self.assertEqual(self.api.send_text.await_count, 1)

    async def test_recovery_requires_a_new_distinct_context_after_actual_rejection(self):
        self.api.send_text.side_effect = BusinessError(-2)
        rejected = await self.invoke()
        self.assertEqual(rejected["phase"], "old_context_rejected")
        self.args.action = "recover"
        with self.assertRaises(ValueError):
            await self.invoke()
        self.assertEqual(self.api.send_text.await_count, 1)
        await self.state._call(lambda: self.state.db.execute("INSERT INTO reply_context VALUES(1,?,?,?)",
            ("fresh-owner-context", int((time.time()+1)*1000), 1)))
        self.api.send_text.side_effect = None
        result = await self.invoke()
        self.assertEqual(result["phase"], "fresh_after_old_rejection_accepted")
        self.assertEqual(self.api.send_text.call_args.kwargs["context_token"], "fresh-owner-context")
        self.assertEqual(self.api.send_text.await_count, 2)

    async def test_binding_expiry_is_not_context_expiry_proof(self):
        self.api.send_text.side_effect = SessionExpired(-14)
        record = await self.invoke()
        self.assertEqual(record["phase"], "binding_expired_not_context_proof")
        self.args.action = "recover"
        with self.assertRaises(ValueError):
            await self.invoke()

    async def test_resume_skips_an_already_accepted_observation(self):
        self.record["attempts"] = [{"state": "accepted", "observation_age_hours": 24}]
        write_json(self.report_dir / "case.json", self.record, replace=True)
        result = await self.invoke()
        self.assertEqual(self.api.send_text.await_count, 2)
        self.assertEqual(result["attempts"][0]["observation_age_hours"], 24)  # Keep historical records intact.
        self.assertEqual([r["planned_age_hours"] for r in result["attempts"][1:]], [36, 48])
        self.assertTrue(all(49 <= r["observation_age_hours"] < 49.1 for r in result["attempts"][1:]))

    async def test_fresh_recovery_measures_the_new_source_context_not_the_old_one(self):
        now = time.time()
        self.record.update(phase="old_context_rejected", rejected_at=now-120,
                           attempts=[{"state":"rejected", "source":"old"}])
        write_json(self.report_dir / "case.json", self.record, replace=True)
        await self.state._call(lambda: self.state.db.execute("INSERT INTO reply_context VALUES(1,?,?,?)",
            ("fresh-owner-context", int((now-60)*1000), 1)))
        self.args.action = "recover"
        result = await self.invoke()
        attempt = result["attempts"][-1]
        self.assertEqual(attempt["source"], "fresh")
        self.assertIsNone(attempt["planned_age_hours"])
        self.assertTrue(0.016 <= attempt["observation_age_hours"] < 0.02)
        self.assertIn("实际源上下文年龄：0.0", self.api.send_text.call_args.kwargs["text"])

    async def test_operator_hold_prevents_late_scheduled_sends(self):
        self.record["phase"] = "held_pending_owner_account_check"
        write_json(self.report_dir / "case.json", self.record, replace=True)
        with self.assertRaises(ValueError):
            await self.invoke()
        self.api.send_text.assert_not_awaited()

    async def test_operator_hold_during_wait_stops_before_the_wire(self):
        self.record["created_ms"] = int(time.time()*1000)
        write_json(self.report_dir / "case.json", self.record, replace=True)
        self.args.wait = True
        async def freeze(_):
            record = read_json(self.report_dir / "case.json")
            record["phase"] = "held_pending_owner_account_check"
            write_json(self.report_dir / "case.json", record, replace=True)
        with patch.object(observation.asyncio, "sleep", side_effect=freeze):
            with self.assertRaisesRegex(ValueError, "superseded"):
                await self.invoke()
        self.api.send_text.assert_not_awaited()

    async def test_future_schedule_does_not_send_or_claim_an_expiry(self):
        self.record["created_ms"] = int(time.time()*1000)
        write_json(self.report_dir / "case.json", self.record, replace=True)
        record = await self.invoke()
        self.assertEqual(record["phase"], "prepared")
        self.assertFalse(record["attempts"])
        self.api.send_text.assert_not_awaited()

    async def test_binding_changed_during_wait_stops_before_any_send(self):
        from dataclasses import replace
        with patch.object(observation, "load_credentials", side_effect=[self.credentials, replace(self.credentials, owner_id="changed-fixture-owner")]):
            record = await self.invoke()
        self.assertEqual(record["phase"], "binding_changed_observation_stopped")
        self.api.send_text.assert_not_awaited()
