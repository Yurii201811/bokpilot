from __future__ import annotations

import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from bokpilot.domain import (
    JournalLine,
    PostingDraft,
    ReviewDecision,
    SourceKind,
    TransactionNature,
    VatTreatment,
)
from bokpilot.repository import Repository
from tests.helpers import source_record


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "private-data"
        self.path = self.root / "bokpilot.sqlite3"
        self.repository = Repository(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_schema_version_tables_indexes_and_initial_revision(self):
        expected_tables = {
            "workspace_state",
            "company_profile",
            "sources",
            "source_attachments",
            "suggestions",
            "reviews",
            "posting_drafts",
            "import_batches",
            "duplicate_candidates",
            "duplicate_decisions",
            "matches",
            "export_batches",
        }

        self.assertEqual(self.repository.schema_version(), 2)
        self.assertEqual(self.repository.workspace_revision(), 0)
        self.assertEqual(self.repository.table_count("workspace_state"), 1)
        self.assertTrue(expected_tables.issubset(self.repository.schema_tables()))
        self.assertTrue(
            {"source_import_key_uq", "review_queue_idx", "matches_source_idx"}.issubset(
                self.repository.schema_indexes()
            )
        )

    def test_connections_enable_foreign_keys_busy_timeout_and_wal(self):
        settings = self.repository.connection_settings()

        self.assertEqual(settings["foreign_keys"], 1)
        self.assertEqual(settings["busy_timeout"], 5000)
        self.assertEqual(settings["journal_mode"].lower(), "wal")

    def test_import_round_trip_and_idempotent_revision(self):
        record = source_record(
            "Exact evidence",
            -24_900,
            source_vat=VatTreatment.RATE_25,
            source_vat_minor=4_980,
            matched_source_id="invoice-1",
            high_risk=True,
        )

        first = self.repository.import_sources([record])
        duplicate = self.repository.import_sources([record])
        loaded = self.repository.get_source(record.id)

        self.assertEqual((first.inserted, first.skipped, first.revision), (1, 0, 1))
        self.assertEqual((duplicate.inserted, duplicate.skipped, duplicate.revision), (0, 1, 1))
        self.assertEqual(loaded, record)
        self.assertEqual(self.repository.workspace_revision(), 1)

    def test_unique_import_key_applies_without_source_row(self):
        first = source_record("No row A", -100)
        second = source_record("No row B", -200)
        first = first.__class__(**{**first.__dict__, "source_row": None, "import_key": "shared-key"})
        second = second.__class__(**{**second.__dict__, "source_row": None, "import_key": "shared-key"})

        result = self.repository.import_sources([first, second])

        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(self.repository.source_count(), 1)

    def test_rollback_keeps_rows_and_revision_unchanged(self):
        committed = source_record("Committed", -100)
        rolled_back = source_record("Rolled back", -200)
        self.repository.import_sources([committed])

        with self.assertRaisesRegex(RuntimeError, "synthetic rollback"):
            with self.repository.transaction() as transaction:
                transaction.import_sources([rolled_back])
                raise RuntimeError("synthetic rollback")

        self.assertEqual(self.repository.source_count(), 1)
        self.assertIsNone(self.repository.get_source(rolled_back.id))
        self.assertEqual(self.repository.workspace_revision(), 1)

    def test_multiple_mutations_in_one_transaction_increment_once(self):
        first = source_record("Batch one", -100)
        second = source_record("Batch two", -200)

        with self.repository.transaction() as transaction:
            transaction.import_sources([first])
            transaction.import_sources([second])

        self.assertEqual(self.repository.source_count(), 2)
        self.assertEqual(self.repository.workspace_revision(), 1)

    def test_concurrent_inserts_keep_all_unique_rows(self):
        records = [source_record(f"Concurrent {index}", -index - 1) for index in range(40)]

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda record: self.repository.import_sources([record]), records))

        self.assertTrue(all(result.inserted == 1 for result in results))
        self.assertEqual(self.repository.source_count(), 40)
        self.assertEqual(self.repository.workspace_revision(), 40)

    def test_review_and_posting_draft_round_trip_exact_types(self):
        record = source_record("Reviewed", -12_500)
        self.repository.import_sources([record])
        decision = ReviewDecision(
            TransactionNature.EXPENSE,
            "5420",
            VatTreatment.RATE_25,
            2_500,
            "Reviewed synthetic decision",
            True,
        )
        draft = PostingDraft(
            record.id,
            (
                JournalLine("5420", "Software", debit_minor=10_000),
                JournalLine("2641", "Input VAT", debit_minor=2_500),
                JournalLine("1930", "Bank", credit_minor=12_500),
            ),
            "software-services",
            1,
            (),
        )

        review_result = self.repository.append_review(record.id, decision)
        draft_result = self.repository.save_posting_draft(draft)

        self.assertEqual(review_result.revision, 2)
        self.assertEqual(draft_result.revision, 3)
        self.assertEqual(self.repository.latest_review(record.id), decision)
        self.assertEqual(self.repository.latest_posting_draft(record.id), draft)

    def test_export_batch_is_a_single_revisioned_mutation(self):
        result = self.repository.create_export_batch(
            format="json",
            artifact_path=self.root / "exports" / "batch.json",
            sha256="a" * 64,
            byte_count=123,
            source_ids=(),
        )

        self.assertEqual(result.revision, 1)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(self.repository.table_count("export_batches"), 1)

    def test_keyset_pagination_is_deterministic(self):
        records = []
        for index in range(7):
            record = source_record(f"Page {index}", -index - 1)
            record = record.__class__(
                **{
                    **record.__dict__,
                    "id": f"source-{index:02d}",
                    "occurred_on": date(2026, 7, 10 + (index // 4)),
                    "import_key": f"page:{index}",
                }
            )
            records.append(record)
        self.repository.import_sources(records)

        first = self.repository.list_review_queue(limit=3)
        second = self.repository.list_review_queue(limit=3, after=first.next_after)
        third = self.repository.list_review_queue(limit=3, after=second.next_after)

        identifiers = [record.id for page in (first, second, third) for record in page.records]
        self.assertEqual(identifiers, [f"source-{index:02d}" for index in range(7)])
        self.assertIsNotNone(first.next_after)
        self.assertIsNotNone(second.next_after)
        self.assertIsNone(third.next_after)
        self.assertEqual(first.revision, 1)

    def test_private_directory_and_database_file_modes(self):
        self.repository.import_sources([source_record("Permissions", -100)])

        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.path}{suffix}")
            if sidecar.exists():
                self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)

    def test_required_queries_use_named_indexes(self):
        self.repository.import_sources([source_record("Index", -100)])

        queue_plan = " ".join(
            self.repository.explain_query_plan(
                "SELECT id FROM sources WHERE status = ? "
                "AND (occurred_on, id) > (?, ?) ORDER BY occurred_on, id LIMIT ?",
                ("needs_review", "2026-01-01", "", 100),
            )
        )
        key_plan = " ".join(
            self.repository.explain_query_plan(
                "SELECT id FROM sources WHERE import_key = ?", ("test:test-index",)
            )
        )

        self.assertIn("review_queue_idx", queue_plan)
        self.assertIn("source_import_key_uq", key_plan)

    def test_ten_thousand_row_transaction_and_bounded_page(self):
        records = [source_record(f"Scale {index:05d}", -index - 1) for index in range(10_000)]

        with self.repository.transaction() as transaction:
            result = transaction.import_sources(records)

        page = self.repository.list_review_queue(limit=100)
        self.assertEqual(result.inserted, 10_000)
        self.assertEqual(self.repository.source_count(), 10_000)
        self.assertEqual(self.repository.workspace_revision(), 1)
        self.assertEqual(len(page.records), 100)
        self.assertIsNotNone(page.next_after)


if __name__ == "__main__":
    unittest.main()
