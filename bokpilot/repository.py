"""Private transactional SQLite repository for Bokpilot workspace state."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from uuid import uuid4

from .domain import (
    AccountingMethod,
    CompanyProfile,
    EvidenceStatus,
    JournalLine,
    Money,
    PostingDraft,
    ReviewDecision,
    SourceKind,
    SourceRecord,
    TransactionNature,
    VatTreatment,
)


SCHEMA_VERSION = 2


@dataclass(frozen=True)
class MutationResult:
    revision: int
    inserted: int
    skipped: int
    ids: tuple[str, ...]


@dataclass(frozen=True)
class ReviewQueuePage:
    records: tuple[SourceRecord, ...]
    next_after: tuple[date, str] | None
    revision: int


class Repository:
    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self.path = Path(path)
        self.timeout = float(timeout)
        self._prepare_directory()
        self._initialize_schema()

    def _prepare_directory(self) -> None:
        parent = self.path.parent
        if parent in {Path("."), Path(parent.anchor)}:
            raise ValueError("Repository requires a dedicated data directory.")
        if parent.exists() and parent.is_symlink():
            raise ValueError("Repository data directory cannot be a symlink.")
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(parent, 0o700)
        if self.path.exists() and self.path.is_symlink():
            raise ValueError("Repository database cannot be a symlink.")
        if not self.path.exists():
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
            os.close(descriptor)
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {max(1, int(self.timeout * 1000))}")
        return connection

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()
            self._harden_files()

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(_SCHEMA_SQL)
            self._ensure_compatibility_columns(connection)
        finally:
            connection.close()
            self._harden_files()

    def _ensure_compatibility_columns(self, connection: sqlite3.Connection) -> None:
        additions = {
            "sources": {
                "raw_json": "TEXT NOT NULL DEFAULT '{}'",
                "source_label": "TEXT NOT NULL DEFAULT ''",
                "reviewer_note": "TEXT NOT NULL DEFAULT ''",
                "reviewed_at": "TEXT",
                "version": "INTEGER NOT NULL DEFAULT 1",
            },
            "source_attachments": {
                "original_filename": "TEXT NOT NULL DEFAULT ''",
                "media_type": "TEXT NOT NULL DEFAULT 'application/octet-stream'",
            },
            "import_batches": {
                "batch_type": "TEXT NOT NULL DEFAULT 'migration'",
                "status": "TEXT NOT NULL DEFAULT 'committed'",
                "updated_at": "TEXT",
            },
            "matches": {
                "score": "INTEGER NOT NULL DEFAULT 0",
                "reasons_json": "TEXT NOT NULL DEFAULT '[]'",
                "version": "INTEGER NOT NULL DEFAULT 1",
                "updated_at": "TEXT",
            },
            "reviews": {
                "decision_id": "TEXT",
                "prior_version": "INTEGER NOT NULL DEFAULT 1",
                "action": "TEXT NOT NULL DEFAULT 'reviewed'",
                "before_suggestion_json": "TEXT NOT NULL DEFAULT '{}'",
                "posting_json": "TEXT NOT NULL DEFAULT '{}'",
                "rule_id": "TEXT",
                "rule_version": "INTEGER",
            },
            "duplicate_candidates": {
                "version": "INTEGER NOT NULL DEFAULT 1",
            },
            "duplicate_decisions": {
                "decision_id": "TEXT",
                "prior_version": "INTEGER NOT NULL DEFAULT 1",
                "source_id": "TEXT",
            },
        }
        for table, table_additions in additions.items():
            columns = {
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            for name, definition in table_additions.items():
                if name not in columns:
                    connection.execute(
                        f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'
                    )

    def _harden_files(self) -> None:
        os.chmod(self.path.parent, 0o700)
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if candidate.exists():
                os.chmod(candidate, 0o600)

    @contextmanager
    def transaction(self) -> Iterator[RepositoryTransaction]:
        connection = self._connect()
        transaction: RepositoryTransaction | None = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            base_revision = int(
                connection.execute(
                    "SELECT revision FROM workspace_state WHERE id = 1"
                ).fetchone()["revision"]
            )
            transaction = RepositoryTransaction(connection, base_revision)
            yield transaction
            if transaction.dirty:
                connection.execute(
                    "UPDATE workspace_state SET revision = revision + 1 WHERE id = 1"
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            try:
                self._harden_files()
            finally:
                connection.close()
            self._harden_files()

    def import_sources(self, records: Sequence[SourceRecord]) -> MutationResult:
        with self.transaction() as transaction:
            return transaction.import_sources(records)

    def append_review(self, source_id: str, decision: ReviewDecision) -> MutationResult:
        with self.transaction() as transaction:
            return transaction.append_review(source_id, decision)

    def save_posting_draft(self, draft: PostingDraft) -> MutationResult:
        with self.transaction() as transaction:
            return transaction.save_posting_draft(draft)

    def record_attachment(
        self,
        source_id: str,
        *,
        path: Path,
        sha256: str,
        byte_count: int,
        original_filename: str = "",
        media_type: str = "application/octet-stream",
    ) -> MutationResult:
        _verify_registered_file(Path(path), sha256, byte_count)
        with self.transaction() as transaction:
            return transaction.record_attachment(
                source_id,
                path=Path(path),
                sha256=sha256,
                byte_count=byte_count,
                original_filename=original_filename,
                media_type=media_type,
            )

    def create_export_batch(
        self,
        *,
        format: str,
        artifact_path: Path,
        sha256: str,
        byte_count: int,
        source_ids: Sequence[str],
        expected_revision: int | None = None,
    ) -> MutationResult:
        _verify_registered_file(Path(artifact_path), sha256, byte_count)
        with self.transaction() as transaction:
            if expected_revision is not None:
                transaction.require_revision(expected_revision)
            return transaction.create_export_batch(
                format=format,
                artifact_path=artifact_path,
                sha256=sha256,
                byte_count=byte_count,
                source_ids=source_ids,
            )

    def backup_to(
        self,
        destination: Path,
        attachment_root: Path,
        export_root: Path,
    ) -> Any:
        from .backups import backup_repository

        return backup_repository(self, Path(destination), Path(attachment_root), Path(export_root))

    def snapshot_to(self, destination: Path) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(destination.parent, 0o700)
        if destination.exists():
            raise FileExistsError(f"Snapshot destination already exists: {destination}")
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
        source = self._connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
            os.chmod(destination, 0o600)
            self._harden_files()

    def workspace_revision(self) -> int:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT revision FROM workspace_state WHERE id = 1"
            ).fetchone()
            return int(row["revision"])

    def schema_version(self) -> int:
        with self._read_connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def schema_tables(self) -> set[str]:
        return self._schema_names("table")

    def schema_indexes(self) -> set[str]:
        return self._schema_names("index")

    def _schema_names(self, kind: str) -> set[str]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
            ).fetchall()
            return {str(row["name"]) for row in rows}

    def source_count(self) -> int:
        with self._read_connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])

    def company_profile(self) -> CompanyProfile | None:
        with self._read_connection() as connection:
            row = connection.execute("SELECT * FROM company_profile WHERE id = 1").fetchone()
        if row is None:
            return None
        return CompanyProfile(
            name=str(row["name"]),
            accounting_method=AccountingMethod(str(row["accounting_method"])),
            fiscal_year_start=date.fromisoformat(str(row["fiscal_year_start"])),
            fiscal_year_end=date.fromisoformat(str(row["fiscal_year_end"])),
            currency=str(row["currency"]),
            voucher_series=str(row["voucher_series"]),
            organization_number=(
                str(row["organization_number"]) if row["organization_number"] is not None else None
            ),
        )

    def save_company_profile(
        self,
        profile: CompanyProfile,
        *,
        expected_revision: int,
    ) -> MutationResult:
        with self.transaction() as transaction:
            transaction.require_revision(expected_revision)
            return transaction.save_company_profile(profile)

    def table_count(self, table: str) -> int:
        if table not in _APPLICATION_TABLES:
            raise ValueError(f"Unsupported table name: {table!r}")
        with self._read_connection() as connection:
            return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

    def connection_settings(self) -> dict[str, Any]:
        with self._read_connection() as connection:
            return {
                "foreign_keys": int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
                "busy_timeout": int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
                "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
            }

    def get_source(self, source_id: str) -> SourceRecord | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            return _source_from_row(row) if row is not None else None

    def all_sources(self) -> tuple[SourceRecord, ...]:
        with self._read_connection() as connection:
            rows = connection.execute("SELECT * FROM sources ORDER BY occurred_on, id").fetchall()
        return tuple(_source_from_row(row) for row in rows)

    def source_version(self, source_id: str) -> int:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT version FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown source id: {source_id}")
        return int(row["version"])

    def import_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT id, source_sha256, report_json, batch_type, status, created_at, updated_at "
                "FROM import_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["report"] = json.loads(str(payload.pop("report_json")))
        return payload

    def uncommitted_preview_ids(self) -> tuple[str, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT id FROM import_batches "
                "WHERE batch_type = 'preview' AND status = 'previewed' ORDER BY id"
            ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def match_record(self, match_id: str) -> dict[str, Any] | None:
        with self._read_connection() as connection:
            row = connection.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["reasons"] = tuple(json.loads(str(payload.pop("reasons_json"))))
        return payload

    def match_records_for_source(self, source_id: str) -> tuple[dict[str, Any], ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM matches WHERE source_id = ? ORDER BY id", (source_id,)
            ).fetchall()
        values = []
        for row in rows:
            payload = dict(row)
            payload["reasons"] = tuple(json.loads(str(payload.pop("reasons_json"))))
            values.append(payload)
        return tuple(values)

    def unresolved_duplicate_ids(self, source_id: str) -> tuple[str, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT id FROM duplicate_candidates WHERE status = 'unresolved' "
                "AND (source_id = ? OR candidate_source_id = ?) ORDER BY id",
                (source_id, source_id),
            ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def latest_suggestion_snapshot(self, source_id: str) -> dict[str, Any]:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM suggestions WHERE source_id = ? ORDER BY id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        return {} if row is None else dict(json.loads(str(row["snapshot_json"])))

    def review_history(self, source_id: str) -> tuple[dict[str, Any], ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT decision_id, prior_version, action, reviewer_note, risk_acknowledged, "
                "snapshot_json, before_suggestion_json, posting_json, rule_id, rule_version, created_at "
                "FROM reviews WHERE source_id = ? ORDER BY id",
                (source_id,),
            ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            history.append(
                {
                    "decision_id": str(row["decision_id"] or "legacy-review"),
                    "prior_version": int(row["prior_version"]),
                    "action": str(row["action"]),
                    "reviewer_note": str(row["reviewer_note"]),
                    "risk_acknowledged": bool(row["risk_acknowledged"]),
                    "selected": dict(json.loads(str(row["snapshot_json"]))),
                    "before_suggestion": dict(json.loads(str(row["before_suggestion_json"]))),
                    "posting": dict(json.loads(str(row["posting_json"]))),
                    "rule_id": str(row["rule_id"]) if row["rule_id"] is not None else None,
                    "rule_version": int(row["rule_version"]) if row["rule_version"] is not None else None,
                    "created_at": str(row["created_at"]),
                }
            )
        return tuple(history)

    def list_review_queue(
        self,
        *,
        limit: int = 100,
        after: tuple[date, str] | None = None,
    ) -> ReviewQueuePage:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Review queue limit must be between 1 and 1000.")
        with self._read_connection() as connection:
            connection.execute("BEGIN")
            if after is None:
                rows = connection.execute(
                    "SELECT * FROM sources WHERE status = ? "
                    "ORDER BY occurred_on, id LIMIT ?",
                    ("needs_review", limit + 1),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM sources WHERE status = ? "
                    "AND (occurred_on, id) > (?, ?) "
                    "ORDER BY occurred_on, id LIMIT ?",
                    ("needs_review", after[0].isoformat(), after[1], limit + 1),
                ).fetchall()
            revision = int(
                connection.execute(
                    "SELECT revision FROM workspace_state WHERE id = 1"
                ).fetchone()["revision"]
            )
            connection.commit()
        visible = rows[:limit]
        records = tuple(_source_from_row(row) for row in visible)
        next_after = None
        if len(rows) > limit and records:
            next_after = (records[-1].occurred_on, records[-1].id)
        return ReviewQueuePage(records, next_after, revision)

    def latest_review(self, source_id: str) -> ReviewDecision | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE source_id = ? ORDER BY id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return ReviewDecision(
            nature=TransactionNature(str(row["nature"])),
            account=str(row["account"]),
            vat=VatTreatment(str(row["vat"])),
            vat_minor=int(row["vat_minor"]) if row["vat_minor"] is not None else None,
            reviewer_note=str(row["reviewer_note"]),
            risk_acknowledged=bool(row["risk_acknowledged"]),
        )

    def latest_posting_draft(self, source_id: str) -> PostingDraft | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM posting_drafts WHERE source_id = ? ORDER BY id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        line_payloads = json.loads(str(row["lines_json"]))
        lines = tuple(
            JournalLine(
                account=str(line["account"]),
                account_name=str(line["account_name"]),
                debit_minor=int(line["debit_minor"]),
                credit_minor=int(line["credit_minor"]),
            )
            for line in line_payloads
        )
        return PostingDraft(
            source_id=str(row["source_id"]),
            lines=lines,
            rule_id=str(row["rule_id"]) if row["rule_id"] is not None else None,
            rule_version=int(row["rule_version"]) if row["rule_version"] is not None else None,
            issues=tuple(json.loads(str(row["issues_json"]))),
        )

    def migration_payload(self, source_sha256: str) -> dict[str, Any] | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT report_json FROM import_batches "
                "WHERE source_sha256 = ? AND batch_type = 'migration'",
                (source_sha256,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["report_json"]))
        if not isinstance(payload, dict):
            raise ValueError("Stored migration report is invalid.")
        return payload

    def migration_events(self, source_sha256: str) -> tuple[dict[str, Any], ...]:
        payload = self.migration_payload(source_sha256)
        if payload is None:
            return ()
        events = payload.get("events", [])
        if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
            raise ValueError("Stored migration events are invalid.")
        return tuple(dict(event) for event in events)

    def attachment_records(self) -> tuple[dict[str, Any], ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT id, source_id, path, sha256, byte_count "
                "FROM source_attachments ORDER BY id"
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def export_records(self) -> tuple[dict[str, Any], ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT id, format, artifact_path, sha256, byte_count, source_ids_json "
                "FROM export_batches ORDER BY id"
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def export_record(self, batch_id: str) -> dict[str, Any] | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT id, format, artifact_path, sha256, byte_count, source_ids_json, created_at "
                "FROM export_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def approved_review_payloads(self, review_ids: Sequence[str]) -> tuple[dict[str, Any], ...]:
        if not review_ids:
            raise ValueError("At least one review ID is required for export.")
        placeholders = ",".join("?" for _ in review_ids)
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT r.decision_id, r.source_id, r.action, r.snapshot_json, r.posting_json, "
                "r.created_at AS reviewed_at, s.occurred_on, s.amount_minor, s.currency, "
                "s.description, s.counterparty, s.kind, s.source_filename, s.source_row, "
                "s.attachment_sha256, s.status "
                "FROM reviews r JOIN sources s ON s.id = r.source_id "
                f"WHERE r.decision_id IN ({placeholders})",
                tuple(review_ids),
            ).fetchall()
            latest = {
                str(row["source_id"]): str(row["decision_id"] or "")
                for row in connection.execute(
                    "SELECT r.source_id, r.decision_id FROM reviews r "
                    "JOIN (SELECT source_id, MAX(id) AS max_id FROM reviews GROUP BY source_id) x "
                    "ON x.max_id = r.id"
                ).fetchall()
            }
        by_id = {str(row["decision_id"]): row for row in rows}
        if set(by_id) != set(review_ids):
            raise ValueError("One or more review IDs do not exist.")
        payloads: list[dict[str, Any]] = []
        for review_id in review_ids:
            row = by_id[review_id]
            source_id = str(row["source_id"])
            if row["action"] != "approved" or row["status"] != "approved" or latest.get(source_id) != review_id:
                raise ValueError(f"Review is not the current approved decision: {review_id}")
            posting = dict(json.loads(str(row["posting_json"])))
            payloads.append(
                {
                    "review_id": review_id,
                    "source_id": source_id,
                    "reviewed_at": str(row["reviewed_at"]),
                    "decision": dict(json.loads(str(row["snapshot_json"]))),
                    "date": str(row["occurred_on"]),
                    "amount_minor": int(row["amount_minor"]),
                    "currency": str(row["currency"]),
                    "description": str(row["description"]),
                    "counterparty": str(row["counterparty"]),
                    "kind": str(row["kind"]),
                    "source_filename": str(row["source_filename"]),
                    "source_row": int(row["source_row"]) if row["source_row"] is not None else None,
                    "source_sha256": str(row["attachment_sha256"]) if row["attachment_sha256"] else None,
                    "posting_lines": list(posting.get("lines", [])),
                }
            )
        return tuple(payloads)

    def compatibility_items(self) -> tuple[dict[str, Any], ...]:
        with self._read_connection() as connection:
            connection.execute("BEGIN")
            items = _compatibility_items_from_connection(connection)
            connection.commit()
        return items

    def workspace_events(self) -> tuple[dict[str, Any], ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM workspace_events ORDER BY id"
            ).fetchall()
        return tuple(dict(json.loads(str(row["payload_json"]))) for row in rows)

    def explain_query_plan(self, sql: str, parameters: Sequence[Any] = ()) -> tuple[str, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(f"EXPLAIN QUERY PLAN {sql}", tuple(parameters)).fetchall()
            return tuple(str(row[3]) for row in rows)


class RepositoryTransaction:
    def __init__(self, connection: sqlite3.Connection, base_revision: int):
        self._connection = connection
        self._base_revision = base_revision
        self.dirty = False

    @property
    def projected_revision(self) -> int:
        return self._base_revision + (1 if self.dirty else 0)

    @property
    def base_revision(self) -> int:
        return self._base_revision

    def compatibility_items(self) -> tuple[dict[str, Any], ...]:
        return _compatibility_items_from_connection(self._connection)

    def require_revision(self, expected_revision: int) -> None:
        if type(expected_revision) is not int:
            raise ValueError("Expected workspace revision must be an integer.")
        if self.base_revision != expected_revision:
            raise ValueError(
                f"Workspace revision conflict: expected {expected_revision}, "
                f"current {self.base_revision}."
            )

    def source_ids_for_import_keys(self, import_keys: Sequence[str]) -> dict[str, str]:
        if not import_keys:
            return {}
        placeholders = ",".join("?" for _ in import_keys)
        rows = self._connection.execute(
            f"SELECT id, import_key FROM sources WHERE import_key IN ({placeholders})",
            tuple(import_keys),
        ).fetchall()
        return {str(row["import_key"]): str(row["id"]) for row in rows}

    def source_count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])

    def save_company_profile(self, profile: CompanyProfile) -> MutationResult:
        if profile.fiscal_year_end < profile.fiscal_year_start:
            raise ValueError("Fiscal year end cannot precede its start.")
        self._connection.execute(
            "INSERT INTO company_profile "
            "(id, name, accounting_method, fiscal_year_start, fiscal_year_end, currency, "
            "voucher_series, organization_number, created_at) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
            "accounting_method = excluded.accounting_method, "
            "fiscal_year_start = excluded.fiscal_year_start, "
            "fiscal_year_end = excluded.fiscal_year_end, currency = excluded.currency, "
            "voucher_series = excluded.voucher_series, "
            "organization_number = excluded.organization_number",
            (
                profile.name,
                profile.accounting_method.value,
                profile.fiscal_year_start.isoformat(),
                profile.fiscal_year_end.isoformat(),
                profile.currency,
                profile.voucher_series,
                profile.organization_number,
                _now(),
            ),
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, ("company-profile",))

    def confirmed_match_total(self, source_id: str, *, excluding: str | None = None) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) AS total FROM matches "
            "WHERE status = 'confirmed' AND (source_id = ? OR matched_source_id = ?) "
            "AND (? IS NULL OR id <> ?)",
            (source_id, source_id, excluding, excluding),
        ).fetchone()
        return int(row["total"])

    def require_source_version_without_attachment(
        self,
        source_id: str,
        expected_version: int,
    ) -> None:
        row = self._connection.execute(
            "SELECT version, attachment_sha256 FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown source id: {source_id}")
        current = int(row["version"])
        if current != expected_version:
            raise ValueError(
                f"Source version conflict: expected {expected_version}, current {current}."
            )
        if row["attachment_sha256"] is not None:
            raise ValueError("Source evidence attachment already exists and cannot be overwritten.")

    def next_compatibility_item_number(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 4) AS INTEGER)), 0) "
            "FROM sources WHERE id GLOB 'BP-[0-9]*'"
        ).fetchone()
        return int(row[0]) + 1

    def import_sources(self, records: Iterable[SourceRecord]) -> MutationResult:
        inserted_ids: list[str] = []
        skipped = 0
        for record in records:
            try:
                self._connection.execute(_INSERT_SOURCE_SQL, _source_parameters(record))
            except sqlite3.IntegrityError:
                duplicate = self._connection.execute(
                    "SELECT 1 FROM sources WHERE id = ? OR import_key = ?",
                    (record.id, record.import_key),
                ).fetchone()
                if duplicate is None:
                    raise
                skipped += 1
            else:
                inserted_ids.append(record.id)
                self.dirty = True
        return MutationResult(
            self.projected_revision,
            len(inserted_ids),
            skipped,
            tuple(inserted_ids),
        )

    def append_review(self, source_id: str, decision: ReviewDecision) -> MutationResult:
        self._require_source(source_id)
        self._connection.execute(
            "INSERT INTO reviews (source_id, nature, account, vat, vat_minor, "
            "reviewer_note, risk_acknowledged, snapshot_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                decision.nature.value,
                decision.account,
                decision.vat.value,
                decision.vat_minor,
                decision.reviewer_note,
                int(decision.risk_acknowledged),
                json.dumps(_decision_payload(decision), sort_keys=True, separators=(",", ":")),
                _now(),
            ),
        )
        self._connection.execute(
            "UPDATE sources SET status = ? WHERE id = ?", ("reviewed", source_id)
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, (source_id,))

    def save_posting_draft(self, draft: PostingDraft) -> MutationResult:
        self._require_source(draft.source_id)
        self._connection.execute(
            "INSERT INTO posting_drafts (source_id, rule_id, rule_version, lines_json, "
            "issues_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                draft.source_id,
                draft.rule_id,
                draft.rule_version,
                json.dumps(
                    [
                        {
                            "account": line.account,
                            "account_name": line.account_name,
                            "debit_minor": line.debit_minor,
                            "credit_minor": line.credit_minor,
                        }
                        for line in draft.lines
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(list(draft.issues), separators=(",", ":")),
                _now(),
            ),
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, (draft.source_id,))

    def record_attachment(
        self,
        source_id: str,
        *,
        path: Path,
        sha256: str,
        byte_count: int,
        original_filename: str = "",
        media_type: str = "application/octet-stream",
    ) -> MutationResult:
        self._require_source(source_id)
        existing = self._connection.execute(
            "SELECT id FROM source_attachments WHERE source_id = ? AND sha256 = ?",
            (source_id, sha256),
        ).fetchone()
        if existing is not None:
            return MutationResult(self.projected_revision, 0, 1, ())
        identifier = f"attachment-{uuid4().hex}"
        self._connection.execute(
            "INSERT INTO source_attachments "
            "(id, source_id, sha256, path, byte_count, original_filename, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier,
                source_id,
                sha256,
                str(path),
                byte_count,
                original_filename,
                media_type,
                _now(),
            ),
        )
        self._connection.execute(
            "UPDATE sources SET attachment_sha256 = ?, evidence_status = ?, version = version + 1 "
            "WHERE id = ?",
            (sha256, EvidenceStatus.AVAILABLE.value, source_id),
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, (identifier,))

    def save_import_preview(
        self,
        *,
        batch_id: str,
        source_sha256: str,
        report: Mapping[str, Any],
    ) -> MutationResult:
        existing = self._connection.execute(
            "SELECT id FROM import_batches WHERE source_sha256 = ? AND batch_type = 'preview'",
            (source_sha256,),
        ).fetchone()
        if existing is not None:
            return MutationResult(self.projected_revision, 0, 1, (str(existing["id"]),))
        self._connection.execute(
            "INSERT INTO import_batches "
            "(id, source_sha256, report_json, batch_type, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'preview', 'previewed', ?, ?)",
            (
                batch_id,
                source_sha256,
                json.dumps(dict(report), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                _now(),
                _now(),
            ),
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, (batch_id,))

    def update_import_preview(
        self,
        batch_id: str,
        *,
        report: Mapping[str, Any],
        status: str,
    ) -> None:
        cursor = self._connection.execute(
            "UPDATE import_batches SET report_json = ?, status = ?, updated_at = ? "
            "WHERE id = ? AND batch_type = 'preview'",
            (
                json.dumps(dict(report), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                status,
                _now(),
                batch_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Unknown import batch: {batch_id}")
        self.dirty = True

    def delete_uncommitted_preview(self, batch_id: str) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM import_batches "
            "WHERE id = ? AND batch_type = 'preview' AND status = 'previewed'",
            (batch_id,),
        )
        if cursor.rowcount:
            self.dirty = True
            return True
        return False

    def create_duplicate_candidates(self, source_ids: Sequence[str]) -> tuple[str, ...]:
        created: list[str] = []
        for source_id in source_ids:
            source = self._connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            if source is None:
                continue
            rows = self._connection.execute(
                "SELECT id FROM sources WHERE id <> ? AND import_key <> ? "
                "AND occurred_on = ? AND amount_minor = ? AND currency = ? "
                "AND lower(trim(description)) = lower(trim(?))",
                (
                    source_id,
                    source["import_key"],
                    source["occurred_on"],
                    source["amount_minor"],
                    source["currency"],
                    source["description"],
                ),
            ).fetchall()
            for row in rows:
                pair = sorted((source_id, str(row["id"])))
                identifier = "duplicate-" + hashlib.sha256("\0".join(pair).encode()).hexdigest()[:24]
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO duplicate_candidates "
                    "(id, source_id, candidate_source_id, status, created_at) "
                    "VALUES (?, ?, ?, 'unresolved', ?)",
                    (identifier, pair[0], pair[1], _now()),
                )
                if cursor.rowcount:
                    created.append(identifier)
                    self.dirty = True
        return tuple(created)

    def decide_match(
        self,
        *,
        match_id: str,
        source_id: str,
        matched_source_id: str,
        decision: str,
        matched_minor: int,
        expected_version: int,
        score: int,
        reasons: Sequence[str],
    ) -> tuple[int, int]:
        self._require_source(source_id)
        self._require_source(matched_source_id)
        existing = self._connection.execute(
            "SELECT version FROM matches WHERE id = ?", (match_id,)
        ).fetchone()
        current_version = int(existing["version"]) if existing is not None else 1
        if current_version != expected_version:
            raise ValueError(
                f"Match version conflict: expected {expected_version}, current {current_version}."
            )
        if existing is None:
            new_version = 2
            self._connection.execute(
                "INSERT INTO matches "
                "(id, source_id, matched_source_id, amount_minor, status, score, reasons_json, "
                "version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    match_id,
                    source_id,
                    matched_source_id,
                    matched_minor,
                    decision,
                    score,
                    json.dumps(list(reasons), separators=(",", ":")),
                    new_version,
                    _now(),
                    _now(),
                ),
            )
        else:
            new_version = current_version + 1
            self._connection.execute(
                "UPDATE matches SET amount_minor = ?, status = ?, score = ?, reasons_json = ?, "
                "version = ?, updated_at = ? WHERE id = ?",
                (
                    matched_minor,
                    decision,
                    score,
                    json.dumps(list(reasons), separators=(",", ":")),
                    new_version,
                    _now(),
                    match_id,
                ),
            )
        self._connection.execute(
            "UPDATE sources SET version = version + 1 WHERE id IN (?, ?)",
            (source_id, matched_source_id),
        )
        self.add_workspace_event(
            {
                "type": "match_decision",
                "match_id": match_id,
                "source_id": source_id,
                "matched_source_id": matched_source_id,
                "decision": decision,
                "matched_minor": matched_minor,
            }
        )
        self.dirty = True
        source_version = int(
            self._connection.execute(
                "SELECT version FROM sources WHERE id = ?", (source_id,)
            ).fetchone()["version"]
        )
        return new_version, source_version

    def record_review_revision(
        self,
        source_id: str,
        *,
        decision: ReviewDecision,
        draft: PostingDraft,
        action: str,
        expected_version: int,
        before_suggestion: Mapping[str, Any],
    ) -> tuple[str, int]:
        row = self._connection.execute(
            "SELECT version FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown source id: {source_id}")
        current = int(row["version"])
        if current != expected_version:
            raise ValueError(
                f"Item version conflict: expected {expected_version}, current {current}."
            )
        decision_id = f"review-{uuid4().hex}"
        posting_payload = {
            "source_id": draft.source_id,
            "lines": [
                {
                    "account": line.account,
                    "account_name": line.account_name,
                    "debit_minor": line.debit_minor,
                    "credit_minor": line.credit_minor,
                }
                for line in draft.lines
            ],
            "issues": list(draft.issues),
        }
        self._connection.execute(
            "INSERT INTO reviews "
            "(source_id, nature, account, vat, vat_minor, reviewer_note, risk_acknowledged, "
            "snapshot_json, created_at, decision_id, prior_version, action, "
            "before_suggestion_json, posting_json, rule_id, rule_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                decision.nature.value,
                decision.account,
                decision.vat.value,
                decision.vat_minor,
                decision.reviewer_note,
                int(decision.risk_acknowledged),
                json.dumps(_decision_payload(decision), sort_keys=True, separators=(",", ":")),
                _now(),
                decision_id,
                current,
                action,
                json.dumps(dict(before_suggestion), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                json.dumps(posting_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                draft.rule_id,
                draft.rule_version,
            ),
        )
        status = {"approved": "approved", "rejected": "rejected", "reopened": "needs_review"}[action]
        self._connection.execute(
            "UPDATE sources SET status = ?, reviewer_note = ?, reviewed_at = ?, "
            "version = version + 1 WHERE id = ?",
            (status, decision.reviewer_note, _now(), source_id),
        )
        self.dirty = True
        return decision_id, current + 1

    def record_duplicate_decision_revision(
        self,
        source_id: str,
        *,
        candidate_id: str,
        decision: str,
        note: str,
        expected_version: int,
    ) -> tuple[str, int]:
        source = self._connection.execute(
            "SELECT version FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if source is None:
            raise ValueError(f"Unknown source id: {source_id}")
        current = int(source["version"])
        if current != expected_version:
            raise ValueError(
                f"Item version conflict: expected {expected_version}, current {current}."
            )
        candidate = self._connection.execute(
            "SELECT version, source_id, candidate_source_id FROM duplicate_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if candidate is None or source_id not in {
            str(candidate["source_id"]),
            str(candidate["candidate_source_id"]),
        }:
            raise ValueError("Unknown duplicate candidate for this source.")
        decision_id = f"duplicate-decision-{uuid4().hex}"
        self._connection.execute(
            "INSERT INTO duplicate_decisions "
            "(candidate_id, decision, reviewer_note, created_at, decision_id, prior_version, source_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                candidate_id,
                decision,
                note,
                _now(),
                decision_id,
                int(candidate["version"]),
                source_id,
            ),
        )
        self._connection.execute(
            "UPDATE duplicate_candidates SET status = ?, version = version + 1 WHERE id = ?",
            (decision, candidate_id),
        )
        status = "duplicate" if decision == "confirmed_duplicate" else "needs_review"
        self._connection.execute(
            "UPDATE sources SET status = ?, version = version + 1 WHERE id = ?",
            (status, source_id),
        )
        self.add_workspace_event(
            {
                "type": "duplicate_decision",
                "decision_id": decision_id,
                "candidate_id": candidate_id,
                "source_id": source_id,
                "decision": decision,
                "note": note,
            }
        )
        return decision_id, current + 1

    def set_source_compatibility(
        self,
        source_id: str,
        *,
        source_label: str,
        raw: Mapping[str, Any],
        status: str = "needs_review",
        reviewer_note: str = "",
        reviewed_at: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self._require_source(source_id)
        self._connection.execute(
            "UPDATE sources SET source_label = ?, raw_json = ?, status = ?, "
            "reviewer_note = ?, reviewed_at = ?, created_at = COALESCE(?, created_at) "
            "WHERE id = ?",
            (
                source_label,
                json.dumps(dict(raw), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                status,
                reviewer_note,
                reviewed_at,
                created_at,
                source_id,
            ),
        )
        self.dirty = True

    def save_suggestion_snapshot(self, source_id: str, snapshot: Mapping[str, Any]) -> None:
        self._require_source(source_id)
        rule_id = snapshot.get("rule_id")
        rule_version = snapshot.get("rule_version")
        self._connection.execute(
            "INSERT INTO suggestions "
            "(source_id, rule_id, rule_version, snapshot_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                source_id,
                str(rule_id) if rule_id is not None else None,
                int(rule_version) if rule_version is not None else None,
                json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                _now(),
            ),
        )
        self.dirty = True

    def set_compatibility_review(
        self,
        source_id: str,
        *,
        status: str,
        reviewer_note: str,
        reviewed_at: str | None,
    ) -> None:
        self._require_source(source_id)
        self._connection.execute(
            "UPDATE sources SET status = ?, reviewer_note = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewer_note, reviewed_at, source_id),
        )
        self.dirty = True

    def add_workspace_event(self, payload: Mapping[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO workspace_events (payload_json, created_at) VALUES (?, ?)",
            (
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                _now(),
            ),
        )
        self.dirty = True

    def reset_workspace(self) -> bool:
        before = self._connection.total_changes
        for table in (
            "duplicate_decisions",
            "matches",
            "duplicate_candidates",
            "posting_drafts",
            "reviews",
            "suggestions",
            "source_attachments",
            "sources",
            "export_batches",
            "import_batches",
            "company_profile",
            "workspace_events",
        ):
            self._connection.execute(f'DELETE FROM "{table}"')
        changed = self._connection.total_changes > before
        self.dirty = self.dirty or changed
        return changed

    def create_export_batch(
        self,
        *,
        format: str,
        artifact_path: Path,
        sha256: str,
        byte_count: int,
        source_ids: Sequence[str],
    ) -> MutationResult:
        if type(byte_count) is not int or byte_count < 0:
            raise ValueError("Export byte_count must be a non-negative integer.")
        identifier = f"export-{uuid4().hex}"
        self._connection.execute(
            "INSERT INTO export_batches (id, format, artifact_path, sha256, byte_count, "
            "source_ids_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                identifier,
                str(format),
                str(artifact_path),
                str(sha256),
                byte_count,
                json.dumps(list(source_ids), separators=(",", ":")),
                _now(),
            ),
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, (identifier,))

    def record_import_batch(
        self,
        *,
        batch_id: str,
        source_sha256: str,
        report: dict[str, Any],
        events: Sequence[dict[str, Any]],
    ) -> MutationResult:
        existing = self._connection.execute(
            "SELECT 1 FROM import_batches WHERE source_sha256 = ? AND batch_type = 'migration'",
            (source_sha256,),
        ).fetchone()
        if existing is not None:
            return MutationResult(self.projected_revision, 0, 1, ())
        payload = {"report": dict(report), "events": [dict(event) for event in events]}
        self._connection.execute(
            "INSERT INTO import_batches "
            "(id, source_sha256, report_json, batch_type, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'migration', 'committed', ?, ?)",
            (
                batch_id,
                source_sha256,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                _now(),
                _now(),
            ),
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, (batch_id,))

    def migration_payload(self, source_sha256: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT report_json FROM import_batches "
            "WHERE source_sha256 = ? AND batch_type = 'migration'",
            (source_sha256,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["report_json"]))
        if not isinstance(payload, dict):
            raise ValueError("Stored migration report is invalid.")
        return payload

    def _require_source(self, source_id: str) -> None:
        if self._connection.execute(
            "SELECT 1 FROM sources WHERE id = ?", (source_id,)
        ).fetchone() is None:
            raise ValueError(f"Unknown source id: {source_id}")


def _source_parameters(record: SourceRecord) -> tuple[Any, ...]:
    return (
        record.id,
        record.kind.value,
        record.occurred_on.isoformat(),
        record.amount.minor,
        record.amount.currency,
        record.description,
        record.counterparty,
        record.source_filename,
        record.source_row,
        record.import_key,
        record.attachment_sha256,
        record.evidence_status.value,
        json.dumps(dict(record.extracted), sort_keys=True, separators=(",", ":")),
        record.source_vat.value if record.source_vat is not None else None,
        record.source_vat_minor,
        record.matched_source_id,
        int(record.high_risk),
        json.dumps(_source_raw_payload(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "",
        "needs_review",
        "",
        None,
        _now(),
    )


def _source_from_row(row: sqlite3.Row) -> SourceRecord:
    return SourceRecord(
        id=str(row["id"]),
        kind=SourceKind(str(row["kind"])),
        occurred_on=date.fromisoformat(str(row["occurred_on"])),
        amount=Money(int(row["amount_minor"]), str(row["currency"])),
        description=str(row["description"]),
        counterparty=str(row["counterparty"]),
        source_filename=str(row["source_filename"]),
        source_row=int(row["source_row"]) if row["source_row"] is not None else None,
        import_key=str(row["import_key"]),
        attachment_sha256=(
            str(row["attachment_sha256"]) if row["attachment_sha256"] is not None else None
        ),
        evidence_status=EvidenceStatus(str(row["evidence_status"])),
        extracted=dict(json.loads(str(row["extracted_json"]))),
        source_vat=(VatTreatment(str(row["source_vat"])) if row["source_vat"] is not None else None),
        source_vat_minor=(
            int(row["source_vat_minor"]) if row["source_vat_minor"] is not None else None
        ),
        matched_source_id=(
            str(row["matched_source_id"]) if row["matched_source_id"] is not None else None
        ),
        high_risk=bool(row["high_risk"]),
    )


def _decision_payload(decision: ReviewDecision) -> dict[str, Any]:
    return {
        "nature": decision.nature.value,
        "account": decision.account,
        "vat": decision.vat.value,
        "vat_minor": decision.vat_minor,
        "reviewer_note": decision.reviewer_note,
        "risk_acknowledged": decision.risk_acknowledged,
    }


def _source_raw_payload(record: SourceRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "date": record.occurred_on.isoformat(),
        "description": record.description,
        "counterparty": record.counterparty,
        "amount_minor": record.amount.minor,
        "currency": record.amount.currency,
        "source_type": record.kind.value,
        "source_filename": record.source_filename,
        "source_row": record.source_row,
        "import_key": record.import_key,
        "evidence_status": record.evidence_status.value,
        "extracted": dict(record.extracted),
    }
    if record.attachment_sha256 is not None:
        payload["attachment_sha256"] = record.attachment_sha256
    if record.source_vat is not None:
        payload["vat_treatment"] = record.source_vat.value
    if record.source_vat_minor is not None:
        payload["vat_amount_minor"] = record.source_vat_minor
    if record.matched_source_id is not None:
        payload["matched_source_id"] = record.matched_source_id
    if record.high_risk:
        payload["high_risk"] = True
    return payload


def _compatibility_items_from_connection(
    connection: sqlite3.Connection,
) -> tuple[dict[str, Any], ...]:
    rows = connection.execute(
        "SELECT s.*, "
        "(SELECT snapshot_json FROM suggestions sg WHERE sg.source_id = s.id "
        " ORDER BY sg.id DESC LIMIT 1) AS suggestion_json "
        ", (SELECT decision_id FROM reviews rv WHERE rv.source_id = s.id "
        " ORDER BY rv.id DESC LIMIT 1) AS review_id "
        ", (SELECT COUNT(*) FROM duplicate_candidates dc WHERE dc.status = 'unresolved' "
        " AND (dc.source_id = s.id OR dc.candidate_source_id = s.id)) AS unresolved_duplicates "
        "FROM sources s ORDER BY s.created_at, s.id"
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        suggestion_json = row["suggestion_json"]
        suggestion = json.loads(str(suggestion_json)) if suggestion_json is not None else {}
        status = str(row["status"])
        items.append(
            {
                "id": str(row["id"]),
                "source": str(row["source_label"]),
                "raw": dict(json.loads(str(row["raw_json"]))),
                "suggestion": dict(suggestion),
                "status": status,
                "human_reviewed": status in {"approved", "rejected"},
                "reviewer_note": str(row["reviewer_note"]),
                "reviewed_at": str(row["reviewed_at"]) if row["reviewed_at"] is not None else None,
                "version": int(row["version"]),
                "review_id": str(row["review_id"]) if row["review_id"] is not None else None,
                "unresolved_duplicates": int(row["unresolved_duplicates"]),
                "created_at": str(row["created_at"]),
            }
        )
    return tuple(items)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _verify_registered_file(path: Path, expected_sha256: str, expected_size: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Registered artifact must be a regular file: {path}")
    if type(expected_size) is not int or expected_size < 0:
        raise ValueError("Registered artifact byte count must be a non-negative integer.")
    data = path.read_bytes()
    if len(data) != expected_size:
        raise ValueError("Registered artifact byte count does not match the file.")
    if hashlib.sha256(data).hexdigest() != str(expected_sha256).lower():
        raise ValueError("Registered artifact hash does not match the file.")
    os.chmod(path.parent, 0o700)
    os.chmod(path, 0o600)


def restore_from(backup: Path, destination_root: Path, expected_sha256: str) -> Any:
    from .backups import restore_backup

    return restore_backup(Path(backup), Path(destination_root), str(expected_sha256))


_INSERT_SOURCE_SQL = """
INSERT INTO sources (
    id, kind, occurred_on, amount_minor, currency, description, counterparty,
    source_filename, source_row, import_key, attachment_sha256, evidence_status,
    extracted_json, source_vat, source_vat_minor, matched_source_id, high_risk,
    raw_json, source_label, status, reviewer_note, reviewed_at, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


_APPLICATION_TABLES = {
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
    "workspace_events",
}


_SCHEMA_SQL = f"""
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS workspace_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL CHECK (revision >= 0)
);
INSERT OR IGNORE INTO workspace_state (id, revision) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS company_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    accounting_method TEXT NOT NULL,
    fiscal_year_start TEXT NOT NULL,
    fiscal_year_end TEXT NOT NULL,
    currency TEXT NOT NULL,
    voucher_series TEXT NOT NULL,
    organization_number TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    occurred_on TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    description TEXT NOT NULL,
    counterparty TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_row INTEGER,
    import_key TEXT NOT NULL,
    attachment_sha256 TEXT,
    evidence_status TEXT NOT NULL,
    extracted_json TEXT NOT NULL,
    source_vat TEXT,
    source_vat_minor INTEGER,
    matched_source_id TEXT,
    high_risk INTEGER NOT NULL DEFAULT 0 CHECK (high_risk IN (0, 1)),
    raw_json TEXT NOT NULL,
    source_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    reviewer_note TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_attachments (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    original_filename TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    created_at TEXT NOT NULL,
    UNIQUE (source_id, sha256)
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    rule_id TEXT,
    rule_version INTEGER,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    nature TEXT NOT NULL,
    account TEXT NOT NULL,
    vat TEXT NOT NULL,
    vat_minor INTEGER,
    reviewer_note TEXT NOT NULL,
    risk_acknowledged INTEGER NOT NULL CHECK (risk_acknowledged IN (0, 1)),
    snapshot_json TEXT NOT NULL,
    decision_id TEXT,
    prior_version INTEGER NOT NULL DEFAULT 1,
    action TEXT NOT NULL DEFAULT 'reviewed',
    before_suggestion_json TEXT NOT NULL DEFAULT '{{}}',
    posting_json TEXT NOT NULL DEFAULT '{{}}',
    rule_id TEXT,
    rule_version INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posting_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    rule_id TEXT,
    rule_version INTEGER,
    lines_json TEXT NOT NULL,
    issues_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    report_json TEXT NOT NULL,
    batch_type TEXT NOT NULL DEFAULT 'migration',
    status TEXT NOT NULL DEFAULT 'committed',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    candidate_source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS duplicate_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES duplicate_candidates(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL,
    reviewer_note TEXT NOT NULL,
    decision_id TEXT,
    prior_version INTEGER NOT NULL DEFAULT 1,
    source_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    matched_source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    amount_minor INTEGER NOT NULL,
    status TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS export_batches (
    id TEXT PRIMARY KEY,
    format TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    source_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS source_import_key_uq
ON sources(import_key);

CREATE UNIQUE INDEX IF NOT EXISTS import_batch_type_hash_uq
ON import_batches(batch_type, source_sha256);

CREATE INDEX IF NOT EXISTS review_queue_idx
ON sources(status, occurred_on, id);

CREATE INDEX IF NOT EXISTS matches_source_idx
ON matches(source_id, status);

PRAGMA user_version = {SCHEMA_VERSION};
COMMIT;
"""
