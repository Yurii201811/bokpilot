"""Schema-v2 codecs with legacy workspace read compatibility."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from .domain import EvidenceStatus, JournalLine, Money, SourceKind, SourceRecord


def decode_source(payload: Mapping[str, Any]) -> SourceRecord:
    """Decode a persisted source record, accepting legacy major-unit amounts."""
    currency = str(payload.get("currency") or "SEK")
    if "amount_minor" in payload:
        amount = Money(payload["amount_minor"], currency)
    elif "amount" in payload:
        amount = Money.from_major(Decimal(str(payload["amount"])), currency)
    else:
        raise ValueError("Source amount_minor is required.")

    source_type = str(payload.get("kind") or payload.get("source_type") or "manual")
    kind = {
        "bank_csv": SourceKind.BANK_TRANSACTION,
        "bank_transaction": SourceKind.BANK_TRANSACTION,
        "receipt": SourceKind.RECEIPT,
        "invoice": SourceKind.SUPPLIER_INVOICE,
        "supplier_invoice": SourceKind.SUPPLIER_INVOICE,
        "customer_invoice": SourceKind.CUSTOMER_INVOICE,
        "manual": SourceKind.MANUAL,
    }.get(source_type, SourceKind.MANUAL)
    source_filename = str(payload.get("source_filename") or "")
    source_row = payload.get("source_row")
    return SourceRecord(
        id=str(payload.get("id") or ""),
        kind=kind,
        occurred_on=date.fromisoformat(str(payload.get("date") or payload.get("occurred_on"))),
        amount=amount,
        description=str(payload.get("description") or ""),
        counterparty=str(payload.get("counterparty") or ""),
        source_filename=source_filename,
        source_row=source_row,
        import_key=str(payload.get("import_key") or f"{source_filename}:{source_row or ''}"),
        attachment_sha256=payload.get("attachment_sha256"),
        evidence_status=EvidenceStatus(str(payload.get("evidence_status") or "legacy_unavailable")),
        extracted=dict(payload.get("extracted") or {}),
    )


def encode_source(record: SourceRecord, *, template: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Encode a source record with schema-v2 minor-unit money fields."""
    encoded = dict(template or {})
    encoded.pop("amount", None)
    encoded.update(
        {
            "date": record.occurred_on.isoformat(),
            "description": record.description,
            "counterparty": record.counterparty,
            "amount_minor": record.amount.minor,
            "currency": record.amount.currency,
            "source_type": encoded.get("source_type") or record.kind.value,
            "source_filename": record.source_filename,
            "source_row": record.source_row,
        }
    )
    if record.id:
        encoded["id"] = record.id
    if record.import_key:
        encoded["import_key"] = record.import_key
    if record.attachment_sha256 is not None:
        encoded["attachment_sha256"] = record.attachment_sha256
    encoded["evidence_status"] = record.evidence_status.value
    if record.extracted:
        encoded["extracted"] = dict(record.extracted)
    return encoded


def decode_source_vat(payload: Mapping[str, Any]) -> Money | None:
    """Decode optional source VAT from either schema version."""
    return _decode_optional_money(payload, "vat_amount_minor", "vat_amount")


def encode_source_vat(amount: Money | None, *, template: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Encode optional source VAT using only its schema-v2 field."""
    encoded = dict(template or {})
    encoded.pop("vat_amount", None)
    encoded.pop("vat_amount_minor", None)
    if amount is not None:
        encoded["vat_amount_minor"] = amount.minor
    return encoded


def decode_suggestion_vat(payload: Mapping[str, Any], currency: str = "SEK") -> Money | None:
    """Decode optional suggestion VAT from either schema version."""
    return _decode_optional_money(payload, "vat_amount_minor", "vat_amount", currency=currency)


def encode_suggestion_vat(
    amount: Money | None, *, template: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Encode optional suggestion VAT using only its schema-v2 field."""
    encoded = dict(template or {})
    encoded.pop("vat_amount", None)
    encoded.pop("vat_amount_minor", None)
    if amount is not None:
        encoded["vat_amount_minor"] = amount.minor
    return encoded


def decode_journal_line(payload: Mapping[str, Any], currency: str = "SEK") -> JournalLine:
    """Decode a journal line, accepting legacy major-unit debit and credit."""
    debit = _decode_optional_money(payload, "debit_minor", "debit", currency=currency) or Money(0, currency)
    credit = _decode_optional_money(payload, "credit_minor", "credit", currency=currency) or Money(0, currency)
    return JournalLine(
        account=str(payload.get("account") or ""),
        account_name=str(payload.get("account_name") or ""),
        debit_minor=debit.minor,
        credit_minor=credit.minor,
    )


def encode_journal_line(
    line: JournalLine, *, template: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Encode a journal line using only schema-v2 minor-unit fields."""
    encoded = dict(template or {})
    for legacy_key in ("debit", "credit"):
        encoded.pop(legacy_key, None)
    encoded.update(
        {
            "account": line.account,
            "account_name": line.account_name,
            "debit_minor": line.debit_minor,
            "credit_minor": line.credit_minor,
        }
    )
    return encoded


def normalize_workspace(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a v1 or v2 workspace to the schema-v2 persisted shape."""
    workspace = deepcopy(dict(payload))
    metadata = dict(workspace.get("metadata") or {})
    metadata["schema_version"] = 2
    workspace["metadata"] = metadata

    normalized_items: list[dict[str, Any]] = []
    for item_payload in workspace.get("items", []):
        item = dict(item_payload)
        source_payload = dict(item.get("raw") or {})
        source = decode_source(source_payload)
        normalized_source = encode_source(source, template=source_payload)
        normalized_source = encode_source_vat(
            decode_source_vat(source_payload), template=normalized_source
        )

        suggestion_payload = dict(item.get("suggestion") or {})
        normalized_suggestion = encode_suggestion_vat(
            decode_suggestion_vat(suggestion_payload, source.amount.currency),
            template=suggestion_payload,
        )
        normalized_suggestion["journal_lines"] = [
            encode_journal_line(
                decode_journal_line(line, source.amount.currency),
                template=line,
            )
            for line in suggestion_payload.get("journal_lines", [])
        ]
        item["raw"] = normalized_source
        item["suggestion"] = normalized_suggestion
        normalized_items.append(item)
    workspace["items"] = normalized_items
    workspace.setdefault("events", [])
    return workspace


def _decode_optional_money(
    payload: Mapping[str, Any], minor_key: str, legacy_key: str, *, currency: str | None = None
) -> Money | None:
    normalized_currency = currency or str(payload.get("currency") or "SEK")
    if minor_key in payload:
        return Money(payload[minor_key], normalized_currency)
    if legacy_key in payload:
        return Money.from_major(Decimal(str(payload[legacy_key])), normalized_currency)
    return None
