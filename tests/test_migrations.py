from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from bokpilot.domain import EvidenceStatus
from bokpilot.migrations import migrate_json_workspace
from bokpilot.repository import Repository


FIXTURE = Path(__file__).parent / "fixtures" / "workspaces" / "v1-workspace.json"


class JsonMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "workspace.json"
        self.destination = self.root / "data" / "bokpilot.sqlite3"
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["items"][0]["raw"]["document_text"] = "Retained legacy evidence text"
        payload["events"] = [{"at": "2026-05-02T11:00:00+00:00", "message": "Legacy import"}]
        self.source.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def test_migration_preserves_source_backs_up_and_imports_exact_record(self):
        report = migrate_json_workspace(self.source, self.destination)
        repository = Repository(self.destination)
        record = repository.get_source("BP-0001")

        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(report.source_sha256, hashlib.sha256(self.original).hexdigest())
        self.assertEqual(report.migrated_item_count, 1)
        self.assertEqual(report.migrated_event_count, 1)
        self.assertEqual(report.skipped_count, 0)
        self.assertEqual(report.schema_version, 2)
        self.assertTrue(report.backup_path.exists())
        self.assertNotEqual(report.backup_path, self.source)
        self.assertEqual(report.backup_path.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(report.backup_path.stat().st_mode), 0o600)
        self.assertEqual(repository.workspace_revision(), 1)
        self.assertEqual(repository.table_count("import_batches"), 1)
        self.assertEqual(record.amount.minor, -24_900)
        self.assertEqual(record.source_vat_minor, 4_980)
        self.assertEqual(record.import_key, f"legacy-v1:{report.source_sha256}:BP-0001")
        self.assertEqual(record.evidence_status, EvidenceStatus.LEGACY_UNAVAILABLE)
        self.assertIsNone(record.attachment_sha256)
        self.assertEqual(record.extracted["document_text"], "Retained legacy evidence text")
        self.assertEqual(record.extracted["review_issue"], "legacy_evidence_incomplete")
        self.assertEqual(repository.migration_events(report.source_sha256)[0]["message"], "Legacy import")

    def test_repeated_source_hash_returns_prior_report_without_mutation(self):
        first = migrate_json_workspace(self.source, self.destination)
        repository = Repository(self.destination)
        first_revision = repository.workspace_revision()
        first_backups = tuple(self.root.glob("workspace.json.backup-*"))

        second = migrate_json_workspace(self.source, self.destination)
        second_backups = tuple(self.root.glob("workspace.json.backup-*"))

        self.assertEqual(second, first)
        self.assertEqual(repository.source_count(), 1)
        self.assertEqual(repository.workspace_revision(), first_revision)
        self.assertEqual(second_backups, first_backups)

    def test_invalid_json_does_not_create_or_change_destination(self):
        self.source.write_text("{not json", encoding="utf-8")
        before = self.source.read_bytes()

        with self.assertRaises(ValueError):
            migrate_json_workspace(self.source, self.destination)

        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(self.destination.exists())
        self.assertEqual(tuple(self.root.glob("workspace.json.backup-*")), ())

    def test_invalid_json_does_not_change_existing_destination(self):
        repository = Repository(self.destination)
        before_revision = repository.workspace_revision()
        before_count = repository.source_count()
        self.source.write_text("[invalid", encoding="utf-8")

        with self.assertRaises(ValueError):
            migrate_json_workspace(self.source, self.destination)

        self.assertEqual(repository.workspace_revision(), before_revision)
        self.assertEqual(repository.source_count(), before_count)

    def test_invalid_item_is_rejected_before_destination_creation(self):
        payload = json.loads(self.source.read_text(encoding="utf-8"))
        payload["items"][0].pop("id")
        self.source.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "item id"):
            migrate_json_workspace(self.source, self.destination)

        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
