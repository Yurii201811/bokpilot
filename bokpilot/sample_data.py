"""Sample dataset loader for the demo flow."""

from __future__ import annotations

from typing import Any

from .parsers import parse_bank_csv, parse_document_text
from .resources import resource_file


DOCUMENT_SAMPLES = (
    ("receipts", "pressbyran-office-supplies.txt", "receipt"),
    ("receipts", "tele2-broadband.txt", "receipt"),
    ("invoices", "customer-invoice-web-design.txt", "invoice"),
    ("invoices", "supplier-invoice-openai.txt", "invoice"),
)


def load_sample_transactions() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    bank_csv = resource_file("samples", "bank", "bank-transactions.csv")
    items.extend(parse_bank_csv(bank_csv.read_text(encoding="utf-8")))
    for directory, filename, kind in DOCUMENT_SAMPLES:
        sample = resource_file("samples", directory, filename)
        items.append(parse_document_text(filename, sample.read_text(encoding="utf-8"), kind))
    return items
