import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from bokpilot.accounting import build_posting
from bokpilot.domain import ReviewDecision, TransactionNature, VatTreatment
from bokpilot.domain import JournalLine, PostingDraft
from bokpilot.repository import Repository
from bokpilot.review import approval_issues, record_duplicate_decision, record_review
from tests.helpers import approved_test_catalog, company_profile, source_record


class ReviewPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temporary.name) / "data" / "bokpilot.sqlite3")
        self.catalog = approved_test_catalog()
        self.profile = company_profile()

    def tearDown(self):
        self.temporary.cleanup()

    def decision(self, **overrides):
        values = {
            "nature": TransactionNature.EXPENSE,
            "account": "5420",
            "vat": VatTreatment.RATE_25,
            "vat_minor": None,
            "reviewer_note": "Checked synthetic evidence",
            "risk_acknowledged": True,
        }
        values.update(overrides)
        return ReviewDecision(**values)

    def test_approval_issues_cover_unknown_currency_account_vat_balance_and_risk(self):
        cases = (
            (self.decision(nature=TransactionNature.UNKNOWN), "unknown_nature"),
            (self.decision(vat=VatTreatment.UNKNOWN), "unknown_vat"),
            (self.decision(account="9999"), "invalid_account"),
            (self.decision(vat=VatTreatment.RATE_0, vat_minor=100), "vat_treatment_mismatch"),
            (self.decision(risk_acknowledged=False), "missing_risk_acknowledgement"),
        )
        for decision, expected in cases:
            record = source_record("Review", -10000, high_risk=expected == "missing_risk_acknowledgement")
            draft = build_posting(record, decision, self.profile, self.catalog)
            with self.subTest(expected=expected):
                self.assertIn(expected, {issue.code for issue in approval_issues(record, decision, draft)})

        foreign = replace(source_record("EUR", -10000), amount=replace(source_record("EUR", -10000).amount, currency="EUR"))
        draft = build_posting(foreign, self.decision(), self.profile, self.catalog)
        self.assertIn("unsupported_currency", {issue.code for issue in approval_issues(foreign, self.decision(), draft)})

        unbalanced = PostingDraft(
            record.id,
            (JournalLine("5420", "Programvaror", debit_minor=100),),
            None,
            None,
            (),
        )
        self.assertIn(
            "unbalanced_lines",
            {issue.code for issue in approval_issues(record, self.decision(), unbalanced)},
        )

    def test_approved_review_is_immutable_versioned_and_stale_safe(self):
        record = source_record("Software", -12500)
        self.repository.import_sources([record])
        decision = self.decision()

        result = record_review(
            self.repository,
            record.id,
            action="approved",
            decision=decision,
            profile=self.profile,
            catalog=self.catalog,
            expected_version=1,
        )

        self.assertEqual(result.item_version, 2)
        self.assertEqual(self.repository.table_count("reviews"), 1)
        history = self.repository.review_history(record.id)
        self.assertEqual(history[0]["decision_id"], result.decision_id)
        self.assertEqual(history[0]["prior_version"], 1)
        self.assertEqual(history[0]["action"], "approved")
        with self.assertRaisesRegex(ValueError, "version conflict"):
            record_review(
                self.repository,
                record.id,
                action="approved",
                decision=decision,
                profile=self.profile,
                catalog=self.catalog,
                expected_version=1,
            )
        self.assertEqual(self.repository.table_count("reviews"), 1)

    def test_rejection_requires_note_but_not_approval_eligibility(self):
        record = source_record("Unknown", -10000)
        self.repository.import_sources([record])
        with self.assertRaisesRegex(ValueError, "note"):
            record_review(
                self.repository,
                record.id,
                action="rejected",
                decision=self.decision(nature=TransactionNature.UNKNOWN, reviewer_note=""),
                profile=self.profile,
                catalog=self.catalog,
                expected_version=1,
            )
        result = record_review(
            self.repository,
            record.id,
            action="rejected",
            decision=self.decision(nature=TransactionNature.UNKNOWN, reviewer_note="Not a business cost"),
            profile=self.profile,
            catalog=self.catalog,
            expected_version=1,
        )
        self.assertEqual(result.status, "rejected")

    def test_duplicate_decisions_clear_one_gate_or_make_source_non_exportable(self):
        first = source_record("Monthly fee", -10000)
        second = replace(first, id="source-2", import_key="test:source-2")
        self.repository.import_sources([first, second])
        with self.repository.transaction() as transaction:
            candidates = transaction.create_duplicate_candidates([second.id])
        candidate_id = candidates[0]
        decision = self.decision()
        draft = build_posting(second, decision, self.profile, self.catalog)
        self.assertIn(
            "unresolved_duplicate",
            {issue.code for issue in approval_issues(second, decision, draft, repository=self.repository)},
        )

        cleared = record_duplicate_decision(
            self.repository,
            second.id,
            candidate_id=candidate_id,
            decision="not_duplicate",
            note="Recurring monthly fee",
            expected_version=1,
        )
        self.assertEqual(cleared.item_version, 2)
        self.assertNotIn(
            "unresolved_duplicate",
            {issue.code for issue in approval_issues(second, decision, draft, repository=self.repository)},
        )

        confirmed = record_duplicate_decision(
            self.repository,
            second.id,
            candidate_id=candidate_id,
            decision="confirmed_duplicate",
            note="Correction after reviewing both files",
            expected_version=2,
        )
        self.assertEqual(confirmed.status, "duplicate")
        reversed_decision = record_duplicate_decision(
            self.repository,
            second.id,
            candidate_id=candidate_id,
            decision="not_duplicate",
            note="Supplier confirmed recurring charges",
            expected_version=3,
        )
        self.assertEqual(reversed_decision.status, "needs_review")


if __name__ == "__main__":
    unittest.main()
