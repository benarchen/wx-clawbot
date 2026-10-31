import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location('md01_reminder', Path(__file__).parent / 'integration/markdown_reminder.py')
reminder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reminder)


class MarkdownReminderTests(unittest.IsolatedAsyncioTestCase):
    def record(self):
        text = 'fixture reminder'
        return {'phase': 'scheduled', 'attempt': None, 'binding': ['fixture-bot', 'fixture-owner'],
                'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'client_id': 'fixture-client',
                'target_timestamp': 100, 'expires_timestamp': 150}

    async def test_exactly_once_owner_send_has_durable_intent_before_api(self):
        record, saved = self.record(), []
        async def send(*args, **kwargs):
            self.assertEqual(saved[-1]['phase'], 'send_intent')
            self.assertEqual(kwargs['peer'], 'fixture-owner')
            return {'message_id': 'fixture-message'}
        api = SimpleNamespace(send_text=AsyncMock(side_effect=send))
        credentials = SimpleNamespace(bot_id='fixture-bot', owner_id='fixture-owner')
        await reminder.send_due(record, lambda v: saved.append(copy.deepcopy(v)), api, credentials, 'context', 101)
        self.assertEqual(record['phase'], 'accepted')
        with self.assertRaises(ValueError):
            await reminder.send_due(record, lambda v: None, api, credentials, 'context', 102)
        self.assertEqual(api.send_text.await_count, 1)

    async def test_early_and_expired_do_not_send(self):
        api = SimpleNamespace(send_text=AsyncMock())
        credentials = SimpleNamespace(bot_id='fixture-bot', owner_id='fixture-owner')
        record = self.record()
        with self.assertRaises(ValueError):
            await reminder.send_due(record, lambda v: None, api, credentials, 'context', 99)
        await reminder.send_due(record, lambda v: None, api, credentials, 'context', 151)
        self.assertEqual(record['phase'], 'expired_no_send')
        api.send_text.assert_not_awaited()

    async def test_unknown_never_retries(self):
        record = self.record()
        api = SimpleNamespace(send_text=AsyncMock(side_effect=TimeoutError('uncertain')))
        credentials = SimpleNamespace(bot_id='fixture-bot', owner_id='fixture-owner')
        with self.assertRaises(TimeoutError):
            await reminder.send_due(record, lambda v: None, api, credentials, 'context', 101)
        self.assertEqual(record['phase'], 'unknown_no_retry')
        with self.assertRaises(ValueError):
            await reminder.send_due(record, lambda v: None, api, credentials, 'context', 102)
        self.assertEqual(api.send_text.await_count, 1)

    async def test_binding_and_body_changes_refuse_without_send(self):
        api = SimpleNamespace(send_text=AsyncMock())
        credentials = SimpleNamespace(bot_id='fixture-bot', owner_id='fixture-owner')
        for field, value in [('binding', ['different-bot', 'fixture-owner']), ('text', 'changed')]:
            record = self.record()
            record[field] = value
            with self.assertRaises(ValueError):
                await reminder.send_due(record, lambda v: None, api, credentials, 'context', 101)
        api.send_text.assert_not_awaited()
