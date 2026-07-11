"""Explicit, reversible migration from legacy JSON workspaces."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .domain import EvidenceStatus, SourceRecord
from .repository import Repository, SCHEMA_VERSION
from .serialization import decode_source


@dataclass(frozen=True)
class MigrationReport:
    source_sha256: str
    backup_path: Path
    migrated_item_count: int
    migrated_event_count: int
    skipped_count: int
    schema_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "backup_path": str(self.backup_path),
            "migrated_item_count": self.migrated_item_count,
            "migrated_event_count": self.migrated_event_count,
            "skipped_count": self.skipped_count,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MigrationReport":
        return cls(
            source_sha256=str(payload["source_sha256"]),
            backup_path=Path(str(payload["backup_path"])),
            migrated_item_count=int(payload["migrated_item_count"]),
            migrated_event_count=int(payload["migrated_event_count"]),
            skipped_count=int(payload["skipped_count"]),
            schema_version=int(payload["schema_version"]),
        )


def migrate_json_workspace(source: Path, destination: Path) -> MigrationReport:
    """Validate, back up, and explicitly import a legacy JSON workspace."""
    source = Path(source)
    destination = Path(destination)
    source_bytes = source.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    workspace = _decode_workspace(source_bytes)
    records = _legacy_records(workspace, source_sha256)
    events = _validated_events(workspace)

    repository: Repository | None = None
    if destination.exists():
        repository = Repository(destination)
        existing = repository.migration_payload(source_sha256)
        if existing is not None:
            return _report_from_stored(existing)
    backup_path = _write_private_backup(source, source_bytes)
    if repository is None:
        repository = Repository(destination)
    report: MigrationReport | None = None
    with repository.transaction() as transaction:
        existing = transaction.migration_payload(source_sha256)
        if existing is not None:
            backup_path.unlink(missing_ok=True)
            report = _report_from_stored(existing)
        else:
            imported = transaction.import_sources(records)
            report = MigrationReport(
                source_sha256=source_sha256,
                backup_path=backup_path,
                migrated_item_count=imported.inserted,
                migrated_event_count=len(events),
                skipped_count=imported.skipped,
                schema_version=SCHEMA_VERSION,
            )
            transaction.record_import_batch(
                batch_id=f"legacy-v1:{source_sha256}",
                source_sha256=source_sha256,
                report=report.to_dict(),
                events=events,
            )
    assert report is not None
    return report


def _decode_workspace(source_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Legacy workspace must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Legacy workspace root must be an object.")
    if not isinstance(payload.get("items", []), list):
        raise ValueError("Legacy workspace items must be a list.")
    if not isinstance(payload.get("events", []), list):
        raise ValueError("Legacy workspace events must be a list.")
    return payload


def _legacy_records(workspace: Mapping[str, Any], source_sha256: str) -> tuple[SourceRecord, ...]:
    records: list[SourceRecord] = []
    seen_ids: set[str] = set()
    for index, item_value in enumerate(workspace.get("items", []), start=1):
        if not isinstance(item_value, dict):
            raise ValueError(f"Legacy item {index} must be an object.")
        item_id = str(item_value.get("id") or "").strip()
        if not item_id:
            raise ValueError(f"Legacy item id is required at item {index}.")
        if item_id in seen_ids:
            raise ValueError(f"Duplicate legacy item id: {item_id}.")
        seen_ids.add(item_id)
        raw = item_value.get("raw")
        if not isinstance(raw, dict):
            raise ValueError(f"Legacy item {item_id} must contain a raw object.")
        try:
            decoded = decode_source(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Legacy item {item_id} is invalid: {exc}") from exc
        extracted = dict(decoded.extracted)
        extracted["legacy_item_id"] = item_id
        extracted["review_issue"] = "legacy_evidence_incomplete"
        if raw.get("document_text") not in (None, ""):
            extracted["document_text"] = str(raw["document_text"])
        if raw.get("source_type") not in (None, ""):
            extracted["legacy_source_type"] = str(raw["source_type"])
        if item_value.get("status") not in (None, ""):
            extracted["legacy_status"] = str(item_value["status"])
        if item_value.get("reviewer_note") not in (None, ""):
            extracted["legacy_reviewer_note"] = str(item_value["reviewer_note"])
        suggestion = item_value.get("suggestion")
        if isinstance(suggestion, dict) and suggestion:
            extracted["legacy_suggestion_json"] = json.dumps(
                suggestion, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        records.append(
            replace(
                decoded,
                id=item_id,
                import_key=f"legacy-v1:{source_sha256}:{item_id}",
                attachment_sha256=None,
                evidence_status=EvidenceStatus.LEGACY_UNAVAILABLE,
                extracted=extracted,
            )
        )
    return tuple(records)


def _validated_events(workspace: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    for index, event in enumerate(workspace.get("events", []), start=1):
        if not isinstance(event, dict):
            raise ValueError(f"Legacy event {index} must be an object.")
        events.append(dict(event))
    return tuple(events)


def _write_private_backup(source: Path, source_bytes: bytes) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = source.with_name(f"{source.name}.backup-{stamp}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(backup, flags, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(source_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    os.chmod(backup, 0o600)
    if hashlib.sha256(backup.read_bytes()).digest() != hashlib.sha256(source_bytes).digest():
        backup.unlink(missing_ok=True)
        raise OSError("Legacy workspace backup verification failed.")
    directory_descriptor = os.open(source.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return backup


def _report_from_stored(payload: Mapping[str, Any]) -> MigrationReport:
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError("Stored migration report is invalid.")
    return MigrationReport.from_dict(report)
