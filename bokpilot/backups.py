"""Verified private backup bundles and atomic restore."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .repository import Repository, SCHEMA_VERSION, _APPLICATION_TABLES


@dataclass(frozen=True)
class BackupReport:
    bundle_path: Path
    sha256: str
    workspace_revision: int
    row_counts: dict[str, int]
    member_count: int
    total_bytes: int


@dataclass(frozen=True)
class RestoreReport:
    destination_root: Path
    database_path: Path
    restored_revision: int
    row_counts: dict[str, int]
    attachment_hashes: tuple[str, ...]
    export_checksums: tuple[str, ...]


def backup_repository(
    repository: Repository,
    destination: Path,
    attachment_root: Path,
    export_root: Path,
) -> BackupReport:
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"Backup destination already exists: {destination}")
    if destination.parent.exists() and destination.parent.is_symlink():
        raise ValueError("Backup destination directory cannot be a symlink.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    temporary_root = Path(tempfile.mkdtemp(prefix=".bokpilot-backup-", dir=destination.parent))
    os.chmod(temporary_root, 0o700)
    temporary_bundle = temporary_root / "pending.bokpilot-backup"
    snapshot = temporary_root / "bokpilot.sqlite3"
    try:
        repository.snapshot_to(snapshot)
        metadata = _snapshot_metadata(snapshot)
        members: dict[str, bytes] = {}
        member_kinds: dict[str, str] = {}
        attachment_rewrites: list[tuple[str, str]] = []
        export_rewrites: list[tuple[str, str]] = []
        for row in metadata["attachments"]:
            name, relative_path, data = _verified_artifact_member(
                attachment_root,
                str(row["path"]),
                "attachments",
                str(row["sha256"]),
                int(row["byte_count"]),
            )
            _add_unique_member(members, member_kinds, name, data, "attachment")
            attachment_rewrites.append((str(row["id"]), relative_path))
        for row in metadata["exports"]:
            name, relative_path, data = _verified_artifact_member(
                export_root,
                str(row["artifact_path"]),
                "exports",
                str(row["sha256"]),
                int(row["byte_count"]),
            )
            _add_unique_member(members, member_kinds, name, data, "export")
            export_rewrites.append((str(row["id"]), relative_path))
        _rewrite_snapshot_paths(snapshot, attachment_rewrites, export_rewrites)
        members["bokpilot.sqlite3"] = snapshot.read_bytes()
        member_kinds["bokpilot.sqlite3"] = "database"

        manifest_members = [
            {
                "path": name,
                "kind": member_kinds[name],
                "byte_count": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(members.items())
        ]
        manifest = {
            "schema_version": metadata["schema_version"],
            "workspace_revision": metadata["workspace_revision"],
            "row_counts": metadata["row_counts"],
            "members": manifest_members,
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")

        with zipfile.ZipFile(temporary_bundle, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(members.items()):
                archive.writestr(_private_zip_info(name), data)
            archive.writestr(_private_zip_info("manifest.json"), manifest_bytes)
        os.chmod(temporary_bundle, 0o600)
        _fsync_file(temporary_bundle)
        _verify_archive(temporary_bundle)
        os.replace(temporary_bundle, destination)
        os.chmod(destination, 0o600)
        _fsync_directory(destination.parent)
        checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
        with zipfile.ZipFile(destination) as archive:
            infos = archive.infolist()
            total_bytes = sum(info.file_size for info in infos)
        return BackupReport(
            bundle_path=destination,
            sha256=checksum,
            workspace_revision=int(metadata["workspace_revision"]),
            row_counts=dict(metadata["row_counts"]),
            member_count=len(infos),
            total_bytes=total_bytes,
        )
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def restore_backup(
    backup: Path,
    destination_root: Path,
    expected_sha256: str,
) -> RestoreReport:
    backup = Path(backup)
    destination_root = Path(destination_root)
    if backup.is_symlink() or not backup.is_file():
        raise ValueError("Backup must be a regular file, not a symlink.")
    if destination_root.is_symlink():
        raise ValueError("Restore destination cannot be a symlink.")
    actual_sha256 = hashlib.sha256(backup.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256.lower():
        raise ValueError("Backup checksum does not match the expected SHA-256.")

    existed_empty = destination_root.exists()
    if existed_empty:
        if not destination_root.is_dir() or any(destination_root.iterdir()):
            raise ValueError("Restore destination must be absent or explicitly empty; it is non-empty.")

    manifest, members = _verify_archive(backup)
    destination_root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".bokpilot-restore-", dir=destination_root.parent)
    )
    os.chmod(temporary_root, 0o700)
    installed = False
    try:
        for name, data in members.items():
            target = temporary_root.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(target.parent, 0o700)
            _write_private_file(target, data)

        database = temporary_root / "bokpilot.sqlite3"
        restored_metadata = _snapshot_metadata(database)
        if restored_metadata["schema_version"] != manifest["schema_version"]:
            raise ValueError("Restored database schema version does not match the manifest.")
        if restored_metadata["workspace_revision"] != manifest["workspace_revision"]:
            raise ValueError("Restored workspace revision does not match the manifest.")
        if restored_metadata["row_counts"] != manifest["row_counts"]:
            raise ValueError("Restored database row counts do not match the manifest.")

        if existed_empty:
            destination_root.rmdir()
        try:
            os.replace(temporary_root, destination_root)
        except BaseException:
            if existed_empty and not destination_root.exists():
                destination_root.mkdir(mode=0o700)
            raise
        installed = True
        _harden_tree(destination_root)
        _fsync_directory(destination_root.parent)

        attachment_hashes = tuple(
            str(entry["sha256"])
            for entry in manifest["members"]
            if entry["kind"] == "attachment"
        )
        export_checksums = tuple(
            str(entry["sha256"])
            for entry in manifest["members"]
            if entry["kind"] == "export"
        )
        return RestoreReport(
            destination_root=destination_root,
            database_path=destination_root / "bokpilot.sqlite3",
            restored_revision=int(manifest["workspace_revision"]),
            row_counts=dict(manifest["row_counts"]),
            attachment_hashes=attachment_hashes,
            export_checksums=export_checksums,
        )
    finally:
        if not installed:
            shutil.rmtree(temporary_root, ignore_errors=True)


def _snapshot_metadata(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.lower() != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported SQLite schema version: {schema_version}")
        revision = int(
            connection.execute("SELECT revision FROM workspace_state WHERE id = 1").fetchone()[0]
        )
        row_counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in sorted(_APPLICATION_TABLES)
        }
        attachments = [
            dict(row)
            for row in connection.execute(
                "SELECT id, path, sha256, byte_count FROM source_attachments ORDER BY id"
            ).fetchall()
        ]
        exports = [
            dict(row)
            for row in connection.execute(
                "SELECT id, artifact_path, sha256, byte_count FROM export_batches ORDER BY id"
            ).fetchall()
        ]
        return {
            "schema_version": schema_version,
            "workspace_revision": revision,
            "row_counts": row_counts,
            "attachments": attachments,
            "exports": exports,
        }
    finally:
        connection.close()


def _verified_artifact_member(
    root: Path,
    stored_path: str,
    prefix: str,
    expected_sha256: str,
    expected_size: int,
) -> tuple[str, str, bytes]:
    root_path = Path(root)
    if root_path.is_symlink():
        raise ValueError(f"Configured {prefix} root cannot be a symlink.")
    root = root_path.resolve()
    candidate = Path(stored_path)
    candidate = candidate if candidate.is_absolute() else root / candidate
    if candidate.is_symlink():
        raise ValueError(f"Referenced {prefix} file cannot be a symlink: {candidate}")
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Referenced {prefix} file is outside its configured root.") from exc
    if not resolved.is_file():
        raise ValueError(f"Referenced {prefix} file does not exist: {resolved}")
    data = resolved.read_bytes()
    if len(data) != expected_size:
        raise ValueError(f"Referenced {prefix} file byte count does not match.")
    if hashlib.sha256(data).hexdigest() != expected_sha256.lower():
        raise ValueError(f"Referenced {prefix} file hash does not match.")
    name = str(PurePosixPath(prefix, *relative.parts))
    return name, relative.as_posix(), data


def _rewrite_snapshot_paths(
    snapshot: Path,
    attachment_paths: list[tuple[str, str]],
    export_paths: list[tuple[str, str]],
) -> None:
    connection = sqlite3.connect(snapshot)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "UPDATE source_attachments SET path = ? WHERE id = ?",
            [(path, identifier) for identifier, path in attachment_paths],
        )
        connection.executemany(
            "UPDATE export_batches SET artifact_path = ? WHERE id = ?",
            [(path, identifier) for identifier, path in export_paths],
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    os.chmod(snapshot, 0o600)


def _add_unique_member(
    members: dict[str, bytes],
    member_kinds: dict[str, str],
    name: str,
    data: bytes,
    kind: str,
) -> None:
    if name in members:
        raise ValueError(f"Duplicate backup member path: {name}")
    members[name] = data
    member_kinds[name] = kind


def _private_zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def _verify_archive(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("Backup is not a valid ZIP bundle.") from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("Backup contains duplicate members.")
        for info in infos:
            _validate_member_name(info.filename)
            if info.compress_type != zipfile.ZIP_STORED:
                raise ValueError("Backup members must use ZIP_STORED.")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("Backup cannot contain symlink members.")
        if "manifest.json" not in names:
            raise ValueError("Backup manifest is missing.")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Backup manifest is invalid.") from exc
        if not isinstance(manifest, dict) or not isinstance(manifest.get("members"), list):
            raise ValueError("Backup manifest structure is invalid.")
        if int(manifest.get("schema_version", -1)) != SCHEMA_VERSION:
            raise ValueError("Backup manifest schema version is unsupported.")
        manifest_entries: dict[str, dict[str, Any]] = {}
        for entry in manifest["members"]:
            if not isinstance(entry, dict):
                raise ValueError("Backup manifest member is invalid.")
            name = str(entry.get("path") or "")
            _validate_member_name(name)
            if name == "manifest.json" or name in manifest_entries:
                raise ValueError("Backup manifest contains duplicate members.")
            if not (
                name == "bokpilot.sqlite3"
                or name.startswith("attachments/")
                or name.startswith("exports/")
            ):
                raise ValueError(f"Unexpected backup member: {name}")
            expected_kind = (
                "database"
                if name == "bokpilot.sqlite3"
                else "attachment"
                if name.startswith("attachments/")
                else "export"
            )
            if entry.get("kind") != expected_kind:
                raise ValueError(f"Backup member kind mismatch: {name}")
            byte_count = entry.get("byte_count")
            if type(byte_count) is not int or byte_count < 0:
                raise ValueError(f"Backup member byte count is invalid: {name}")
            sha256 = str(entry.get("sha256") or "")
            if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
                raise ValueError(f"Backup member SHA-256 is invalid: {name}")
            manifest_entries[name] = entry
        if "bokpilot.sqlite3" not in manifest_entries:
            raise ValueError("Backup database member is missing.")
        if set(names) != set(manifest_entries) | {"manifest.json"}:
            raise ValueError("Backup members do not match the manifest.")
        members: dict[str, bytes] = {}
        for name, entry in manifest_entries.items():
            data = archive.read(name)
            if len(data) != int(entry.get("byte_count", -1)):
                raise ValueError(f"Backup member byte count mismatch: {name}")
            if hashlib.sha256(data).hexdigest() != str(entry.get("sha256") or "").lower():
                raise ValueError(f"Backup member hash mismatch: {name}")
            members[name] = data
        row_counts = manifest.get("row_counts")
        if not isinstance(row_counts, dict) or set(row_counts) != _APPLICATION_TABLES:
            raise ValueError("Backup row counts are invalid.")
        if any(type(value) is not int or value < 0 for value in row_counts.values()):
            raise ValueError("Backup row count values are invalid.")
        revision = manifest.get("workspace_revision")
        if type(revision) is not int or revision < 0:
            raise ValueError("Backup workspace revision is invalid.")
        manifest["row_counts"] = {str(key): value for key, value in row_counts.items()}
        return manifest, members


def _validate_member_name(name: str) -> None:
    if not name or "\\" in name:
        raise ValueError("Backup member path is invalid.")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or str(path) != name
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Backup member path is unsafe.")


def _write_private_file(path: Path, data: bytes) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _harden_tree(root: Path) -> None:
    os.chmod(root, 0o700)
    for path in root.rglob("*"):
        if path.is_dir():
            os.chmod(path, 0o700)
        else:
            os.chmod(path, 0o600)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
