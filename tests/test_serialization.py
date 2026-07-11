import json
import tempfile
import unittest
from pathlib import Path

from bokpilot.serialization import (
    decode_journal_line,
    decode_source,
    decode_source_vat,
    decode_suggestion_vat,
    encode_journal_line,
    encode_source,
    encode_source_vat,
    encode_suggestion_vat,
)
from bokpilot.store import WorkspaceStore


FIXTURE = Path(__file__).parent / "fixtures" / "workspaces" / "v1-workspace.json"


class SerializationTest(unittest.TestCase):
    def test_decode_source_accepts_legacy_major_amount(self):
        workspace = json.loads(FIXTURE.read_text(encoding="utf-8"))

        source = decode_source(workspace["items"][0]["raw"])

        self.assertEqual(source.amount.minor, -24900)
        self.assertEqual(source.amount.currency, "SEK")

    def test_encode_source_writes_only_schema_v2_amount(self):
        workspace = json.loads(FIXTURE.read_text(encoding="utf-8"))
        legacy = workspace["items"][0]["raw"]

        encoded = encode_source(decode_source(legacy), template=legacy)

        self.assertEqual(encoded["amount_minor"], -24900)
        self.assertEqual(encoded["currency"], "SEK")
        self.assertNotIn("amount", encoded)

    def test_source_vat_codec_upgrades_legacy_major_amount(self):
        workspace = json.loads(FIXTURE.read_text(encoding="utf-8"))
        legacy = workspace["items"][0]["raw"]

        encoded = encode_source_vat(decode_source_vat(legacy), template=legacy)

        self.assertEqual(encoded["vat_amount_minor"], 4980)
        self.assertNotIn("vat_amount", encoded)

    def test_suggestion_vat_codec_upgrades_legacy_major_amount(self):
        workspace = json.loads(FIXTURE.read_text(encoding="utf-8"))
        legacy = workspace["items"][0]["suggestion"]

        encoded = encode_suggestion_vat(decode_suggestion_vat(legacy), template=legacy)

        self.assertEqual(encoded["vat_amount_minor"], 4980)
        self.assertNotIn("vat_amount", encoded)

    def test_journal_codec_upgrades_legacy_major_amounts(self):
        workspace = json.loads(FIXTURE.read_text(encoding="utf-8"))
        legacy = workspace["items"][0]["suggestion"]["journal_lines"][0]

        line = decode_journal_line(legacy)
        encoded = encode_journal_line(line)

        self.assertEqual(line.debit_minor, 19920)
        self.assertEqual(line.credit_minor, 0)
        self.assertEqual(encoded["debit_minor"], 19920)
        self.assertEqual(encoded["credit_minor"], 0)
        self.assertNotIn("debit", encoded)
        self.assertNotIn("credit", encoded)

    def test_store_loads_v1_fixture_as_v2_and_saves_only_v2_money(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.json"
            path.write_bytes(FIXTURE.read_bytes())
            store = WorkspaceStore(path)

            workspace = store.load()
            store.save(workspace)
            persisted = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(workspace["metadata"]["schema_version"], 2)
        raw = workspace["items"][0]["raw"]
        suggestion = workspace["items"][0]["suggestion"]
        line = suggestion["journal_lines"][0]
        self.assertEqual(raw["amount_minor"], -24900)
        self.assertEqual(raw["vat_amount_minor"], 4980)
        self.assertEqual(suggestion["vat_amount_minor"], 4980)
        self.assertEqual(line["debit_minor"], 19920)
        self.assertEqual(line["credit_minor"], 0)
        self.assertNotIn("amount", persisted["items"][0]["raw"])
        self.assertNotIn("vat_amount", persisted["items"][0]["raw"])
        self.assertNotIn("vat_amount", persisted["items"][0]["suggestion"])
        self.assertNotIn("debit", persisted["items"][0]["suggestion"]["journal_lines"][0])
        self.assertNotIn("credit", persisted["items"][0]["suggestion"]["journal_lines"][0])

    def test_codecs_reject_bool_and_float_schema_v2_minor_fields(self):
        for invalid in (True, 12.5):
            cases = (
                ("source", decode_source, {"amount_minor": invalid}),
                ("source_vat", decode_source_vat, {"vat_amount_minor": invalid}),
                ("suggestion_vat", decode_suggestion_vat, {"vat_amount_minor": invalid}),
                ("journal_debit", decode_journal_line, {"debit_minor": invalid}),
                ("journal_credit", decode_journal_line, {"credit_minor": invalid}),
            )
            for name, decoder, payload in cases:
                with self.subTest(name=name, invalid=invalid), self.assertRaises((TypeError, ValueError)):
                    decoder(payload)


if __name__ == "__main__":
    unittest.main()
