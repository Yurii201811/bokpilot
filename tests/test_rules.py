from decimal import Decimal
import unittest

from bokpilot.rules import apply_account_override, classify_transaction


class ClassificationRulesTest(unittest.TestCase):
    def test_software_expense_creates_balanced_vat_lines(self):
        suggestion = classify_transaction(
            {
                "date": "2026-05-02",
                "description": "Fortnox subscription May",
                "counterparty": "Fortnox AB",
                "amount": -249.00,
            }
        )

        self.assertEqual(suggestion.bas_account, "5420")
        self.assertEqual(suggestion.vat_amount, Decimal("49.80"))
        debits = sum(line.debit for line in suggestion.journal_lines)
        credits = sum(line.credit for line in suggestion.journal_lines)
        self.assertEqual(debits, credits)

    def test_income_creates_output_vat_lines(self):
        suggestion = classify_transaction(
            {
                "date": "2026-05-05",
                "description": "Customer invoice 2026-104 paid",
                "counterparty": "Nordic Design Studio AB",
                "amount": 12500,
            }
        )

        self.assertEqual(suggestion.bas_account, "3011")
        self.assertEqual(suggestion.vat_amount, Decimal("2500.00"))
        accounts = {line.account for line in suggestion.journal_lines}
        self.assertIn("2611", accounts)
        self.assertIn("1930", accounts)

    def test_bank_fee_has_no_vat(self):
        suggestion = classify_transaction(
            {
                "date": "2026-05-06",
                "description": "Bankavgift foretagskonto",
                "amount": -59,
            }
        )

        self.assertEqual(suggestion.bas_account, "6570")
        self.assertEqual(suggestion.vat_amount, Decimal("0.00"))

    def test_reviewer_override_recalculates_account(self):
        suggestion = classify_transaction({"description": "Lunch with client", "amount": -420})
        item = {"raw": {"description": "Lunch with client", "amount": -420}, "suggestion": suggestion.to_dict()}

        updated = apply_account_override(item, "6991", "0")

        self.assertEqual(updated["suggestion"]["bas_account"], "6991")
        self.assertEqual(updated["suggestion"]["vat_amount"], 0.0)


if __name__ == "__main__":
    unittest.main()
