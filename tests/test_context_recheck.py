import contextlib
from dataclasses import asdict
import hashlib
import io
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_runtime_state import RuntimeFixture
from wx_clawbot.channels.private import private_directory, read_json, write_json
from wx_clawbot.channels.wechat import BusinessError, DeliveryUnknown, SessionExpired
from test_wechat_state import message


sys.path.insert(0, str(Path(__file__).parent / 'integration'))
import w08_context_recheck as recheck


class ContextRecheckTests(RuntimeFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        write_json(self.root / 'credentials.json', {'version': 1, 'owner_confirmed': True,
                                                   'credentials': asdict(self.credentials)})
        self.source = private_directory(self.root / 'original')
        self.output = self.root / 'immediate'
        old = {'phase': 'no_rejection_observed_within_schedule',
               'binding': [self.credentials.bot_id, self.credentials.owner_id],
               'old_context': 'synthetic-old', 'created_ms': int((time.time()-180*3600)*1000),
               'attempts': [{'state': 'accepted'}] * 3}
        write_json(self.source / 'case.json', old)
        write_json(self.source / 'followup-plan.json', {'phase': 'waiting', 'attempts': 0,
            'waiting_pid': 1, 'source_created_ms': old['created_ms'],
            'old_context_sha256': hashlib.sha256(b'synthetic-old').hexdigest(),
            'credential_file_sha256': recheck.digest(self.root / 'credentials.json')})
        self.original = {name: (self.source / name).read_bytes() for name in ('case.json', 'followup-plan.json')}
        self.args = SimpleNamespace(action='observe', report_dir=self.output, state_dir=self.root,
                                    source_dir=self.source, confirm_owner_once=True)
        self.api = SimpleNamespace(send_text=AsyncMock(return_value={'ret': 0, 'message_id': 7}))

    def prepare(self):
        with patch.object(recheck.os, 'kill', side_effect=ProcessLookupError):
            return recheck.prepare(self.args)

    async def execute(self):
        with patch.object(recheck.observation, 'WeixinHttp', return_value=SimpleNamespace(close=AsyncMock())), \
                patch.object(recheck.observation, 'WechatApi', return_value=self.api), contextlib.redirect_stdout(io.StringIO()):
            return await recheck.execute(self.args)

    async def test_new_once_observation_keeps_original_records_and_cannot_replay(self):
        self.prepare()
        result = await self.execute()
        self.assertEqual(result['results'][0]['state'], 'accepted')
        self.assertFalse(result['natural_expiry_proven'])
        self.assertEqual(self.api.send_text.await_count, 1)
        self.assertTrue(result['source_records_unchanged'])
        for name, data in self.original.items():
            self.assertEqual((self.source / name).read_bytes(), data)
        with self.assertRaises(ValueError):
            await self.execute()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.api.send_text.await_count, 1)

    async def test_expired_window_and_changed_source_prevent_http(self):
        self.prepare()
        plan = read_json(self.output / 'plan.json')
        plan['not_after'] = time.time()-1
        write_json(self.output / 'plan.json', plan, replace=True)
        self.assertEqual((await self.execute())['phase'], 'missed_immediate_window_no_send')
        self.api.send_text.assert_not_awaited()
        source = read_json(self.source / 'case.json'); source['phase'] = 'held'
        write_json(self.source / 'case.json', source, replace=True)
        with self.assertRaises(ValueError):
            await self.execute()

    async def test_credential_change_and_modified_prepared_case_prevent_http(self):
        self.prepare()
        case = read_json(self.output / 'case.json'); case['old_context'] = 'changed'
        write_json(self.output / 'case.json', case, replace=True)
        with self.assertRaises(ValueError):
            await self.execute()
        credentials = read_json(self.root / 'credentials.json'); credentials['owner_confirmed'] = False
        write_json(self.root / 'credentials.json', credentials, replace=True)
        with self.assertRaises(ValueError):
            await self.execute()
        self.api.send_text.assert_not_awaited()

    async def test_unknown_never_retries_or_enters_fresh_recovery(self):
        self.prepare()
        self.api.send_text.side_effect = DeliveryUnknown('synthetic uncertain ACK')
        self.assertEqual((await self.execute())['phase'], 'send_unknown_no_retry')
        self.args.action = 'recover'
        with self.assertRaises(ValueError):
            await self.execute()
        self.assertEqual(self.api.send_text.await_count, 1)

    async def test_actual_rejection_requires_new_owner_context_and_recovers_only_once(self):
        self.prepare()
        self.api.send_text.side_effect = BusinessError(-2)
        self.assertEqual((await self.execute())['phase'], 'old_context_rejected')
        self.args.action = 'recover'
        with self.assertRaises(ValueError):
            await self.execute()
        self.assertEqual(self.api.send_text.await_count, 1)
        await self.state.accept_batch({'ret': 0, 'msgs': [message(100, context='synthetic-fresh',
            created=int((time.time()+.01)*1000))]}, phase='runtime')
        self.api.send_text.side_effect = None
        result = await self.execute()
        self.assertEqual(result['phase'], 'fresh_after_old_rejection_accepted')
        self.assertEqual(self.api.send_text.call_args.kwargs['context_token'], 'synthetic-fresh')
        with self.assertRaises(ValueError):
            await self.execute()
        self.assertEqual(self.api.send_text.await_count, 2)

    async def test_account_expiry_does_not_trigger_context_recovery(self):
        self.prepare()
        self.api.send_text.side_effect = SessionExpired(-14)
        self.assertEqual((await self.execute())['phase'], 'binding_expired_not_context_proof')
        self.args.action = 'recover'
        with self.assertRaises(ValueError):
            await self.execute()
        self.assertEqual(self.api.send_text.await_count, 1)

    async def test_prepare_refuses_live_waiter_and_unapproved_send(self):
        with patch.object(recheck.os, 'kill'):
            with self.assertRaises(ValueError):
                recheck.prepare(self.args)
        self.args.confirm_owner_once = False
        with self.assertRaises(ValueError):
            self.prepare()
        self.api.send_text.assert_not_awaited()
