"""Offline guards for the explicit AUD01 experiment; never opens a terminal."""

import asyncio
import importlib.util
import io
import json
import os
import shlex
import stat
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch


class RulesNativeGuardTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('rules_native', project / 'tests/integration/rules_native.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.root = project / '.tmp/native-diagnostics-rules-unused-offline-case'

    def test_plan_is_read_only_and_never_connects_or_creates_resources(self):
        with patch.object(self.module, 'HostLifecycle') as host, \
                patch.object(self.module, 'private_directory') as directory, \
                patch.object(self.module, 'protect') as protect, redirect_stdout(io.StringIO()) as output:
            asyncio.run(self.module.main(SimpleNamespace(action='plan',case_dir=self.root,confirm_dedicated=False)))
        self.assertEqual(json.loads(output.getvalue())['status'], 'rules_native_plan')
        host.assert_not_called()
        directory.assert_not_called()
        protect.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_missing_confirmation_is_rejected_before_any_state_or_host_access(self):
        with patch.object(self.module, 'HostLifecycle') as host, \
                patch.object(self.module, 'private_directory') as directory:
            with self.assertRaises(ValueError):
                asyncio.run(self.module.main(SimpleNamespace(action='prepare',case_dir=self.root,confirm_dedicated=False)))
        host.assert_not_called()
        directory.assert_not_called()

    def test_case_outside_project_temporary_root_is_refused(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.module.main(SimpleNamespace(action='plan',case_dir=Path('/tmp/outside-aud01'),
                                                        confirm_dedicated=True)))

    def test_existing_run_intent_is_rejected_before_authentication(self):
        self.assert_phase_rejected('run', 'running')

    def test_cleanup_without_tested_terminal_state_never_requests_authentication(self):
        self.assert_phase_rejected('cleanup', 'ready')

    def test_completed_boundaries_cannot_be_replayed_or_request_authentication(self):
        self.assert_phase_rejected('boundaries','tested',boundaries_completed=True)

    def assert_phase_rejected(self, action, phase, **fields):
        parent = Path(__file__).resolve().parents[1] / '.tmp/native-diagnostics-rules'
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            root = Path(temporary)
            self.module.write_json(root / 'case.json', {'phase': phase, **fields})
            with patch.object(self.module, 'HostLifecycle', side_effect=AssertionError('Unexpected authentication')) as host:
                with self.assertRaises(ValueError):
                    asyncio.run(self.module.main(SimpleNamespace(action=action,case_dir=root,confirm_dedicated=True)))
            host.assert_not_called()

    def test_startup_failure_is_captured_privately_before_any_native_execution(self):
        parent = Path(__file__).resolve().parents[1] / '.tmp/native-diagnostics-rules'
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='diagnostic space ', dir=parent) as temporary:
            root = Path(temporary)
            registry = self.module.DiagnosticRegistry(root)
            launch_id = 'a' * 32
            # A deliberately incomplete record must fail before launch_argv can exec anything.
            self.module.write_json(root / (launch_id + '.json'),
                                   {'version':1,'launch_id':launch_id,'phase':'handshaking'})
            with patch.dict(os.environ):
                os.environ.pop(self.module.ENVIRONMENT_KEY, None)
                command = registry.command(launch_id)
            # A GUI session may retain another release's environment. An explicit
            # development parent must not accidentally inherit it.
            result = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=10,
                                    env=os.environ | {self.module.ENVIRONMENT_KEY: '/fixture/unrelated-release.json'})
            self.assertNotEqual(result.returncode, 0)
            path = root / (launch_id + '.startup-error.txt')
            self.assertIn('KeyError', path.read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse((root / (launch_id + '.boot.json')).exists())

    def test_frozen_parent_manifest_is_explicit_in_child_command(self):
        parent = Path(__file__).resolve().parents[1] / '.tmp/native-diagnostics-rules'
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            root = Path(temporary)
            launch_id = 'b' * 32
            self.module.write_json(root / (launch_id + '.json'),
                                   {'version':1,'launch_id':launch_id,'phase':'handshaking'})
            value = '/fixture/frozen release/release.json'
            with patch.dict(os.environ, {self.module.ENVIRONMENT_KEY:value}):
                command = shlex.split(self.module.DiagnosticRegistry(root).command(launch_id))
            self.assertEqual(command[:2], ['/usr/bin/env', self.module.ENVIRONMENT_KEY + '=' + value])

    def test_invalid_parent_manifest_is_refused_before_host_or_state_access(self):
        with patch.object(self.module, 'verify_active', side_effect=ValueError('Wrong release')) as verify, \
                patch.object(self.module, 'HostLifecycle') as host, \
                patch.object(self.module, 'private_directory') as directory:
            with self.assertRaises(ValueError):
                asyncio.run(self.module.main(SimpleNamespace(action='prepare',case_dir=self.root,confirm_dedicated=True)))
        verify.assert_called_once()
        host.assert_not_called()
        directory.assert_not_called()

    def test_successful_prepare_persists_real_binding_paths_and_identity(self):
        from wx_clawbot.hosts.discovery import TerminalEndpoint
        from wx_clawbot.hosts.process import ProcessIdentity
        from wx_clawbot.sessions import SessionBinding
        parent = Path(__file__).resolve().parents[1] / '.tmp/native-diagnostics-rules'
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            root = Path(temporary)
            binding = SessionBinding(TerminalEndpoint('owned-terminal',
                ProcessIdentity(123, (10, 20), '/fixture/codex', 12), 'codex_candidate'),
                root / 'project', (1, 2), 'owned-thread', 'owned-session')
            host = SimpleNamespace(ensure=AsyncMock(),close=AsyncMock(),verified=Mock(),generation=1)
            native = SimpleNamespace(server_version='0.166.0',runtime_identity=(1,2),close=AsyncMock())
            registry = SimpleNamespace(load=Mock(return_value={
                'window_id':'owned-window','tab_id':'owned-tab','terminal_id':'owned-terminal'}))
            with patch.object(self.module,'verify_active'), patch.object(self.module,'protect',return_value=['safe']), \
                    patch.object(self.module,'HostLifecycle',return_value=host), \
                    patch.object(self.module,'discover_runtime',return_value=(root/'socket',root/'native')), \
                    patch.object(self.module.CodexConnection,'connect',new=AsyncMock(return_value=native)), \
                    patch.object(self.module,'ItermDirectory'), patch.object(self.module,'ItermWindowStarter'), \
                    patch.object(self.module,'DiagnosticRegistry',return_value=registry), \
                    patch.object(self.module,'VisibleStarter',return_value=SimpleNamespace(start=AsyncMock())), \
                    patch.object(self.module,'reconcile_launch',new=AsyncMock(return_value=binding)), \
                    redirect_stdout(io.StringIO()):
                asyncio.run(self.module.main(SimpleNamespace(action='prepare',case_dir=root,confirm_dedicated=True)))
            saved = self.module.read_json(root/'case.json')
            self.assertEqual(saved['phase'],'ready')
            self.assertEqual(saved['binding']['project'],str(root/'project'))
            self.assertEqual(saved['binding']['thread_id'],'owned-thread')
            self.assertEqual(saved['binding']['endpoint']['process']['pid'],123)

    def test_experiment_result_requires_exact_single_business_input(self):
        parent = Path(__file__).resolve().parents[1] / '.tmp/native-diagnostics-rules'
        for clients in (['own'],['own','foreign']):
            with self.subTest(clients=clients),tempfile.TemporaryDirectory(dir=parent) as temporary:
                root=Path(temporary);path=root/'case.json'
                intent={'case':'fixture','client':'own','state':'queued'};case={'results':[intent]}
                self.module.write_json(path,case)
                turn={'id':'turn','status':'completed','items':[
                    *[{'type':'userMessage','clientId':c} for c in clients],
                    {'type':'agentMessage','text':'AUD01_RULE_A'}]}
                native=SimpleNamespace(read_turns=AsyncMock(return_value={'data':[turn]}))
                with redirect_stdout(io.StringIO()):
                    if len(clients)==1:
                        asyncio.run(self.module.record_result(native,'thread',case,intent,path))
                    else:
                        with self.assertRaises(ValueError):
                            asyncio.run(self.module.record_result(native,'thread',case,intent,path))
                saved=self.module.read_json(path)['results'][0]
                self.assertEqual(saved['state'],'completed' if len(clients)==1 else 'unknown')
                self.assertEqual(saved['native_status'],'completed')
                self.assertEqual(saved['business_users'],len(clients))

    def test_connection_diagnostic_cannot_reopen_an_existing_ledger(self):
        parent=Path(__file__).resolve().parents[1]/'.tmp/native-diagnostics-rules'
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            root=Path(temporary);(root/'runtime.sqlite3').write_bytes(b'owned existing state')
            with patch.object(self.module,'HostLifecycle') as host:
                with self.assertRaises(FileExistsError):
                    asyncio.run(self.module.diagnose_connection(root))
            host.assert_not_called()
            self.assertEqual((root/'runtime.sqlite3').read_bytes(),b'owned existing state')
