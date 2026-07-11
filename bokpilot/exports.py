"""Exports for approved Bokpilot review items."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from .domain import CompanyProfile
from . import __version__
from .repository import Repository
from .sie import sie4i_bytes


@dataclass(frozen=True)
class ExportBatch:
    id: str
    format: str
    filename: str
    sha256: str
    byte_count: int
    review_ids: tuple[str, ...]
    workspace_revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "format": self.format,
            "filename": self.filename,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "review_ids": list(self.review_ids),
            "included_count": len(self.review_ids),
            "workspace_revision": self.workspace_revision,
        }


def create_json_batch(
    repository: Repository, review_ids: list[str], *, expected_revision: int | None = None
) -> ExportBatch:
    packets = repository.approved_review_payloads(review_ids)
    content = (
        json.dumps(
            {
                "schema_version": 2,
                "format": "bokpilot-review-packet",
                "generated_on": date.today().isoformat(),
                "items": [_share_safe_packet(value) for value in packets],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    return _persist_batch(repository, "json", review_ids, content, expected_revision)


def create_csv_batch(
    repository: Repository, review_ids: list[str], *, expected_revision: int | None = None
) -> ExportBatch:
    packets = repository.approved_review_payloads(review_ids)
    output = io.StringIO(newline="")
    fields = [
        "review_id",
        "source_id",
        "date",
        "description",
        "counterparty",
        "amount",
        "currency",
        "source_kind",
        "source_filename",
        "source_row",
        "account",
        "vat",
        "reviewer_note",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for packet in packets:
        decision = packet["decision"]
        writer.writerow(
            {
                "review_id": _csv_text(packet["review_id"]),
                "source_id": _csv_text(packet["source_id"]),
                "date": packet["date"],
                "description": _csv_text(packet["description"]),
                "counterparty": _csv_text(packet["counterparty"]),
                "amount": f"{Decimal(packet['amount_minor']) / Decimal(100):.2f}",
                "currency": packet["currency"],
                "source_kind": packet["kind"],
                "source_filename": _csv_text(_safe_filename(packet["source_filename"])),
                "source_row": packet["source_row"] if packet["source_row"] is not None else "",
                "account": decision.get("account", ""),
                "vat": decision.get("vat", ""),
                "reviewer_note": _csv_text(decision.get("reviewer_note", "")),
            }
        )
    return _persist_batch(
        repository, "csv", review_ids, output.getvalue().encode("utf-8"), expected_revision
    )


def create_sie4i_batch(
    repository: Repository,
    review_ids: list[str],
    profile: CompanyProfile,
    *,
    expected_revision: int | None = None,
) -> ExportBatch:
    packets = repository.approved_review_payloads(review_ids)
    return _persist_batch(
        repository, "sie4i", review_ids, sie4i_bytes(profile, packets), expected_revision
    )


def read_export_batch(repository: Repository, batch_id: str) -> bytes:
    record = repository.export_record(batch_id)
    if record is None:
        raise ValueError(f"Unknown export batch: {batch_id}")
    path = Path(str(record["artifact_path"]))
    if (
        path.resolve().parent != (repository.path.parent / "exports").resolve()
        or path.is_symlink()
        or not path.is_file()
    ):
        raise ValueError("Export artifact is unavailable.")
    content = path.read_bytes()
    if len(content) != int(record["byte_count"]):
        raise ValueError("Export artifact byte count failed verification.")
    if hashlib.sha256(content).hexdigest() != str(record["sha256"]):
        raise ValueError("Export artifact checksum failed verification.")
    return content


def _persist_batch(
    repository: Repository,
    format_name: str,
    review_ids: list[str],
    content: bytes,
    expected_revision: int | None,
) -> ExportBatch:
    checksum = hashlib.sha256(content).hexdigest()
    root = repository.path.parent / "exports"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    artifact = root / checksum
    if artifact.exists():
        if artifact.read_bytes() != content:
            raise ValueError("Content-addressed export artifact collision.")
    else:
        temporary = root / f".{checksum}.tmp-{uuid4().hex}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, artifact)
        os.chmod(artifact, 0o600)
    result = repository.create_export_batch(
        format=format_name,
        artifact_path=artifact,
        sha256=checksum,
        byte_count=len(content),
        source_ids=review_ids,
        expected_revision=expected_revision,
    )
    filename = f"bokpilot-export-{date.today().strftime('%Y%m%d')}.{'se' if format_name == 'sie4i' else format_name}"
    return ExportBatch(
        result.ids[0],
        format_name,
        filename,
        checksum,
        len(content),
        tuple(review_ids),
        result.revision,
    )


def _share_safe_packet(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": packet["review_id"],
        "source_id": packet["source_id"],
        "source_sha256": packet["source_sha256"],
        "source": {
            "date": packet["date"],
            "description": packet["description"],
            "counterparty": packet["counterparty"],
            "amount_minor": packet["amount_minor"],
            "currency": packet["currency"],
            "kind": packet["kind"],
            "source_filename": _safe_filename(packet["source_filename"]),
            "source_row": packet["source_row"],
        },
        "decision": packet["decision"],
        "posting_lines": packet["posting_lines"],
        "reviewed_at": packet["reviewed_at"],
    }


def _csv_text(value: Any) -> str:
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _safe_filename(value: Any) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _share_safe_legacy_item(item: dict[str, Any]) -> dict[str, Any]:
    raw = dict(item.get("raw") or {})
    for key in ("document_text", "raw_bytes", "path", "local_path", "attachment_path"):
        raw.pop(key, None)
    raw["source_filename"] = _safe_filename(raw.get("source_filename", ""))
    return {
        "id": item.get("id"),
        "raw": raw,
        "suggestion": dict(item.get("suggestion") or {}),
        "status": item.get("status"),
        "reviewer_note": item.get("reviewer_note", ""),
        "reviewed_at": item.get("reviewed_at"),
        "review_id": item.get("review_id"),
    }


def approved_items(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in workspace.get("items", [])
        if item.get("status") == "approved" and item.get("human_reviewed") is True
    ]


def export_json(workspace: dict[str, Any]) -> str:
    packet = {
        "metadata": {
            "program": "Bokpilot",
            "schema_version": 2,
            "generated_on": date.today().isoformat(),
            "export_policy": "Only human-approved items are included.",
            "disclaimer": "Draft bookkeeping suggestions only; verify before posting or filing.",
        },
        "items": [_share_safe_legacy_item(item) for item in approved_items(workspace)],
    }
    return json.dumps(packet, ensure_ascii=False, indent=2) + "\n"


def export_csv(workspace: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "item_id",
            "date",
            "description",
            "amount_minor",
            "currency",
            "source_type",
            "source_filename",
            "source_row",
            "status",
            "bas_account",
            "bas_account_name",
            "vat_rate",
            "vat_amount_minor",
            "confidence",
            "reviewer_note",
            "explanation",
        ],
    )
    writer.writeheader()
    for item in approved_items(workspace):
        raw = item["raw"]
        suggestion = item["suggestion"]
        writer.writerow(
            {
                "item_id": item["id"],
                "date": raw.get("date"),
                "description": _csv_text(raw.get("description")),
                "amount_minor": raw.get("amount_minor"),
                "currency": raw.get("currency", "SEK"),
                "source_type": raw.get("source_type", ""),
                "source_filename": _csv_text(_safe_filename(raw.get("source_filename", ""))),
                "source_row": raw.get("source_row", ""),
                "status": item.get("status"),
                "bas_account": suggestion.get("bas_account"),
                "bas_account_name": suggestion.get("bas_account_name"),
                "vat_rate": suggestion.get("vat_rate"),
                "vat_amount_minor": suggestion.get("vat_amount_minor"),
                "confidence": suggestion.get("confidence"),
                "reviewer_note": _csv_text(item.get("reviewer_note", "")),
                "explanation": _csv_text(suggestion.get("explanation")),
            }
        )
    return output.getvalue()


def export_sie_style(workspace: dict[str, Any]) -> str:
    lines = [
        "#FLAGGA 0",
        f'#PROGRAM "Bokpilot" {__version__}',
        "#FORMAT PC8",
        f"#GEN {date.today().strftime('%Y%m%d')}",
        '#FNAMN "Bokpilot Demo Company"',
        "#RAR 0 20260101 20261231",
    ]
    accounts = _used_accounts(workspace)
    for account, name in sorted(accounts.items()):
        lines.append(f'#KONTO {account} "{name}"')

    for index, item in enumerate(approved_items(workspace), start=1):
        raw = item["raw"]
        description = _escape(str(raw.get("description") or item["id"]))
        ver_date = str(raw.get("date", "")).replace("-", "")
        lines.append(f'#VER "BP" "{index}" {ver_date} "{description}"')
        lines.append("{")
        for journal_line in item["suggestion"]["journal_lines"]:
            account = journal_line["account"]
            debit_minor = _minor_value(journal_line, "debit_minor")
            credit_minor = _minor_value(journal_line, "credit_minor")
            amount = Decimal(debit_minor - credit_minor) / Decimal(100)
            lines.append(f"#TRANS {account} {{}} {amount:.2f}")
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def export_summary(workspace: dict[str, Any]) -> dict[str, Any]:
    items = workspace.get("items", [])
    approved = approved_items(workspace)
    return {
        "total_items": len(items),
        "needs_review": sum(1 for item in items if item.get("status") == "needs_review"),
        "approved": len(approved),
        "rejected": sum(1 for item in items if item.get("status") == "rejected"),
        "export_ready": len(approved),
    }


def _used_accounts(workspace: dict[str, Any]) -> dict[str, str]:
    accounts: dict[str, str] = {}
    for item in approved_items(workspace):
        for line in item["suggestion"].get("journal_lines", []):
            accounts[str(line["account"])] = str(line["account_name"])
    return accounts


def _escape(value: str) -> str:
    from .sie import sie_text

    return sie_text(value)


def _minor_value(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise TypeError(f"{key} must be an integer.")
    return value
