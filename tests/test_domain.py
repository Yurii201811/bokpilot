import json
import unittest
from datetime import date
from decimal import Decimal

from bokpilot.domain import (
    AccountingMethod,
    CompanyProfile,
    EvidenceStatus,
    JournalLine,
    Money,
    SourceKind,
    SourceRecord,
    Suggestion,
    TransactionNature,
    VatTreatment,
)


class MoneyTest(unittest.TestCase):
    def test_minor_units_survive_json_round_trip_exactly(self):
        payload = Money(-24900, "sek").to_dict()

        self.assertEqual(payload, {"minor": -24900, "currency": "SEK"})
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_from_major_accepts_exact_values(self):
        self.assertEqual(Money.from_major("1248.75"), Money(124875, "SEK"))
        self.assertEqual(Money.from_major(Decimal("-249.00")), Money(-24900, "SEK"))

    def test_from_major_rejects_sub_minor_precision(self):
        with self.assertRaisesRegex(ValueError, "at most two decimal places"):
            Money.from_major("1.234")

    def test_minor_units_must_be_an_integer(self):
        with self.assertRaisesRegex(TypeError, "must be an integer"):
            Money(249.0, "SEK")  # type: ignore[arg-type]

    def test_currency_must_be_a_three_letter_code(self):
        with self.assertRaisesRegex(ValueError, "three-letter ISO code"):
            Money(24900, "kr")


class DomainTypeTest(unittest.TestCase):
    def test_accounting_enums_have_the_schema_v2_values(self):
        self.assertEqual([value.value for value in VatTreatment], ["unknown", "exempt", "0", "6", "12", "25"])
        self.assertEqual(SourceKind.BANK_TRANSACTION.value, "bank_transaction")
        self.assertEqual(EvidenceStatus.LEGACY_UNAVAILABLE.value, "legacy_unavailable")
        self.assertEqual(TransactionNature.OWNER_MOVEMENT.value, "owner_movement")
        self.assertEqual(AccountingMethod.ACCRUAL.value, "accrual")

    def test_source_profile_and_suggestion_use_exact_domain_values(self):
        source = SourceRecord(
            id="source-1",
            kind=SourceKind.BANK_TRANSACTION,
            occurred_on=date(2026, 7, 11),
            amount=Money(-24900),
            description="Fortnox subscription",
            counterparty="Fortnox AB",
            source_filename="bank.csv",
            source_row=2,
            import_key="bank.csv:2",
            attachment_sha256=None,
            evidence_status=EvidenceStatus.AVAILABLE,
            extracted={"amount": "-249,00"},
        )
        profile = CompanyProfile(
            name="Demo AB",
            accounting_method=AccountingMethod.CASH,
            fiscal_year_start=date(2026, 1, 1),
            fiscal_year_end=date(2026, 12, 31),
            currency="SEK",
            voucher_series="BP",
        )
        suggestion = Suggestion(
            nature=TransactionNature.EXPENSE,
            category="Software and cloud services",
            account="5420",
            account_name="Programvaror",
            vat=VatTreatment.RATE_25,
            vat_minor=4980,
            confidence=0.88,
            explanation="Rule-based draft.",
            risk_flags=(),
            rule_id="software",
            rule_version=1,
        )

        self.assertEqual(source.amount.minor, -24900)
        self.assertEqual(profile.accounting_method, AccountingMethod.CASH)
        self.assertEqual(suggestion.vat, VatTreatment.RATE_25)

    def test_journal_line_rejects_invalid_amount_sides(self):
        with self.assertRaisesRegex(ValueError, "cannot be both debit and credit"):
            JournalLine("1930", "Företagskonto", debit_minor=100, credit_minor=100)
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            JournalLine("1930", "Företagskonto", debit_minor=-1)


if __name__ == "__main__":
    unittest.main()
