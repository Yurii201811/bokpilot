"""Previewed, byte-preserving and idempotent local imports."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .domain import EvidenceStatus, Money, SourceKind, SourceRecord
from .parsers import (
    _bank_amount,
    _first,
    _is_blank_csv_row,
    _normalize_header,
    _sniff_csv_dialect,
    parse_date,
    parse_document_text,
    parse_money,
)
from .repository import Repository
from .serialization import decode_source, normalize_source


MAX_DECODED_BYTES = 10 * 1024 * 1024
SUPPORTED_CHARSETS = {"utf-8": "utf-8", "utf-8-sig": "utf-8-sig", "windows-1252": "cp1252"}


@dataclass(frozen=True)
class ImportIssue:
    source_row: int | None
    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_row": self.source_row,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ImportPreview:
    batch_id: str
    kind: SourceKind
    source_filename: str
    media_type: str
    source_sha256: str
    decoded_bytes: int
    candidates: tuple[SourceRecord, ...]
    issues: tuple[ImportIssue, ...]
    committed: bool
    column_mapping: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "kind": self.kind.value,
            "source_filename": self.source_filename,
            "media_type": self.media_type,
            "source_sha256": self.source_sha256,
            "decoded_bytes": self.decoded_bytes,
            "candidates": [_record_payload(record) for record in self.candidates],
            "issues": [issue.to_dict() for issue in self.issues],
            "committed": self.committed,
            "column_mapping": dict(self.column_mapping),
        }


@dataclass(frozen=True)
class ImportCommit:
    batch_id: str
    created_ids: tuple[str, ...]
    existing_ids: tuple[str, ...]
    issue_count: int
    workspace_revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "created_ids": list(self.created_ids),
            "existing_ids": list(self.existing_ids),
            "issue_count": self.issue_count,
            "workspace_revision": self.workspace_revision,
        }


def preview_import(repository: Repository, request: Mapping[str, Any]) -> ImportPreview:
    try:
        kind = SourceKind(str(request.get("kind") or ""))
    except ValueError as exc:
        raise ValueError("Import kind must be bank_transaction, receipt, supplier_invoice, or customer_invoice.") from exc
    if kind is SourceKind.MANUAL:
        raise ValueError("Manual entries do not use file import preview.")
    filename = Path(str(request.get("filename") or "")).name
    if not filename:
        raise ValueError("Import filename is required.")
    media_type = str(request.get("media_type") or "application/octet-stream").strip().lower()
    encoded = request.get("content_base64")
    if not isinstance(encoded, str):
        raise ValueError("Import content_base64 is required.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Import content is not valid base64.") from exc
    if len(content) > MAX_DECODED_BYTES:
        raise ValueError("Decoded import content exceeds the 10 MiB limit.")

    charset = _charset(media_type)
    try:
        text = content.decode(charset)
    except UnicodeDecodeError as exc:
        raise ValueError(f"Import content cannot be decoded as {charset}.") from exc
    source_sha256 = hashlib.sha256(content).hexdigest()
    batch_id = f"import-{uuid4().hex}"
    if kind is SourceKind.BANK_TRANSACTION:
        requested_mapping = request.get("column_mapping")
        if requested_mapping is not None and not isinstance(requested_mapping, Mapping):
            raise ValueError("Import column_mapping must be an object.")
        candidates, issues, mapping = _preview_bank_csv(
            text,
            filename=filename,
            locale=str(request.get("locale") or "auto"),
            source_sha256=source_sha256,
            requested_mapping=requested_mapping,
        )
    else:
        candidates, issues, mapping = _preview_document(
            kind, text, filename=filename, source_sha256=source_sha256
        )
    preview = ImportPreview(
        batch_id=batch_id,
        kind=kind,
        source_filename=filename,
        media_type=media_type,
        source_sha256=source_sha256,
        decoded_bytes=len(content),
        candidates=tuple(candidates),
        issues=tuple(issues),
        committed=False,
        column_mapping=mapping,
    )
    with repository.transaction() as transaction:
        result = transaction.save_import_preview(
            batch_id=batch_id,
            source_sha256=source_sha256,
            report=preview.to_dict(),
        )
    actual_batch_id = result.ids[0]
    if result.skipped:
        existing = get_import_preview(repository, actual_batch_id)
        if not existing.committed and request.get("column_mapping") is not None and (
            existing.column_mapping != preview.column_mapping
            or existing.issues != preview.issues
            or existing.candidates != preview.candidates
        ):
            replacement = replace(preview, batch_id=actual_batch_id)
            with repository.transaction() as transaction:
                transaction.update_import_preview(
                    actual_batch_id,
                    report=replacement.to_dict(),
                    status="previewed",
                )
            return replacement
        return existing
    try:
        _write_private_file(_staging_path(repository, batch_id), content)
    except BaseException:
        with repository.transaction() as transaction:
            transaction.delete_uncommitted_preview(batch_id)
        raise
    return preview


def get_import_preview(repository: Repository, batch_id: str) -> ImportPreview:
    batch = repository.import_batch(batch_id)
    if batch is None or batch["batch_type"] != "preview":
        raise ValueError(f"Unknown import batch: {batch_id}")
    return _preview_from_payload(batch["report"])


def commit_import(
    repository: Repository,
    batch_id: str,
    *,
    expected_workspace_revision: int,
) -> ImportCommit:
    preview = get_import_preview(repository, batch_id)
    if preview.committed:
        imported_ids = tuple(
            str(value) for value in repository.import_batch(batch_id)["report"].get("imported_ids", [])
        )
        return ImportCommit(
            batch_id,
            (),
            imported_ids,
            len(preview.issues),
            repository.workspace_revision(),
        )
    if any(issue.code == "mapping_required" for issue in preview.issues):
        raise ValueError("Import column mapping must be completed before commit.")
    staged = _staging_path(repository, batch_id)
    if not staged.is_file():
        raise ValueError("Import staging bytes are unavailable; create a new preview.")
    content = staged.read_bytes()
    if len(content) != preview.decoded_bytes or hashlib.sha256(content).hexdigest() != preview.source_sha256:
        raise ValueError("Import staging bytes failed integrity verification.")
    attachment = repository.path.parent / "attachments" / preview.source_sha256

    import_keys = [record.import_key for record in preview.candidates]
    attachment_created = False
    try:
        with repository.transaction() as transaction:
            transaction.require_revision(expected_workspace_revision)
            attachment_created = _write_private_file(attachment, content, allow_identical=True)
            before = transaction.source_ids_for_import_keys(import_keys)
            result = transaction.import_sources(preview.candidates)
            after = transaction.source_ids_for_import_keys(import_keys)
            for source_id in result.ids:
                transaction.record_attachment(
                    source_id,
                    path=attachment,
                    sha256=preview.source_sha256,
                    byte_count=preview.decoded_bytes,
                    original_filename=preview.source_filename,
                    media_type=preview.media_type,
                )
            transaction.create_duplicate_candidates(result.ids)
            imported_ids = tuple(after[key] for key in import_keys)
            committed_payload = preview.to_dict()
            committed_payload["committed"] = True
            committed_payload["imported_ids"] = list(imported_ids)
            transaction.update_import_preview(batch_id, report=committed_payload, status="committed")
            existing_ids = tuple(after[key] for key in import_keys if key in before)
            revision = transaction.projected_revision
    except BaseException:
        if attachment_created:
            attachment.unlink(missing_ok=True)
        raise
    try:
        staged.unlink()
    except FileNotFoundError:
        pass
    return ImportCommit(
        batch_id,
        result.ids,
        existing_ids,
        len(preview.issues),
        revision,
    )


def attach_source_evidence(
    repository: Repository,
    source_id: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    filename = Path(str(request.get("filename") or "")).name
    media_type = str(request.get("media_type") or "application/octet-stream").strip().lower()
    expected_version = request.get("expected_version")
    if not filename:
        raise ValueError("Attachment filename is required.")
    if type(expected_version) is not int:
        raise ValueError("Attachment expected_version must be an integer.")
    encoded = request.get("content_base64")
    if not isinstance(encoded, str):
        raise ValueError("Attachment content_base64 is required.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Attachment content is not valid base64.") from exc
    if len(content) > MAX_DECODED_BYTES:
        raise ValueError("Decoded attachment content exceeds the 10 MiB limit.")
    sha256 = hashlib.sha256(content).hexdigest()
    path = repository.path.parent / "attachments" / sha256
    attachment_created = False
    try:
        with repository.transaction() as transaction:
            transaction.require_source_version_without_attachment(source_id, expected_version)
            attachment_created = _write_private_file(path, content, allow_identical=True)
            transaction.record_attachment(
                source_id,
                path=path,
                sha256=sha256,
                byte_count=len(content),
                original_filename=filename,
                media_type=media_type,
            )
            transaction.add_workspace_event(
                {
                    "type": "attachment_added",
                    "source_id": source_id,
                    "sha256": sha256,
                    "byte_count": len(content),
                    "filename": filename,
                    "media_type": media_type,
                }
            )
            revision = transaction.projected_revision
    except BaseException:
        if attachment_created:
            path.unlink(missing_ok=True)
        raise
    return {
        "source_id": source_id,
        "source_version": expected_version + 1,
        "workspace_revision": revision,
        "sha256": sha256,
        "byte_count": len(content),
    }


def cleanup_abandoned_previews(
    repository: Repository,
    *,
    now: float | None = None,
) -> tuple[str, ...]:
    """Delete only uncommitted staging files older than 24 hours."""
    current = time.time() if now is None else float(now)
    removed: list[str] = []
    for batch_id in repository.uncommitted_preview_ids():
        staged = _staging_path(repository, batch_id)
        if not staged.is_file() or current - staged.stat().st_mtime < 24 * 60 * 60:
            continue
        with repository.transaction() as transaction:
            if not transaction.delete_uncommitted_preview(batch_id):
                continue
        staged.unlink(missing_ok=True)
        removed.append(batch_id)
    return tuple(removed)


def _preview_bank_csv(
    text: str,
    *,
    filename: str,
    locale: str,
    source_sha256: str,
    requested_mapping: Mapping[str, Any] | None = None,
) -> tuple[list[SourceRecord], list[ImportIssue], dict[str, str]]:
    dialect = _sniff_csv_dialect(text[:2048])
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return [], [ImportIssue(None, "header", "missing_header", "CSV file has no header row.")], {}
    mapping = _detected_mapping(reader.fieldnames)
    normalized_headers = {_normalize_header(value) for value in reader.fieldnames}
    for field, header in dict(requested_mapping or {}).items():
        if field not in {"date", "description", "amount", "debit", "credit", "currency", "counterparty"}:
            raise ValueError(f"Unsupported column mapping field: {field}.")
        normalized_header = _normalize_header(str(header))
        if normalized_header not in normalized_headers:
            raise ValueError(f"Mapped CSV column does not exist: {header}.")
        mapping[field] = normalized_header
    missing = [field for field in ("date", "amount") if field not in mapping]
    issues = [
        ImportIssue(None, field, "mapping_required", f"Choose the CSV column for {field}.")
        for field in missing
    ]
    candidates: list[SourceRecord] = []
    for line_number, row in enumerate(reader, start=2):
        if _is_blank_csv_row(row):
            continue
        normalized = {_normalize_header(key): value for key, value in row.items()}
        try:
            date_value = _first(normalized, (mapping.get("date", "date"),))
            currency = str(_first(normalized, (mapping.get("currency", "currency"), "valuta")) or "SEK").strip().upper()
            amount = _mapped_amount(normalized, mapping, currency, locale)
            if not date_value:
                raise ValueError("Date value is required.")
            if amount is None:
                raise ValueError("Amount value is required.")
            occurred_on = parse_date(date_value)
        except ValueError as exc:
            field = "date" if "date" in str(exc).lower() else "amount"
            issues.append(ImportIssue(line_number, field, f"invalid_{field}", str(exc)))
            continue
        description = _first(
            normalized,
            (mapping.get("description", "description"), "beskrivning", "text", "meddelande", "referens"),
        )
        counterparty = _first(
            normalized,
            (mapping.get("counterparty", "counterparty"), "motpart", "namn", "payee"),
        )
        import_key = f"sha256:{source_sha256}:{line_number}:{SourceKind.BANK_TRANSACTION.value}"
        candidates.append(
            SourceRecord(
                id=_source_id(import_key),
                kind=SourceKind.BANK_TRANSACTION,
                occurred_on=occurred_on,
                amount=amount,
                description=str(description or "Bank transaction"),
                counterparty=str(counterparty or ""),
                source_filename=filename,
                source_row=line_number,
                import_key=import_key,
                attachment_sha256=source_sha256,
                evidence_status=EvidenceStatus.AVAILABLE,
                extracted={key: str(value) for key, value in normalized.items() if value not in (None, "")},
            )
        )
    return candidates, issues, mapping


def _mapped_amount(
    normalized: Mapping[str, Any],
    mapping: Mapping[str, str],
    currency: str,
    locale: str,
) -> Money | None:
    amount_column = mapping.get("amount")
    if amount_column and amount_column != "debit+credit":
        value = normalized.get(amount_column)
        return parse_money(value, locale, currency) if value not in (None, "") else None
    if mapping.get("debit") or mapping.get("credit"):
        debit_value = normalized.get(mapping.get("debit", ""))
        credit_value = normalized.get(mapping.get("credit", ""))
        debit = parse_money(debit_value, locale, currency) if debit_value not in (None, "") else Money(0, currency)
        credit = parse_money(credit_value, locale, currency) if credit_value not in (None, "") else Money(0, currency)
        if debit.minor == 0 and credit.minor == 0:
            return None
        return Money(abs(credit.minor) - abs(debit.minor), currency)
    return _bank_amount(dict(normalized), currency, locale)


def _preview_document(
    kind: SourceKind,
    text: str,
    *,
    filename: str,
    source_sha256: str,
) -> tuple[list[SourceRecord], list[ImportIssue], dict[str, str]]:
    try:
        raw = parse_document_text(filename, text, kind.value)
        raw["attachment_sha256"] = source_sha256
        raw["evidence_status"] = EvidenceStatus.AVAILABLE.value
        raw["source_type"] = kind.value
        import_key = f"sha256:{source_sha256}:-1:{kind.value}"
        raw["import_key"] = import_key
        decoded = decode_source(normalize_source(raw))
        return [replace(decoded, id=_source_id(import_key), import_key=import_key)], [], {}
    except (TypeError, ValueError) as exc:
        return [], [ImportIssue(None, "document", "invalid_document", str(exc))], {}


def _charset(media_type: str) -> str:
    declared = "utf-8"
    for part in media_type.split(";")[1:]:
        key, separator, value = part.strip().partition("=")
        if separator and key.lower() == "charset":
            declared = value.strip().strip('"').lower()
    if declared not in SUPPORTED_CHARSETS:
        raise ValueError(f"Unsupported text charset: {declared}.")
    return SUPPORTED_CHARSETS[declared]


def _detected_mapping(fieldnames: list[str]) -> dict[str, str]:
    normalized = [_normalize_header(value) for value in fieldnames]
    aliases = {
        "date": ("date", "datum", "bookingdate", "bokforingsdatum", "transaktionsdatum"),
        "description": ("description", "beskrivning", "text", "meddelande", "referens"),
        "amount": ("amount", "belopp", "summa", "transaction_amount"),
        "debit": ("debit", "debet", "uttag", "ut"),
        "credit": ("credit", "kredit", "insattning", "in"),
        "currency": ("currency", "valuta"),
        "counterparty": ("counterparty", "motpart", "namn", "payee"),
    }
    mapping: dict[str, str] = {}
    for field, candidates in aliases.items():
        hits = [name for name in normalized if name in candidates]
        if len(hits) == 1:
            mapping[field] = hits[0]
    if "amount" not in mapping and "debit" in mapping and "credit" in mapping:
        mapping["amount"] = "debit+credit"
    return mapping


def _source_id(import_key: str) -> str:
    return "source-" + hashlib.sha256(import_key.encode()).hexdigest()[:24]


def _staging_path(repository: Repository, batch_id: str) -> Path:
    return repository.path.parent / "staging" / batch_id


def _write_private_file(path: Path, content: bytes, *, allow_identical: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists():
        if allow_identical and path.is_file() and path.read_bytes() == content:
            os.chmod(path, 0o600)
            return False
        raise FileExistsError(f"Private import file already exists: {path.name}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    return True


def _record_payload(record: SourceRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind.value,
        "occurred_on": record.occurred_on.isoformat(),
        "amount_minor": record.amount.minor,
        "currency": record.amount.currency,
        "description": record.description,
        "counterparty": record.counterparty,
        "source_filename": record.source_filename,
        "source_row": record.source_row,
        "import_key": record.import_key,
        "attachment_sha256": record.attachment_sha256,
        "evidence_status": record.evidence_status.value,
        "extracted": dict(record.extracted),
    }


def _preview_from_payload(payload: Mapping[str, Any]) -> ImportPreview:
    candidates = tuple(
        decode_source(
            {
                "id": value["id"],
                "source_type": value["kind"],
                "date": value["occurred_on"],
                "amount_minor": value["amount_minor"],
                "currency": value["currency"],
                "description": value["description"],
                "counterparty": value["counterparty"],
                "source_filename": value["source_filename"],
                "source_row": value.get("source_row"),
                "import_key": value["import_key"],
                "attachment_sha256": value.get("attachment_sha256"),
                "evidence_status": value["evidence_status"],
                "extracted": value.get("extracted", {}),
            }
        )
        for value in payload.get("candidates", [])
    )
    issues = tuple(ImportIssue(**value) for value in payload.get("issues", []))
    return ImportPreview(
        batch_id=str(payload["batch_id"]),
        kind=SourceKind(str(payload["kind"])),
        source_filename=str(payload["source_filename"]),
        media_type=str(payload["media_type"]),
        source_sha256=str(payload["source_sha256"]),
        decoded_bytes=int(payload["decoded_bytes"]),
        candidates=candidates,
        issues=issues,
        committed=bool(payload.get("committed")),
        column_mapping=dict(payload.get("column_mapping", {})),
    )
