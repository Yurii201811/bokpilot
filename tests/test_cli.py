from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bokpilot.repository import Repository
from tests.helpers import source_record


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests" / "fixtures" / "workspaces" / "v1-workspace.json"


class CliTest(unittest.TestCase):
    def run_cli(self, *arguments: str, environment: dict[str, str] | None = None):
        merged = os.environ.copy()
        if environment:
            merged.update(environment)
        return subprocess.run(
            [sys.executable, "-m", "bokpilot", *arguments],
            cwd=PROJECT,
            env=merged,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )

    def test_migrate_backup_and_restore_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "workspace.json"
            source.write_bytes(FIXTURE.read_bytes())
            database = root / "data" / "bokpilot.sqlite3"
            bundle = root / "backups" / "workspace.bokpilot-backup"
            restored = root / "restored"

            migration = self.run_cli(
                "migrate", "--from-json", str(source), "--to-sqlite", str(database)
            )
            self.assertEqual(migration.returncode, 0, migration.stderr)
            self.assertIn("Migrated 1 item", migration.stdout)
            self.assertTrue(database.exists())

            backup = self.run_cli(
                "backup",
                "--to",
                str(bundle),
                environment={"BOKPILOT_DATA_PATH": str(database)},
            )
            self.assertEqual(backup.returncode, 0, backup.stderr)
            checksum = hashlib.sha256(bundle.read_bytes()).hexdigest()
            self.assertIn(checksum, backup.stdout)

            restore = self.run_cli(
                "restore",
                "--from",
                str(bundle),
                "--to",
                str(restored),
                "--sha256",
                checksum,
            )
            self.assertEqual(restore.returncode, 0, restore.stderr)
            self.assertEqual(Repository(restored / "bokpilot.sqlite3").source_count(), 1)

    def test_invalid_migration_and_restore_exit_nonzero_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "invalid.json"
            source.write_text("{invalid", encoding="utf-8")
            database = root / "data" / "bokpilot.sqlite3"

            invalid = self.run_cli(
                "migrate", "--from-json", str(source), "--to-sqlite", str(database)
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertFalse(database.exists())

            valid_database = root / "valid" / "bokpilot.sqlite3"
            repository = Repository(valid_database)
            repository.import_sources([source_record("CLI", -100)])
            bundle = root / "backup" / "workspace.bokpilot-backup"
            repository.backup_to(bundle, root / "valid" / "attachments", root / "valid" / "exports")
            destination = root / "wrong-restore"
            wrong = self.run_cli(
                "restore",
                "--from",
                str(bundle),
                "--to",
                str(destination),
                "--sha256",
                "0" * 64,
            )
            self.assertNotEqual(wrong.returncode, 0)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
