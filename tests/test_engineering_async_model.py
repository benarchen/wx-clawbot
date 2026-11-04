import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


class OwnedModelExceptionTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('owned_model_exception',
            self.project / 'tests/integration/engineering_async_model.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.reply = {'model':'fixture-original', 'modelProvider':'fixture-provider',
            'collaborationMode':{'mode':'default', 'settings':{'model':'fixture-original'}},
            'reasoningEffort':None, 'approvalPolicy':'never', 'approvalsReviewer':None,
            'sandbox':{'type':'readOnly'}, 'cwd':'/fixture'}

    def test_snapshot_cannot_mutate_original_sandbox_or_model_settings(self):
        saved = self.module.view(self.reply)
        saved['sandbox']['type'] = 'changed'
        saved['collaborationMode']['settings']['model'] = 'fixture-other'
        self.assertEqual(self.reply['sandbox'], {'type':'readOnly'})
        self.assertEqual(self.reply['collaborationMode']['settings']['model'], 'fixture-original')

    def test_missing_permission_or_provider_evidence_is_refused(self):
        for name in ('modelProvider', 'sandbox', 'approvalPolicy', 'collaborationMode'):
            with self.subTest(name=name):
                reply = {k:v for k,v in self.reply.items() if k != name}
                with self.assertRaises(ValueError):
                    self.module.view(reply)

    def test_malformed_sandbox_or_collaboration_settings_are_refused(self):
        for changes in ({'sandbox':None}, {'collaborationMode':{'mode':'default'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.module.view({**self.reply, **changes})

    def test_model_argument_without_explicit_exception_confirmation_has_no_side_effect(self):
        args = SimpleNamespace(action='run', release_manifest=None, model='fixture-requested',
            case_dir=self.project / '.tmp/unused-owned-model-case',
            report_dir=self.project / '.tmp/unused-owned-model-report',
            confirm_dedicated=True, confirm_temporary_model=False)
        with patch.object(self.module, 'private_directory') as directory, \
                patch.object(self.module.CodexConnection, 'connect', new=AsyncMock()) as connect:
            with self.assertRaises(ValueError):
                asyncio.run(self.module.main(args))
            directory.assert_not_called()
            connect.assert_not_awaited()
