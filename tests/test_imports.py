import base64
import hashlib
import os
import time
import tempfile
import unittest
from pathlib import Path

from bokpilot.imports import cleanup_abandoned_previews, commit_import, preview_import
from bokpilot.repository import Repository


class ImportPreviewTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = Repository(self.root / "data" / "bokpilot.sqlite3")

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, content: bytes) -> dict[str, str]:
        return {
            "kind": "bank_transaction",
            "filename": "seb-july.csv",
            "media_type": "text/csv; charset=utf-8",
            "content_base64": base64.b64encode(content).decode("ascii"),
            "locale": "auto",
        }

    def test_preview_keeps_valid_rows_and_reports_row_specific_issues(self):
        content = (
            "Datum;Beskrivning;Belopp\n"
            "2026-07-01;Valid payment;100,00\n"
            "not-a-date;Broken date;20,00\n"
            "2026-07-03;Ambiguous amount;1,234\n"
        ).encode("utf-8")

        preview = preview_import(self.repository, self.request(content))

        self.assertEqual(preview.source_filename, "seb-july.csv")
        self.assertEqual(preview.candidates[0].source_row, 2)
        self.assertEqual(preview.source_sha256, hashlib.sha256(content).hexdigest())
        self.assertEqual(len(preview.candidates), 1)
        self.assertEqual([issue.source_row for issue in preview.issues], [3, 4])
        self.assertFalse(preview.committed)
        self.assertEqual(self.repository.source_count(), 0)

    def test_commit_is_idempotent_and_preserves_original_bytes(self):
        content = b"Datum;Beskrivning;Belopp\n2026-07-01;Payment;100,00\n"
        preview = preview_import(self.repository, self.request(content))

        first = commit_import(
            self.repository,
            preview.batch_id,
            expected_workspace_revision=self.repository.workspace_revision(),
        )
        second = commit_import(
            self.repository,
            preview.batch_id,
            expected_workspace_revision=self.repository.workspace_revision(),
        )

        self.assertEqual(first.created_ids, second.existing_ids)
        self.assertEqual(second.created_ids, ())
        self.assertEqual(self.repository.source_count(), 1)
        attachment = self.root / "data" / "attachments" / preview.source_sha256
        self.assertEqual(attachment.read_bytes(), content)

    def test_invalid_base64_and_oversized_content_fail_before_batch_creation(self):
        request = self.request(b"small")
        request["content_base64"] = "not base64!"
        with self.assertRaisesRegex(ValueError, "base64"):
            preview_import(self.repository, request)

        oversized = self.request(b"x" * (10 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "10 MiB"):
            preview_import(self.repository, oversized)
        self.assertEqual(self.repository.table_count("import_batches"), 0)

    def test_windows_1252_is_supported_and_unknown_charset_is_rejected(self):
        content = "Datum;Beskrivning;Belopp\n2026-07-01;Köp;100,00\n".encode("cp1252")
        request = self.request(content)
        request["media_type"] = "text/csv; charset=windows-1252"
        preview = preview_import(self.repository, request)
        self.assertEqual(preview.candidates[0].description, "Köp")

        request = self.request(content)
        request["media_type"] = "text/csv; charset=iso-8859-1"
        with self.assertRaisesRegex(ValueError, "charset"):
            preview_import(self.repository, request)

    def test_stale_commit_revision_does_not_create_sources(self):
        preview = preview_import(
            self.repository,
            self.request(b"Datum;Beskrivning;Belopp\n2026-07-01;Payment;100,00\n"),
        )

        with self.assertRaisesRegex(ValueError, "revision conflict"):
            commit_import(self.repository, preview.batch_id, expected_workspace_revision=0)

        self.assertEqual(self.repository.source_count(), 0)
        self.assertFalse((self.root / "data" / "attachments" / preview.source_sha256).exists())

    def test_incomplete_detection_requires_and_persists_explicit_mapping(self):
        content = b"Dag;Detalj;Kronor\n2026-07-01;Payment;100,00\n"
        request = self.request(content)
        preview = preview_import(self.repository, request)
        self.assertEqual(
            {issue.field for issue in preview.issues if issue.code == "mapping_required"},
            {"date", "amount"},
        )
        with self.assertRaisesRegex(ValueError, "mapping"):
            commit_import(
                self.repository,
                preview.batch_id,
                expected_workspace_revision=self.repository.workspace_revision(),
            )

        request["column_mapping"] = {
            "date": "Dag",
            "description": "Detalj",
            "amount": "Kronor",
        }
        mapped = preview_import(self.repository, request)
        self.assertEqual(mapped.batch_id, preview.batch_id)
        self.assertEqual(mapped.column_mapping["amount"], "kronor")
        self.assertEqual(len(mapped.candidates), 1)
        self.assertFalse(any(issue.code == "mapping_required" for issue in mapped.issues))

    def test_cleanup_removes_only_abandoned_uncommitted_preview(self):
        preview = preview_import(self.repository, self.request(b"Datum;Beskrivning;Belopp\n2026-07-01;Payment;100,00\n"))
        staged = self.root / "data" / "staging" / preview.batch_id
        old = time.time() - 25 * 60 * 60
        os.utime(staged, (old, old))

        removed = cleanup_abandoned_previews(self.repository, now=time.time())

        self.assertEqual(removed, (preview.batch_id,))
        self.assertIsNone(self.repository.import_batch(preview.batch_id))
        self.assertFalse(staged.exists())

    def test_different_files_with_same_business_fields_create_unresolved_duplicate(self):
        first = preview_import(
            self.repository,
            self.request(b"Datum;Beskrivning;Belopp\n2026-07-01;Payment;100,00\n"),
        )
        commit_import(
            self.repository,
            first.batch_id,
            expected_workspace_revision=self.repository.workspace_revision(),
        )
        second = preview_import(
            self.repository,
            self.request(b"Datum;Beskrivning;Belopp\r\n2026-07-01;Payment;100,00\r\n"),
        )
        commit_import(
            self.repository,
            second.batch_id,
            expected_workspace_revision=self.repository.workspace_revision(),
        )

        self.assertEqual(self.repository.source_count(), 2)
        self.assertEqual(self.repository.table_count("duplicate_candidates"), 1)


if __name__ == "__main__":
    unittest.main()
