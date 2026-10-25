import unittest
from types import SimpleNamespace

from wx_clawbot.hosts.identity import footer_thread_id


ONE = "01900000-0000-7000-8000-000000000001"
TWO = "01900000-0000-7000-8000-000000000002"


def screen(lines):
    return SimpleNamespace(number_of_lines=len(lines), line=lambda index: SimpleNamespace(string=lines[index]))


class FooterIdentityTests(unittest.TestCase):
    def test_footer_is_authority_even_when_history_contains_an_old_identity(self):
        value = screen(["history " + ONE, "› current draft", "  " + TWO + " · other status", "← for agents"])
        self.assertEqual(footer_thread_id(value), TWO)

    def test_history_and_draft_ids_do_not_replace_missing_footer_identity(self):
        for lines in ([ONE, "› " + TWO, "  model only", "shortcuts"],
                      ["› " + ONE, "shortcuts"], [ONE], []):
            self.assertIsNone(footer_thread_id(screen(lines)))

    def test_ambiguous_truncated_or_non_native_uuid_footer_fails_closed(self):
        for row in (ONE + " " + TWO, ONE[:-1], ONE.replace("-7000-", "-4000-"), "no identity"):
            self.assertIsNone(footer_thread_id(screen([row, "shortcuts"])))

    def test_footer_uuid_has_a_canonical_case(self):
        value = "019aaaaa-abcd-7abc-8abc-abcdef123456"
        self.assertEqual(footer_thread_id(screen([value.upper(), "shortcuts"])), value)
