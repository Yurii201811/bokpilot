import unittest
from dataclasses import asdict

from bokpilot.domain import TransactionNature, VatTreatment
from bokpilot.rules import apply_account_override, classify_transaction
from bokpilot.rules import SAFE_SUGGESTION_RULES, suggest
from tests.helpers import source_record


class ClassificationRulesTest(unittest.TestCase):
    def test_safe_suggestions_do_not_infer_owner_transfer_or_unknown_purchases(self):
        owner = source_record("Owner deposit", 100_000)
        transfer = source_record("Transfer savings", 100_000)
        unmatched = source_record("Unmatched vendor", -10_000)
        unknown = source_record("Unknown purchase", -10_000)

        self.assertEqual(suggest(owner).nature, TransactionNature.UNKNOWN)
        self.assertEqual(suggest(transfer).vat, VatTreatment.UNKNOWN)
        self.assertEqual(suggest(unmatched).category, "Unclassified expense")
        self.assertEqual(suggest(unknown).vat, VatTreatment.UNKNOWN)
        self.assertNotIn("journal_lines", asdict(suggest(unknown)))

    def test_suggest_does_not_mutate_source_and_uses_token_boundaries(self):
        record = source_record("Unmatched vendor", -10_000)
        before = asdict(record)

        suggestion = suggest(record)

        self.assertEqual(asdict(record), before)
        self.assertEqual(suggestion.category, "Unclassified expense")
        self.assertIsNone(suggestion.account)

    def test_safe_rules_have_versioned_review_metadata(self):
        identifiers = {rule.rule_id for rule in SAFE_SUGGESTION_RULES}

        self.assertEqual(len(identifiers), len(SAFE_SUGGESTION_RULES))
        self.assertTrue(all(rule.version >= 1 for rule in SAFE_SUGGESTION_RULES))
        self.assertTrue(all(rule.source_note for rule in SAFE_SUGGESTION_RULES))
        self.assertTrue(all(rule.evidence_status == "pending_review" for rule in SAFE_SUGGESTION_RULES))
        self.assertTrue(all(rule.suggested_account for rule in SAFE_SUGGESTION_RULES))

    def test_schema_v2_source_creates_balanced_integer_minor_postings(self):
        suggestion = classify_transaction(
            {
                "date": "2026-05-02",
                "description": "Fortnox subscription May",
                "counterparty": "Fortnox AB",
                "amount_minor": -24900,
                "currency": "SEK",
            }
        )

        self.assertEqual(suggestion.bas_account, "5420")
        self.assertEqual(suggestion.vat_amount_minor, 4980)
        self.assertIs(type(suggestion.vat_amount_minor), int)
        debits = sum(line.debit_minor for line in suggestion.journal_lines)
        credits = sum(line.credit_minor for line in suggestion.journal_lines)
        self.assertEqual(debits, credits)
        payload = suggestion.to_dict()
        self.assertNotIn("vat_amount", payload)
        self.assertTrue(all("debit" not in line and "credit" not in line for line in payload["journal_lines"]))

    def test_software_expense_creates_balanced_vat_lines(self):
        suggestion = classify_transaction(
            {
                "date": "2026-05-02",
                "description": "Fortnox subscription May",
                "counterparty": "Fortnox AB",
                "amount_minor": -24900,
            }
        )

        self.assertEqual(suggestion.bas_account, "5420")
        self.assertEqual(suggestion.vat_amount_minor, 4980)
        debits = sum(line.debit_minor for line in suggestion.journal_lines)
        credits = sum(line.credit_minor for line in suggestion.journal_lines)
        self.assertEqual(debits, credits)

    def test_income_creates_output_vat_lines(self):
        suggestion = classify_transaction(
            {
                "date": "2026-05-05",
                "description": "Customer invoice 2026-104 paid",
                "counterparty": "Nordic Design Studio AB",
                "amount_minor": 1250000,
            }
        )

        self.assertEqual(suggestion.bas_account, "3011")
        self.assertEqual(suggestion.vat_amount_minor, 250000)
        accounts = {line.account for line in suggestion.journal_lines}
        self.assertIn("2611", accounts)
        self.assertIn("1930", accounts)

    def test_bank_fee_has_no_vat(self):
        suggestion = classify_transaction(
            {
                "date": "2026-05-06",
                "description": "Bankavgift foretagskonto",
                "amount_minor": -5900,
            }
        )

        self.assertEqual(suggestion.bas_account, "6570")
        self.assertEqual(suggestion.vat_amount_minor, 0)

    def test_reviewer_override_recalculates_account(self):
        suggestion = classify_transaction({"description": "Lunch with client", "amount_minor": -42000})
        item = {
            "raw": {"description": "Lunch with client", "amount_minor": -42000},
            "suggestion": suggestion.to_dict(),
        }

        updated = apply_account_override(item, "6991", "0")

        self.assertEqual(updated["suggestion"]["bas_account"], "6991")
        self.assertEqual(updated["suggestion"]["vat_amount_minor"], 0)


if __name__ == "__main__":
    unittest.main()
