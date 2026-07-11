"""Private transactional SQLite repository for Bokpilot workspace state."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from uuid import uuid4

from .domain import (
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
        finally:
            connection.close()
            self._harden_files()

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

    def create_export_batch(
        self,
        *,
        format: str,
        artifact_path: Path,
        sha256: str,
        byte_count: int,
        source_ids: Sequence[str],
    ) -> MutationResult:
        with self.transaction() as transaction:
            return transaction.create_export_batch(
                format=format,
                artifact_path=artifact_path,
                sha256=sha256,
                byte_count=byte_count,
                source_ids=source_ids,
            )

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
                "SELECT report_json FROM import_batches WHERE source_sha256 = ?",
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
            "SELECT 1 FROM import_batches WHERE source_sha256 = ?", (source_sha256,)
        ).fetchone()
        if existing is not None:
            return MutationResult(self.projected_revision, 0, 1, ())
        payload = {"report": dict(report), "events": [dict(event) for event in events]}
        self._connection.execute(
            "INSERT INTO import_batches (id, source_sha256, report_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                batch_id,
                source_sha256,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                _now(),
            ),
        )
        self.dirty = True
        return MutationResult(self.projected_revision, 1, 0, (batch_id,))

    def migration_payload(self, source_sha256: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT report_json FROM import_batches WHERE source_sha256 = ?",
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
        "needs_review",
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


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_INSERT_SOURCE_SQL = """
INSERT INTO sources (
    id, kind, occurred_on, amount_minor, currency, description, counterparty,
    source_filename, source_row, import_key, attachment_sha256, evidence_status,
    extracted_json, source_vat, source_vat_minor, matched_source_id, high_risk,
    status, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
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
    source_sha256 TEXT NOT NULL UNIQUE,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    candidate_source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS duplicate_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES duplicate_candidates(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL,
    reviewer_note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    matched_source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    amount_minor INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
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

CREATE UNIQUE INDEX IF NOT EXISTS source_import_key_uq
ON sources(import_key);

CREATE INDEX IF NOT EXISTS review_queue_idx
ON sources(status, occurred_on, id);

CREATE INDEX IF NOT EXISTS matches_source_idx
ON matches(source_id, status);

PRAGMA user_version = {SCHEMA_VERSION};
COMMIT;
"""
