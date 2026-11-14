"""Intent persistence survives restart and refuses duplicate or unsafe storage."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from wx_clawbot.channels.http import ProtocolError
from wx_clawbot.control_journal import ControlJournal


class JournalTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'.tmp/control-journal-tests'
        base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'records';self.journal=ControlJournal(self.root)
        self.payload={'fingerprint':'f'*64,'target':{'thread_id':'fixture-thread'},
                      'before':{'model':'old'},'setting':{'field':'model','value':'new'}}

    def test_read_missing_has_no_storage_side_effect(self):
        self.assertIsNone(self.journal.read('one'))
        self.assertFalse(self.root.exists())

    def test_restart_keeps_intent_and_terminal_reply_without_creating_again(self):
        first,created=self.journal.begin('one',self.payload);self.assertTrue(created)
        again=ControlJournal(self.root)
        value,created=again.begin('one',self.payload)
        self.assertFalse(created);self.assertEqual(value,first)
        again.finish('one','confirmed','frozen reply',settings_event=True)
        value,created=ControlJournal(self.root).begin('one',self.payload)
        self.assertFalse(created);self.assertEqual(value['reply'],'frozen reply')
        self.assertEqual(self.root.stat().st_mode&0o777,0o700)
        self.assertEqual((self.root/(value['key']+'.json')).stat().st_mode&0o777,0o600)

    def test_capacity_never_evicts_unknown_or_terminal_record(self):
        self.journal.LIMIT=1
        self.journal.begin('one',self.payload)
        with self.assertRaises(ProtocolError):self.journal.begin('two',self.payload)
        self.assertEqual(self.journal.read('one')['phase'],'intent')
        self.assertIsNone(self.journal.read('two'))

    def test_oversized_payload_and_bad_state_fail_before_replace(self):
        with self.assertRaises(ProtocolError):
            self.journal.begin('one',dict(self.payload,extra='X'*16384))
        self.journal.begin('one',self.payload)
        with self.assertRaises(ProtocolError):self.journal.finish('one','unsupported','bad')
        self.assertEqual(self.journal.read('one')['phase'],'intent')

    def test_corrupt_or_public_record_fails_closed(self):
        value,_=self.journal.begin('one',self.payload);path=self.root/(value['key']+'.json')
        path.chmod(0o644)
        with self.assertRaises(ProtocolError):self.journal.read('one')
        path.chmod(0o600);path.write_text('{}')
        with self.assertRaises(ProtocolError):self.journal.read('one')

    def test_directory_sync_failure_leaves_intent_that_cannot_be_recreated(self):
        with patch.object(self.journal,'_sync_directory',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.journal.begin('one',self.payload)
        value,created=self.journal.begin('one',self.payload)
        self.assertFalse(created);self.assertEqual(value['phase'],'intent')

    def test_symlink_directory_and_record_are_refused(self):
        actual=Path(self.temp.name)/'actual';actual.mkdir(mode=0o700)
        self.root.symlink_to(actual,target_is_directory=True)
        with self.assertRaises(ProtocolError):self.journal.begin('one',self.payload)

    def test_second_process_cannot_hold_same_short_file_lease(self):
        from wx_clawbot.channels.private import private_directory,private_lease
        private_directory(self.root)
        with private_lease(self.root/'.lease'):
            code=('from pathlib import Path; from wx_clawbot.channels.private import private_lease; '
                  'c=private_lease(Path(__import__("sys").argv[1])); c.__enter__()')
            child=subprocess.run([sys.executable,'-I','-c',code,str(self.root/'.lease')],capture_output=True)
            self.assertNotEqual(child.returncode,0)
        self.journal.begin('one',self.payload)

    def test_real_child_exit_after_intent_does_not_authorize_recreation(self):
        code=('import os,sys; from wx_clawbot.control_journal import ControlJournal; '
              'ControlJournal(sys.argv[1]).begin("child",'+repr(self.payload)+'); os._exit(73)')
        child=subprocess.run([sys.executable,'-I','-c',code,str(self.root)],capture_output=True)
        self.assertEqual(child.returncode,73,child.stderr)
        value,created=self.journal.begin('child',self.payload)
        self.assertFalse(created);self.assertEqual(value['phase'],'intent')
