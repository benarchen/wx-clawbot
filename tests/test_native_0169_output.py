"""Respect native presentation metadata without inventing unsupported UI actions."""
import unittest
from wx_clawbot.output import native_output

class NativeDisplayTests(unittest.TestCase):
    def test_legacy_and_explicit_unmoderated_output_remain_readable(self):
        for value in (None,{'moderated':False},{'moderated':False,'display':None}):
            turn={'status':'completed','items':[{'type':'agentMessage','text':'normal','moderation':value}]}
            self.assertEqual(native_output(turn),'normal')

    def test_moderated_unknown_or_display_directive_does_not_forward_body_or_error(self):
        for value in ({'moderated':True},{'moderated':False,'display':{'action':'unknown'}},{},True,'invalid'):
            turn={'status':'failed','items':[{'type':'agentMessage','text':'PRIVATE_BODY','moderation':value}],
                  'error':{'message':'PRIVATE_ERROR'}}
            text=native_output(turn)
            self.assertIn('原生客户端',text);self.assertNotIn('PRIVATE',text)

    def test_one_directive_blocks_the_complete_result_including_other_items(self):
        self.assertNotIn('PRIVATE',native_output({'items':[{'type':'agentMessage','text':'PRIVATE_NORMAL'},
            {'type':'agentMessage','text':'PRIVATE_MODERATED','moderation':{'moderated':True}}]}))
