"""Sample dataset loader for the demo flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .parsers import parse_bank_csv, parse_document_text


ROOT = Path(__file__).resolve().parents[1]


def load_sample_transactions() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    bank_csv = ROOT / "samples" / "bank" / "bank-transactions.csv"
    items.extend(parse_bank_csv(bank_csv.read_text(encoding="utf-8")))
    for sample in sorted((ROOT / "samples" / "receipts").glob("*.txt")):
        items.append(parse_document_text(sample.name, sample.read_text(encoding="utf-8"), "receipt"))
    for sample in sorted((ROOT / "samples" / "invoices").glob("*.txt")):
        items.append(parse_document_text(sample.name, sample.read_text(encoding="utf-8"), "invoice"))
    return items
