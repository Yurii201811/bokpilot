from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from bokpilot.domain import EvidenceStatus
from bokpilot.migrations import migrate_json_workspace
from bokpilot.repository import Repository, restore_from
from tests.helpers import source_record


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


class BackupRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "data"
        self.repository = Repository(self.data_root / "bokpilot.sqlite3")
        self.record = source_record("Backup source", -12_500)
        self.repository.import_sources([self.record])

        self.attachment_root = self.data_root / "attachments"
        self.export_root = self.data_root / "exports"
        self.attachment_root.mkdir(mode=0o700)
        self.export_root.mkdir(mode=0o700)
        self.attachment = self.attachment_root / "receipt.txt"
        self.export = self.export_root / "batch.json"
        self.attachment.write_bytes(b"synthetic attachment")
        self.export.write_bytes(b'{"synthetic":true}\n')
        os.chmod(self.attachment, 0o600)
        os.chmod(self.export, 0o600)
        self.attachment_sha = hashlib.sha256(self.attachment.read_bytes()).hexdigest()
        self.export_sha = hashlib.sha256(self.export.read_bytes()).hexdigest()
        self.repository.record_attachment(
            self.record.id,
            path=self.attachment,
            sha256=self.attachment_sha,
            byte_count=self.attachment.stat().st_size,
        )
        self.repository.create_export_batch(
            format="json",
            artifact_path=self.export,
            sha256=self.export_sha,
            byte_count=self.export.stat().st_size,
            source_ids=(self.record.id,),
        )
        self.bundle = self.root / "backups" / "workspace.bokpilot-backup"

    def tearDown(self):
        self.temporary.cleanup()

    def test_backup_and_restore_verified_snapshot_with_private_modes(self):
        backup = self.repository.backup_to(
            self.bundle, self.attachment_root, self.export_root
        )

        self.assertTrue(self.bundle.exists())
        self.assertEqual(stat.S_IMODE(self.bundle.stat().st_mode), 0o600)
        self.assertEqual(backup.sha256, hashlib.sha256(self.bundle.read_bytes()).hexdigest())
        self.assertEqual(backup.workspace_revision, self.repository.workspace_revision())
        self.assertEqual(backup.row_counts["sources"], 1)
        self.assertEqual(backup.member_count, 4)
        self.assertGreater(backup.total_bytes, self.bundle.stat().st_size / 2)
        with zipfile.ZipFile(self.bundle) as archive:
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()))
            self.assertEqual(
                set(archive.namelist()),
                {
                    "bokpilot.sqlite3",
                    "attachments/receipt.txt",
                    "exports/batch.json",
                    "manifest.json",
                },
            )

        restored_root = self.root / "restored"
        restored = restore_from(self.bundle, restored_root, backup.sha256)
        restored_repository = Repository(restored_root / "bokpilot.sqlite3")

        self.assertEqual(restored_repository.source_count(), 1)
        self.assertEqual(restored_repository.attachment_records()[0]["path"], "receipt.txt")
        self.assertEqual(restored_repository.export_records()[0]["artifact_path"], "batch.json")
        self.assertEqual(restored.restored_revision, backup.workspace_revision)
        self.assertEqual(restored.attachment_hashes, (self.attachment_sha,))
        self.assertEqual(restored.export_checksums, (self.export_sha,))
        self.assertEqual((restored_root / "attachments" / "receipt.txt").read_bytes(), self.attachment.read_bytes())
        self.assertEqual((restored_root / "exports" / "batch.json").read_bytes(), self.export.read_bytes())
        self.assertEqual(stat.S_IMODE(restored_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((restored_root / "bokpilot.sqlite3").stat().st_mode), 0o600)

    def test_backup_aborts_when_referenced_file_hash_changed(self):
        self.attachment.write_bytes(b"synthetic attachmenU")

        with self.assertRaisesRegex(ValueError, "hash"):
            self.repository.backup_to(self.bundle, self.attachment_root, self.export_root)

        self.assertFalse(self.bundle.exists())

    def test_restore_rejects_wrong_outer_checksum_without_destination(self):
        self.repository.backup_to(self.bundle, self.attachment_root, self.export_root)
        destination = self.root / "wrong-checksum"

        with self.assertRaisesRegex(ValueError, "checksum"):
            restore_from(self.bundle, destination, "0" * 64)

        self.assertFalse(destination.exists())

    def test_restore_rejects_tampered_member_and_traversal(self):
        backup = self.repository.backup_to(
            self.bundle, self.attachment_root, self.export_root
        )
        for variant in ("tampered", "traversal"):
            candidate = self.root / f"{variant}.bokpilot-backup"
            with zipfile.ZipFile(self.bundle) as source_archive, zipfile.ZipFile(
                candidate, "w", compression=zipfile.ZIP_STORED
            ) as target_archive:
                for info in source_archive.infolist():
                    data = source_archive.read(info.filename)
                    if variant == "tampered" and info.filename == "attachments/receipt.txt":
                        data = b"tampered member"
                    target_archive.writestr(info, data)
                if variant == "traversal":
                    target_archive.writestr("../escape", b"escape")
            checksum = hashlib.sha256(candidate.read_bytes()).hexdigest()
            destination = self.root / f"restore-{variant}"

            with self.subTest(variant=variant), self.assertRaises(ValueError):
                restore_from(candidate, destination, checksum)
            self.assertFalse(destination.exists())

        self.assertTrue(backup.sha256)

    def test_restore_rejects_absolute_duplicate_and_symlink_members(self):
        self.repository.backup_to(self.bundle, self.attachment_root, self.export_root)
        for variant in ("absolute", "duplicate", "symlink"):
            candidate = self.root / f"unsafe-{variant}.bokpilot-backup"
            with zipfile.ZipFile(self.bundle) as source_archive, zipfile.ZipFile(
                candidate, "w", compression=zipfile.ZIP_STORED
            ) as target_archive:
                for info in source_archive.infolist():
                    target_archive.writestr(info, source_archive.read(info.filename))
                if variant == "absolute":
                    target_archive.writestr("/escape", b"escape")
                elif variant == "duplicate":
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        info = source_archive.getinfo("manifest.json")
                        target_archive.writestr(info, source_archive.read("manifest.json"))
                else:
                    info = zipfile.ZipInfo("attachments/link")
                    info.compress_type = zipfile.ZIP_STORED
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    target_archive.writestr(info, b"receipt.txt")
            checksum = hashlib.sha256(candidate.read_bytes()).hexdigest()
            destination = self.root / f"unsafe-restore-{variant}"

            with self.subTest(variant=variant), self.assertRaises(ValueError):
                restore_from(candidate, destination, checksum)
            self.assertFalse(destination.exists())

    def test_restore_accepts_explicitly_empty_destination(self):
        backup = self.repository.backup_to(
            self.bundle, self.attachment_root, self.export_root
        )
        destination = self.root / "empty-destination"
        destination.mkdir()

        restored = restore_from(self.bundle, destination, backup.sha256)

        self.assertEqual(restored.destination_root, destination)
        self.assertTrue((destination / "bokpilot.sqlite3").exists())

    def test_restore_refuses_nonempty_destination(self):
        backup = self.repository.backup_to(
            self.bundle, self.attachment_root, self.export_root
        )
        destination = self.root / "existing"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "non-empty"):
            restore_from(self.bundle, destination, backup.sha256)

        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
