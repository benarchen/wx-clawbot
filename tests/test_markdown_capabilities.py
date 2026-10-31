"""Offline safety checks for the explicit capability probe, never live WeChat."""
import importlib.util
import copy
import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

spec = importlib.util.spec_from_file_location('md01_probe', Path(__file__).parent / 'integration/markdown_capabilities.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class MarkdownCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_existing_owner_context_has_no_invented_age_expiry(self):
        db = MagicMock()
        db.__enter__.return_value = db
        db.execute.return_value.fetchone.return_value = ('fixture-context', 1000, 1)
        with patch.object(probe, 'private_file'), patch.object(probe.schema, 'validate') as validate, \
                patch.object(probe.sqlite3, 'connect', return_value=db), patch.object(probe.time, 'time', return_value=100000):
            credentials = SimpleNamespace(owner_id='fixture-owner')
            self.assertEqual(probe.current_context(Path('/fixture/private'), credentials), ('fixture-context', 1000, 1))
            validate.assert_called_once_with(db, credentials)
            db.execute.return_value.fetchone.return_value = None
            with self.assertRaises(ValueError):
                probe.current_context(Path('/fixture/private'), credentials)

    def case(self):
        return {'phase': 'prepared', 'samples': [{**s, 'state': 'prepared', 'client_id': s['id'],
                'sha256': hashlib.sha256(s['text'].encode()).hexdigest()} for s in probe.load_samples()]}

    async def test_raw_fixture_is_sent_once_to_owner_and_frozen_before_each_call(self):
        case, saved = self.case(), []
        api = SimpleNamespace(send_text=AsyncMock(return_value={'message_id': 'fixture-message'}))
        owner = SimpleNamespace(owner_id='fixture-owner')
        await probe.send_once(case, lambda c: saved.append(copy.deepcopy(c)), api, owner, 'fixture-context')
        self.assertEqual(case['phase'], 'accepted')
        self.assertEqual(api.send_text.await_count, 3)
        for call, sample in zip(api.send_text.await_args_list, probe.load_samples()):
            self.assertEqual(call.kwargs['peer'], 'fixture-owner')
            self.assertEqual(call.kwargs['text'], sample['text'])
            self.assertTrue(any(r['samples'][i]['state'] == 'sending' for r in saved
                                for i in range(3) if r['samples'][i]['id'] == sample['id']))
        with self.assertRaises(ValueError):
            await probe.send_once(case, lambda c: None, api, owner, 'fixture-context')
        self.assertEqual(api.send_text.await_count, 3)

    async def test_unknown_send_stops_batch_and_refuses_replay(self):
        case, saved = self.case(), []
        api = SimpleNamespace(send_text=AsyncMock(side_effect=TimeoutError('uncertain')))
        owner = SimpleNamespace(owner_id='fixture-owner')
        with self.assertRaises(TimeoutError):
            await probe.send_once(case, lambda c: saved.append(copy.deepcopy(c)), api, owner, 'fixture-context')
        self.assertEqual(case['phase'], 'unknown')
        self.assertEqual([s['state'] for s in case['samples']], ['unknown', 'prepared', 'prepared'])
        with self.assertRaises(ValueError):
            await probe.send_once(case, lambda c: None, api, owner, 'fixture-context')
        self.assertEqual(api.send_text.await_count, 1)

    async def test_changed_frozen_body_is_refused_without_any_send(self):
        case = self.case()
        case['samples'][0]['text'] += 'changed'
        api = SimpleNamespace(send_text=AsyncMock())
        with self.assertRaises(ValueError):
            await probe.send_once(case, lambda c: None, api, SimpleNamespace(owner_id='fixture-owner'), 'context')
        api.send_text.assert_not_awaited()
