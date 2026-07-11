"""Input parsers for bank CSV files and simple receipt/invoice text."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def parse_money(value: Any) -> Decimal:
    text = str(value or "").strip()
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1].strip()
    text = text.replace("SEK", "").replace("kr", "").replace("\u00a0", " ")
    text = text.replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if negative_parentheses and text and not text.startswith("-"):
        text = f"-{text}"
    if text in ("", "-", ".", "-."):
        return Decimal("0.00")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Could not parse money value: {value!r}") from exc


def parse_bank_csv(content: str, filename: str = "bank-transactions.csv") -> list[dict[str, Any]]:
    sample = content[:2048]
    dialect = _sniff_csv_dialect(sample)
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("CSV file has no header row.")

    rows: list[dict[str, Any]] = []
    for line_number, row in enumerate(reader, start=2):
        if _is_blank_csv_row(row):
            continue
        normalized = {_normalize_header(key): value for key, value in row.items()}
        date_value = _first(
            normalized,
            (
                "date",
                "datum",
                "bookingdate",
                "booking_date",
                "posted_date",
                "transactiondate",
                "transaction_date",
                "transaktionsdag",
                "transaktionsdatum",
                "bokforingsdag",
                "bokforingsdatum",
            ),
        )
        amount = _bank_amount(normalized)
        description = _first(
            normalized,
            (
                "description",
                "beskrivning",
                "text",
                "message",
                "meddelande",
                "notering",
                "reference",
                "referens",
                "transaction_text",
                "transaktionstext",
                "mottagare",
                "payee",
            ),
        )
        if not date_value or amount is None:
            raise ValueError(f"Missing required date or amount in CSV row {line_number}.")
        rows.append(
            {
                "date": _parse_date(date_value),
                "description": description or "Bank transaction",
                "counterparty": _first(normalized, ("counterparty", "motpart", "namn", "payee")) or "",
                "amount": float(amount),
                "currency": _first(normalized, ("currency", "valuta")) or "SEK",
                "source_type": "bank_csv",
                "source_filename": filename,
                "source_row": line_number,
            }
        )
    return rows


def parse_document_text(filename: str, content: str, kind: str = "document") -> dict[str, Any]:
    fields = _key_value_fields(content)
    lower = content.lower()
    parsed_date = _parse_date(
        _first(fields, ("date", "datum", "invoice_date", "fakturadatum")) or _first_date(content)
    )
    total_value = _first(fields, ("total", "total_sek", "belopp", "amount", "summa", "att_betala"))
    if not total_value:
        total_value = _amount_after_label(content, ("total", "summa", "att betala", "belopp"))
    vat_value = _first(fields, ("vat", "moms", "vat_sek", "moms_sek"))
    supplier = _first(fields, ("supplier", "vendor", "leverantor", "leverantör", "seller", "säljare"))
    customer = _first(fields, ("customer", "kund", "buyer", "köpare"))
    description = _first(fields, ("description", "beskrivning", "specification", "specifikation"))

    amount = parse_money(total_value)
    is_income = any(marker in lower for marker in ("customer invoice", "kundfaktura", "invoice to", "faktura till"))
    signed_amount = amount if is_income else -abs(amount)
    counterparty = customer if is_income else supplier

    raw: dict[str, Any] = {
        "date": parsed_date,
        "description": description or _fallback_description(filename, content),
        "counterparty": counterparty or supplier or customer or Path(filename).stem,
        "amount": float(signed_amount),
        "currency": "SEK",
        "source_type": kind,
        "source_filename": filename,
        "document_text": content[:5000],
    }
    if vat_value:
        raw["vat_amount"] = float(parse_money(vat_value))
    return raw


def manual_transaction(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": _parse_date(payload.get("date") or date.today().isoformat()),
        "description": str(payload.get("description") or "Manual transaction").strip(),
        "counterparty": str(payload.get("counterparty") or "").strip(),
        "amount": float(parse_money(payload.get("amount", 0))),
        "currency": str(payload.get("currency") or "SEK").strip().upper(),
        "source_type": "manual",
        "source_filename": "manual-entry",
    }


def _normalize_header(header: str | None) -> str:
    text = (header or "").strip().lower().replace(" ", "_")
    text = text.translate(str.maketrans({"å": "a", "ä": "a", "ö": "o", "é": "e"}))
    return re.sub(r"[^a-z0-9_]", "", text)


def _sniff_csv_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        class FallbackDialect(csv.excel):
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","

        return FallbackDialect


def _is_blank_csv_row(row: dict[str | None, Any]) -> bool:
    return all(str(value or "").strip() == "" for value in row.values())


def _first(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        normalized = _normalize_header(key)
        if normalized in mapping and mapping[normalized] not in (None, ""):
            return mapping[normalized]
    return None


def _bank_amount(mapping: dict[str, Any]) -> Decimal | None:
    amount_value = _first(
        mapping,
        ("amount", "amount_sek", "belopp", "belopp_sek", "value", "summa", "transaction_amount"),
    )
    if amount_value not in (None, ""):
        return parse_money(amount_value)

    debit_value = _first(
        mapping,
        ("debit", "debet", "withdrawal", "withdrawals", "uttag", "ut", "paid_out", "money_out", "utbetalt"),
    )
    credit_value = _first(
        mapping,
        ("credit", "kredit", "deposit", "deposits", "insattning", "insättning", "in", "paid_in", "money_in", "inbetalt"),
    )
    debit = parse_money(debit_value) if debit_value not in (None, "") else Decimal("0.00")
    credit = parse_money(credit_value) if credit_value not in (None, "") else Decimal("0.00")
    if debit == 0 and credit == 0:
        return None
    return abs(credit) - abs(debit)


def _parse_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return date.today().isoformat()
    for pattern, repl in (
        (r"^(\d{4})-(\d{2})-(\d{2})$", r"\1-\2-\3"),
        (r"^(\d{4})/(\d{2})/(\d{2})$", r"\1-\2-\3"),
        (r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3"),
        (r"^(\d{2})/(\d{2})/(\d{4})$", r"\3-\2-\1"),
        (r"^(\d{2})\.(\d{2})\.(\d{4})$", r"\3-\2-\1"),
        (r"^(\d{2})-(\d{2})-(\d{4})$", r"\3-\2-\1"),
    ):
        match = re.match(pattern, text)
        if match:
            return re.sub(pattern, repl, text)
    raise ValueError(f"Unsupported date format: {value!r}")


def _key_value_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[_normalize_header(key)] = value.strip()
    return fields


def _first_date(content: str) -> str:
    match = re.search(r"\b(20\d{2}[-/.]\d{2}[-/.]\d{2}|\d{2}[/.]\d{2}[/.]20\d{2})\b", content)
    return match.group(1) if match else date.today().isoformat()


def _amount_after_label(content: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        pattern = rf"{label}\s*[: ]\s*([0-9][0-9\s.,-]*)"
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    raise ValueError("Could not find a total amount in the document text.")


def _fallback_description(filename: str, content: str) -> str:
    first_text_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    return first_text_line or Path(filename).stem
