from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .migrations import migrate_json_workspace
from .repository import Repository, restore_from
from .store import default_data_path


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {"migrate", "backup", "restore"}:
        from .server import main as server_main

        server_main(arguments)
        return 0

    parser = argparse.ArgumentParser(description="Bokpilot local data utilities.")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate = commands.add_parser("migrate", help="Explicitly migrate a legacy JSON workspace.")
    migrate.add_argument("--from-json", type=Path, required=True)
    migrate.add_argument("--to-sqlite", type=Path, required=True)

    backup = commands.add_parser("backup", help="Create a verified private backup bundle.")
    backup.add_argument("--to", type=Path, required=True)
    backup.add_argument("--data-path", type=Path, default=None)
    backup.add_argument("--attachment-root", type=Path, default=None)
    backup.add_argument("--export-root", type=Path, default=None)

    restore = commands.add_parser("restore", help="Verify and atomically restore a backup.")
    restore.add_argument("--from", dest="from_backup", type=Path, required=True)
    restore.add_argument("--to", type=Path, required=True)
    restore.add_argument("--sha256", required=True)

    parsed = parser.parse_args(arguments)
    try:
        if parsed.command == "migrate":
            report = migrate_json_workspace(parsed.from_json, parsed.to_sqlite)
            suffix = "" if report.migrated_item_count == 1 else "s"
            print(
                f"Migrated {report.migrated_item_count} item{suffix}; "
                f"skipped {report.skipped_count}; schema {report.schema_version}."
            )
            print(f"Source SHA-256: {report.source_sha256}")
            print(f"Verified source backup: {report.backup_path}")
            return 0
        if parsed.command == "backup":
            data_path = parsed.data_path or default_data_path()
            repository = Repository(data_path)
            attachment_root = parsed.attachment_root or data_path.parent / "attachments"
            export_root = parsed.export_root or data_path.parent / "exports"
            report = repository.backup_to(parsed.to, attachment_root, export_root)
            print(f"Backup: {report.bundle_path}")
            print(f"SHA-256: {report.sha256}")
            print(f"Workspace revision: {report.workspace_revision}")
            return 0
        report = restore_from(parsed.from_backup, parsed.to, parsed.sha256)
        print(f"Restored: {report.destination_root}")
        print(f"Workspace revision: {report.restored_revision}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed with a concise report.
        print(f"Bokpilot error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
