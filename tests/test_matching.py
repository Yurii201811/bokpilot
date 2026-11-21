import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from bokpilot.domain import EvidenceStatus, Money, SourceKind, SourceRecord
from bokpilot.matching import record_match_decision, suggest_matches
from bokpilot.repository import Repository


def record(identifier: str, day: int, amount: int, *, currency: str = "SEK", description: str = "Invoice 42") -> SourceRecord:
    return SourceRecord(
        id=identifier,
        kind=SourceKind.BANK_TRANSACTION if identifier.startswith("bank") else SourceKind.SUPPLIER_INVOICE,
        occurred_on=date(2026, 7, day),
        amount=Money(amount, currency),
        description=description,
        counterparty="Example AB",
        source_filename=f"{identifier}.txt",
        source_row=None,
        import_key=f"test:{identifier}",
        attachment_sha256=None,
        evidence_status=EvidenceStatus.LEGACY_UNAVAILABLE,
        extracted={"reference": "INV-42"},
    )


class MatchingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temporary.name) / "data" / "bokpilot.sqlite3")

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_amount_and_date_explain_score(self):
        self.repository.import_sources([record("bank-1", 10, -24900), record("invoice-1", 10, -24900)])

        suggestions = suggest_matches(self.repository, "bank-1")

        self.assertEqual(suggestions[0].matched_source_id, "invoice-1")
        self.assertIn("Exact amount", suggestions[0].reasons)
        self.assertIn("Same date", suggestions[0].reasons)

    def test_three_day_tolerance_partial_and_equal_candidates_are_retained(self):
        records = [
            record("bank-1", 10, -10000),
            record("invoice-1", 13, -10000),
            record("invoice-2", 10, -6000),
            record("invoice-3", 10, -10000),
        ]
        self.repository.import_sources(records)

        suggestions = suggest_matches(self.repository, "bank-1")
        ids = {suggestion.matched_source_id for suggestion in suggestions}

        self.assertEqual(ids, {"invoice-1", "invoice-2", "invoice-3"})
        partial = next(value for value in suggestions if value.matched_source_id == "invoice-2")
        self.assertIn("Possible partial amount", partial.reasons)

    def test_different_currency_is_never_suggested(self):
        self.repository.import_sources(
            [record("bank-1", 10, -24900), record("invoice-1", 10, -24900, currency="EUR")]
        )
        self.assertEqual(suggest_matches(self.repository, "bank-1"), ())

    def test_confirmed_match_is_returned_and_cannot_exceed_remaining_amount(self):
        self.repository.import_sources([record("bank-1", 10, -24900), record("invoice-1", 10, -24900)])
        suggestion = suggest_matches(self.repository, "bank-1")[0]

        decision = record_match_decision(
            self.repository,
            suggestion.id,
            source_id="bank-1",
            matched_source_id="invoice-1",
            decision="confirmed",
            matched_minor=20000,
            expected_version=1,
        )
        confirmed = suggest_matches(self.repository, "bank-1")[0]

        self.assertEqual(decision.match_version, 2)
        self.assertEqual(confirmed.status, "confirmed")
        with self.assertRaisesRegex(ValueError, "remaining"):
            record_match_decision(
                self.repository,
                suggestion.id + "-other",
                source_id="bank-1",
                matched_source_id="invoice-1",
                decision="confirmed",
                matched_minor=5000,
                expected_version=1,
            )

    def test_stale_match_version_is_rejected(self):
        self.repository.import_sources([record("bank-1", 10, -24900), record("invoice-1", 10, -24900)])
        suggestion = suggest_matches(self.repository, "bank-1")[0]
        record_match_decision(
            self.repository,
            suggestion.id,
            source_id="bank-1",
            matched_source_id="invoice-1",
            decision="rejected",
            matched_minor=0,
            expected_version=1,
        )

        with self.assertRaisesRegex(ValueError, "version conflict"):
            record_match_decision(
                self.repository,
                suggestion.id,
                source_id="bank-1",
                matched_source_id="invoice-1",
                decision="confirmed",
                matched_minor=24900,
                expected_version=1,
            )


if __name__ == "__main__":
    unittest.main()
