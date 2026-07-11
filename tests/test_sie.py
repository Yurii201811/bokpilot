import unittest
from dataclasses import replace
from pathlib import Path

from bokpilot.domain import JournalLine
from bokpilot.sie import sie4i_bytes, sie_text
from tests.helpers import company_profile


class SieTest(unittest.TestCase):
    def packet(self, description="Ångström tjänst"):
        return {
            "review_id": "review-1",
            "source_id": "source-1",
            "date": "2026-07-01",
            "description": description,
            "posting_lines": [
                JournalLine("5420", "Programvaror", debit_minor=10000),
                JournalLine("1930", "Företagskonto", credit_minor=10000),
            ],
        }

    def test_sie4i_has_required_headers_cp437_and_balanced_voucher(self):
        profile = replace(company_profile(), name="Ångström AB", voucher_series="BP")
        content = sie4i_bytes(profile, [self.packet()])
        text = content.decode("cp437")

        with self.assertRaises(UnicodeDecodeError):
            content.decode("utf-8")
        for marker in (
            "#FLAGGA 0",
            '#PROGRAM "Bokpilot"',
            "#FORMAT PC8",
            "#GEN ",
            "#SIETYP 4",
            '#FNAMN "Ångström AB"',
            '#KONTO 1930 "Företagskonto"',
            '#VER "BP"',
            "#TRANS 5420 {} 100.00",
            "#TRANS 1930 {} -100.00",
        ):
            self.assertIn(marker, text)

    def test_sie_text_cannot_inject_records_and_invalid_tokens_fail(self):
        self.assertEqual(sie_text('hello\r\n#VER "x"'), "hello #VER 'x'")
        with self.assertRaisesRegex(ValueError, "control"):
            sie_text("bad\x01text")
        with self.assertRaisesRegex(ValueError, "voucher series"):
            sie4i_bytes(replace(company_profile(), voucher_series='A"\n#VER'), [self.packet()])
        with self.assertRaisesRegex(ValueError, "currency"):
            sie4i_bytes(replace(company_profile(), currency="EUR"), [self.packet()])
        with self.assertRaises(UnicodeEncodeError):
            sie4i_bytes(company_profile(), [self.packet("emoji 😀")])

    def test_synthetic_fixture_is_cp437_and_structurally_balanced(self):
        content = (Path(__file__).parent / "fixtures" / "sie" / "approved-packet.se").read_bytes()
        text = content.decode("cp437")
        self.assertIn("Ångström Bokpilot AB", text)
        self.assertEqual(text.count("#VER "), text.count("\r\n{\r\n"))
        self.assertEqual(text.count("\r\n{\r\n"), text.count("\r\n}\r\n"))


if __name__ == "__main__":
    unittest.main()
