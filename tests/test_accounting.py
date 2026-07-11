import unittest

from bokpilot.accounting import build_posting, posting_issues
from bokpilot.domain import (
    AccountingMethod,
    JournalLine,
    Money,
    PostingDraft,
    ReviewDecision,
    SourceKind,
    TransactionNature,
    VatTreatment,
)
from tests.helpers import approved_test_catalog, company_profile, source_record


def decision(
    nature: TransactionNature,
    account: str,
    vat: VatTreatment,
    vat_minor: int | None = None,
    *,
    note: str = "Synthetic test",
    risk_acknowledged: bool = True,
) -> ReviewDecision:
    return ReviewDecision(nature, account, vat, vat_minor, note, risk_acknowledged)


class PostingDraftTest(unittest.TestCase):
    def setUp(self):
        self.catalog = approved_test_catalog()

    def assert_balanced(self, draft):
        self.assertEqual(posting_issues(draft), ())
        self.assertEqual(
            sum(line.debit_minor for line in draft.lines),
            sum(line.credit_minor for line in draft.lines),
        )

    def test_invalid_account_is_an_issue(self):
        record = source_record("Unknown purchase", -10_000)

        draft = build_posting(
            record,
            decision(TransactionNature.EXPENSE, "NOT-BAS", VatTreatment.RATE_25, 2_000),
            company_profile(),
            self.catalog,
        )

        self.assertIn("invalid_account", draft.issues)
        self.assertEqual(draft.lines, ())

    def test_reviewer_cannot_select_reserved_control_accounts(self):
        cases = (
            (source_record("Bank row", 10_000), "1510"),
            (
                source_record("Customer invoice", 10_000, kind=SourceKind.CUSTOMER_INVOICE),
                "1930",
            ),
            (
                source_record("Supplier invoice", -10_000, kind=SourceKind.SUPPLIER_INVOICE),
                "2440",
            ),
        )
        for record, account in cases:
            nature = (
                TransactionNature.EXPENSE
                if record.amount.minor < 0
                else TransactionNature.REVENUE
            )
            with self.subTest(kind=record.kind, account=account):
                draft = build_posting(
                    record,
                    decision(nature, account, VatTreatment.RATE_0),
                    company_profile(AccountingMethod.ACCRUAL),
                    self.catalog,
                )
                self.assertIn("reserved_control_account", draft.issues)
                self.assertEqual(draft.lines, ())

    def test_bank_expense_and_revenue_use_1930_and_balance_exactly(self):
        expense = build_posting(
            source_record("Software payment", -12_500),
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_25),
            company_profile(),
            self.catalog,
        )
        revenue = build_posting(
            source_record("Customer payment", 12_500),
            decision(TransactionNature.REVENUE, "3011", VatTreatment.RATE_25),
            company_profile(),
            self.catalog,
        )

        self.assert_balanced(expense)
        self.assert_balanced(revenue)
        self.assertEqual(expense.lines[-1].account, "1930")
        self.assertEqual(revenue.lines[0].account, "1930")
        self.assertEqual(sum(line.debit_minor for line in expense.lines), 12_500)
        self.assertEqual(sum(line.credit_minor for line in revenue.lines), 12_500)

    def test_accrual_customer_and_supplier_invoices_use_control_accounts(self):
        customer = build_posting(
            source_record("Customer invoice", 12_500, kind=SourceKind.CUSTOMER_INVOICE),
            decision(TransactionNature.REVENUE, "3011", VatTreatment.RATE_25),
            company_profile(AccountingMethod.ACCRUAL),
            self.catalog,
        )
        supplier = build_posting(
            source_record("Supplier invoice", -12_500, kind=SourceKind.SUPPLIER_INVOICE),
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_25),
            company_profile(AccountingMethod.ACCRUAL),
            self.catalog,
        )

        self.assert_balanced(customer)
        self.assert_balanced(supplier)
        self.assertEqual(customer.lines[0].account, "1510")
        self.assertEqual(supplier.lines[-1].account, "2440")
        self.assertNotIn("1930", {line.account for line in customer.lines + supplier.lines})

    def test_cash_method_invoice_waits_for_matched_bank_payment(self):
        invoice = build_posting(
            source_record("Customer invoice", 12_500, kind=SourceKind.CUSTOMER_INVOICE),
            decision(TransactionNature.REVENUE, "3011", VatTreatment.RATE_25),
            company_profile(AccountingMethod.CASH),
            self.catalog,
        )
        payment = build_posting(
            source_record("Matched customer payment", 5_000, matched_source_id="invoice-1"),
            decision(TransactionNature.REVENUE, "3011", VatTreatment.RATE_25),
            company_profile(AccountingMethod.CASH),
            self.catalog,
        )

        self.assertIn("cash_method_invoice_requires_payment", invoice.issues)
        self.assertEqual(invoice.lines, ())
        self.assert_balanced(payment)
        self.assertEqual(payment.lines[0].debit_minor, 5_000)

    def test_accrual_matched_partial_payments_settle_control_accounts(self):
        customer_payment = build_posting(
            source_record("Partial customer payment", 5_000, matched_source_id="customer-invoice-1"),
            decision(TransactionNature.REVENUE, "3011", VatTreatment.RATE_0),
            company_profile(AccountingMethod.ACCRUAL),
            self.catalog,
        )
        supplier_payment = build_posting(
            source_record("Partial supplier payment", -4_000, matched_source_id="supplier-invoice-1"),
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_0),
            company_profile(AccountingMethod.ACCRUAL),
            self.catalog,
        )
        unmatched = build_posting(
            source_record("Unmatched accrual payment", 5_000),
            decision(TransactionNature.REVENUE, "3011", VatTreatment.RATE_0),
            company_profile(AccountingMethod.ACCRUAL),
            self.catalog,
        )

        self.assert_balanced(customer_payment)
        self.assert_balanced(supplier_payment)
        self.assertEqual(
            [(line.account, line.debit_minor, line.credit_minor) for line in customer_payment.lines],
            [("1930", 5_000, 0), ("1510", 0, 5_000)],
        )
        self.assertEqual(
            [(line.account, line.debit_minor, line.credit_minor) for line in supplier_payment.lines],
            [("2440", 4_000, 0), ("1930", 0, 4_000)],
        )
        self.assertIn("accrual_bank_payment_requires_match", unmatched.issues)
        self.assertEqual(unmatched.lines, ())

    def test_rate_zero_override_does_not_reuse_source_vat(self):
        record = source_record(
            "VAT override",
            -10_000,
            source_vat=VatTreatment.RATE_25,
            source_vat_minor=2_000,
        )

        draft = build_posting(
            record,
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_0),
            company_profile(),
            self.catalog,
        )

        self.assert_balanced(draft)
        self.assertNotIn("2641", {line.account for line in draft.lines})
        self.assertEqual(draft.lines[0].debit_minor, 10_000)

    def test_matching_source_vat_is_preserved_but_changed_rate_is_recalculated(self):
        record = source_record(
            "Source VAT",
            -10_000,
            source_vat=VatTreatment.RATE_25,
            source_vat_minor=1_900,
        )
        matching = build_posting(
            record,
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_25),
            company_profile(),
            self.catalog,
        )
        changed = build_posting(
            record,
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_12),
            company_profile(),
            self.catalog,
        )

        self.assert_balanced(matching)
        self.assert_balanced(changed)
        self.assertEqual(next(line.debit_minor for line in matching.lines if line.account == "2641"), 1_900)
        self.assertNotEqual(next(line.debit_minor for line in changed.lines if line.account == "2641"), 1_900)

    def test_high_risk_non_operating_posting_rejects_vat_rate(self):
        draft = build_posting(
            source_record("Owner funding", 10_000, high_risk=True),
            decision(TransactionNature.OWNER_MOVEMENT, "6991", VatTreatment.RATE_25),
            company_profile(),
            self.catalog,
        )

        self.assertIn("vat_treatment_mismatch", draft.issues)
        self.assertEqual(draft.lines, ())

    def test_receipt_does_not_invent_a_bank_movement(self):
        draft = build_posting(
            source_record("Receipt only", -10_000, kind=SourceKind.RECEIPT),
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_25),
            company_profile(),
            self.catalog,
        )

        self.assertIn("source_kind_requires_payment", draft.issues)
        self.assertEqual(draft.lines, ())

    def test_required_issue_codes_are_reported(self):
        foreign = source_record("Foreign", -10_000, currency="EUR")
        unknown = source_record("Unknown", -10_000)
        excessive_vat = source_record("VAT", -10_000)
        risky = source_record("Owner movement", 10_000, high_risk=True)

        foreign_draft = build_posting(
            foreign,
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_25),
            company_profile(),
            self.catalog,
        )
        unknown_draft = build_posting(
            unknown,
            decision(TransactionNature.UNKNOWN, "5420", VatTreatment.UNKNOWN),
            company_profile(),
            self.catalog,
        )
        vat_draft = build_posting(
            excessive_vat,
            decision(TransactionNature.EXPENSE, "5420", VatTreatment.RATE_25, 10_001),
            company_profile(),
            self.catalog,
        )
        risk_draft = build_posting(
            risky,
            decision(
                TransactionNature.OWNER_MOVEMENT,
                "6991",
                VatTreatment.EXEMPT,
                note="",
                risk_acknowledged=False,
            ),
            company_profile(),
            self.catalog,
        )

        self.assertIn("unsupported_currency", foreign_draft.issues)
        self.assertIn("unknown_nature", unknown_draft.issues)
        self.assertIn("unknown_vat", unknown_draft.issues)
        self.assertIn("vat_exceeds_gross", vat_draft.issues)
        self.assertIn("missing_risk_acknowledgement", risk_draft.issues)
        self.assertIn("missing_high_risk_note", risk_draft.issues)

    def test_posting_issues_detects_unbalanced_lines(self):
        draft = PostingDraft(
            source_id="source-1",
            lines=(JournalLine("1930", "Bank", debit_minor=100),),
            rule_id=None,
            rule_version=None,
            issues=(),
        )

        self.assertEqual(posting_issues(draft), ("unbalanced_lines",))

    def test_invalid_vat_enum_value_is_unrepresentable(self):
        with self.assertRaises(ValueError):
            VatTreatment("999")


if __name__ == "__main__":
    unittest.main()
