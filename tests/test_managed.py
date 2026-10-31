import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.channels.private import private_lease, read_json, write_json
from wx_clawbot.managed import EventStream, ErrorStream, open_log, record, run
from wx_clawbot.hosts.process import ProcessIdentity


class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        identity = ProcessIdentity(os.getpid(), (123, 456), '/fixture/python', 0)
        process = patch('wx_clawbot.managed.read_process', return_value=identity)
        process.start()
        self.addCleanup(process.stop)

    def logger(self, limit=1024 * 1024):
        logger, handler = open_log(self.root, limit=limit)
        self.addCleanup(handler.close)
        return logger

    def events(self):
        return [json.loads(line) for line in (self.root / 'logs/bridge.jsonl').read_text().splitlines()]

    def test_structured_output_filters_bodies_tokens_context_and_unknown_fields(self):
        stream = EventStream(self.logger())
        line = json.dumps({'status': 'failed', 'token': 'SECRET_TOKEN', 'message': 'SECRET_BODY',
                           'failures': [{'component': 'channel_receive', 'error_type': 'ProtocolError', 'body': 'SECRET_BODY'}]}) + '\n'
        stream.write(line[:15])
        stream.write(line[15:])
        event = self.events()[0]
        self.assertEqual(event['event'], 'failed')
        self.assertEqual(event['failures'], [{'component': 'channel_receive', 'error_type': 'ProtocolError'}])
        self.assertNotIn('SECRET', json.dumps(event))

    def test_malformed_oversized_and_arbitrary_output_cannot_break_or_leak(self):
        stream = EventStream(self.logger())
        for text in ['SECRET_BODY\n', '{"status": []}\n', '[]\n', '{"status":"unknown","message":"SECRET_BODY"}\n',
                     'x' * 20000, 'SECRET_BODY\n', '{"status":"capabilities","host":{"state":[]}}\n']:
            stream.write(text)
        self.assertEqual([e['event'] for e in self.events()], ['capabilities'])
        self.assertLessEqual(len(stream.buffer), 8192)

    def test_stderr_records_presence_without_raw_text_or_traceback(self):
        stream = ErrorStream(self.logger())
        stream.write('SECRET exception traceback\n')
        stream.write('SECRET again\n')
        self.assertEqual([e['event'] for e in self.events()], ['stderr_suppressed'])
        self.assertNotIn('SECRET', (self.root / 'logs/bridge.jsonl').read_text())

    def test_rotation_bounds_disk_and_keeps_every_file_private(self):
        logger = self.logger(400)
        for index in range(100):
            record(logger, 'process_start', sequence=index)
        files = list((self.root / 'logs').iterdir())
        self.assertEqual(len(files), 4)
        for path in files:
            self.assertLessEqual(path.stat().st_size, 400)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            for line in path.read_text().splitlines():
                json.loads(line)

    def test_symlink_or_public_log_refused_without_overwriting_target(self):
        directory = self.root / 'logs'
        directory.mkdir(mode=0o700)
        target = self.root / 'target'
        target.write_text('unchanged')
        link = directory / 'bridge.jsonl'
        link.symlink_to(target)
        with self.assertRaises(ProtocolError):
            open_log(self.root)
        self.assertEqual(target.read_text(), 'unchanged')

    def test_normal_stop_records_zero_exit_and_passes_original_config_and_state(self):
        config = self.root / 'config.json'
        with patch('wx_clawbot.managed.cli_main', return_value=0) as main:
            self.assertEqual(run(config, self.root), 0)
        self.assertEqual(main.call_args.args[0], ['serve', '--config', str(config), '--state-dir', str(self.root)])
        value = read_json(self.root / 'managed.json')
        self.assertEqual(value['exit_code'], 0)
        self.assertEqual(value['state'], 'exited')
        self.assertEqual(len(value['source_sha256']), 64)
        self.assertEqual([e['event'] for e in self.events()], ['process_start', 'process_exit'])

    def test_failure_records_class_and_nonzero_exit_without_exception_body(self):
        with patch('wx_clawbot.managed.cli_main', side_effect=ValueError('SECRET_TOKEN')):
            self.assertEqual(run(self.root / 'config', self.root), 1)
        self.assertEqual(read_json(self.root / 'managed.json')['exit_code'], 1)
        self.assertEqual(self.events()[1]['error_type'], 'ValueError')
        self.assertNotIn('SECRET', (self.root / 'logs/bridge.jsonl').read_text())

    def test_prior_unobserved_exit_is_reported_without_replaying_any_work(self):
        write_json(self.root / 'managed.json', {'version': 1, 'state': 'running', 'pid': 999999})
        with patch('wx_clawbot.managed.cli_main', return_value=0) as main:
            self.assertEqual(run(self.root / 'config', self.root), 0)
        self.assertEqual(main.call_count, 1)
        self.assertTrue(self.events()[0]['previous_exit_unobserved'])

    def test_second_managed_process_cannot_invoke_serve_or_replace_record(self):
        with private_lease(self.root / 'managed.lock'), patch('wx_clawbot.managed.cli_main') as main:
            with self.assertRaises(ProtocolError):
                run(self.root / 'config', self.root)
        main.assert_not_called()
        self.assertFalse((self.root / 'managed.json').exists())

    def test_sigterm_is_observed_exit_not_silent_disappearance(self):
        original = signal.getsignal(signal.SIGTERM)
        def stop(argv):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        with patch('wx_clawbot.managed.cli_main', side_effect=stop):
            self.assertEqual(run(self.root / 'config', self.root), 143)
        self.assertEqual(signal.getsignal(signal.SIGTERM), original)
        self.assertEqual(read_json(self.root / 'managed.json')['signal'], 15)
        self.assertEqual([e['event'] for e in self.events()], ['process_start', 'process_signal', 'process_exit'])

    def test_actual_cli_output_does_not_escape_to_stdout_or_stderr(self):
        def emit(argv):
            print(json.dumps({'status': 'foreground_ready', 'message': 'SECRET_BODY'}))
            print('SECRET_STDERR', file=sys.stderr)
            return 0
        with patch('wx_clawbot.managed.cli_main', side_effect=emit):
            self.assertEqual(run(self.root / 'config', self.root), 0)
        self.assertEqual([e['event'] for e in self.events()],
                         ['process_start', 'foreground_ready', 'stderr_suppressed', 'process_exit'])
        self.assertNotIn('SECRET', (self.root / 'logs/bridge.jsonl').read_text())
