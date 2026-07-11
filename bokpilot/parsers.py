"""Input parsers for bank CSV files and simple receipt/invoice text."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .domain import Money


_EXACT_MONEY_LOCALES = ("sv-SE", "en-US", "plain")


def parse_money_exact(value: object, locale: str = "auto", currency: str = "SEK") -> Money:
    """Parse a documented money layout into exact integer minor units."""
    if type(value) is int or isinstance(value, Decimal):
        return Money.from_major(value, currency)
    if not isinstance(value, str):
        raise TypeError("Money input must be text, an integer, or a Decimal.")

    text = value.strip()
    if not text:
        raise ValueError("Money value is required.")

    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1].strip()
    normalized_currency = Money(0, currency).currency
    text = _strip_exact_currency(text, normalized_currency)
    if negative_parentheses and text.startswith(("+", "-")):
        raise ValueError(f"Could not parse money value: {value!r}")

    normalized_locale = _normalize_exact_locale(locale)
    locales = _EXACT_MONEY_LOCALES if normalized_locale == "auto" else (normalized_locale,)
    candidates = {
        candidate
        for candidate in (_exact_money_candidate(text, candidate_locale) for candidate_locale in locales)
        if candidate is not None
    }
    if not candidates:
        raise ValueError(f"Could not parse money value: {value!r}")
    major_values = {candidate[0] for candidate in candidates}
    if len(major_values) > 1:
        raise ValueError("Ambiguous money format; choose the source locale.")
    if any(fraction_digits > 2 for _, fraction_digits in candidates):
        raise ValueError("Money supports at most two decimal places.")

    major = major_values.pop()
    if negative_parentheses:
        major = -abs(major)
    return Money.from_major(major, normalized_currency)


def parse_date_exact(value: object) -> date:
    """Parse a supported date layout and validate the calendar date."""
    if type(value) is date:
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("Date value is required.")
    for pattern, normalized in (
        (r"^(\d{4})-(\d{2})-(\d{2})$", r"\1-\2-\3"),
        (r"^(\d{4})/(\d{2})/(\d{2})$", r"\1-\2-\3"),
        (r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3"),
        (r"^(\d{2})/(\d{2})/(\d{4})$", r"\3-\2-\1"),
        (r"^(\d{2})\.(\d{2})\.(\d{4})$", r"\3-\2-\1"),
        (r"^(\d{2})-(\d{2})-(\d{4})$", r"\3-\2-\1"),
    ):
        if re.fullmatch(pattern, text):
            return date.fromisoformat(re.sub(pattern, normalized, text))
    raise ValueError(f"Unsupported date format: {value!r}")


def _normalize_exact_locale(locale: str) -> str:
    normalized = str(locale or "").strip().lower()
    aliases = {"auto": "auto", "sv-se": "sv-SE", "en-us": "en-US", "plain": "plain"}
    if normalized not in aliases:
        raise ValueError("Money locale must be auto, sv-SE, en-US, or plain.")
    return aliases[normalized]


def _strip_exact_currency(text: str, currency: str) -> str:
    marker_pattern = r"(?P<marker>[A-Za-z]{3}|kr)"
    prefix = re.fullmatch(rf"{marker_pattern}\s*(?P<number>.+)", text, flags=re.IGNORECASE)
    suffix = re.fullmatch(rf"(?P<number>.+?)\s*{marker_pattern}", text, flags=re.IGNORECASE)
    match = prefix or suffix
    if match is None:
        return text
    marker = match.group("marker").upper()
    marker_currency = "SEK" if marker == "KR" else marker
    if marker_currency != currency:
        raise ValueError(f"Money currency {marker_currency} does not match {currency}.")
    return match.group("number").strip()


def _exact_money_candidate(text: str, locale: str) -> tuple[Decimal, int] | None:
    patterns = {
        "sv-SE": (
            r"(?P<sign>[+-]?)(?P<integer>(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d{1,3}(?:\.\d{3})+|\d+))"
            r"(?:,(?P<fraction>\d+))?",
            (" ", "\u00a0", "."),
        ),
        "en-US": (
            r"(?P<sign>[+-]?)(?P<integer>(?:\d{1,3}(?:,\d{3})+|\d+))"
            r"(?:\.(?P<fraction>\d+))?",
            (",",),
        ),
        "plain": (
            r"(?P<sign>[+-]?)(?P<integer>\d+)(?:\.(?P<fraction>\d+))?",
            (),
        ),
    }
    pattern, grouping_characters = patterns[locale]
    match = re.fullmatch(pattern, text)
    if match is None:
        return None
    integer = match.group("integer")
    for character in grouping_characters:
        integer = integer.replace(character, "")
    fraction = match.group("fraction")
    normalized = f"{match.group('sign')}{integer}"
    if fraction is not None:
        normalized = f"{normalized}.{fraction}"
    return Decimal(normalized), len(fraction or "")


def parse_money(value: object, locale: str = "auto", currency: str = "SEK") -> Money:
    """Public strict money boundary returning exact minor units."""
    return parse_money_exact(value, locale, currency)


def parse_date(value: object) -> date:
    """Public strict date boundary returning a validated calendar date."""
    return parse_date_exact(value)


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
        currency = str(_first(normalized, ("currency", "valuta")) or "SEK").strip().upper()
        amount = _bank_amount(normalized, currency)
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
        try:
            parsed_date = parse_date(date_value).isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid date in CSV row {line_number}: {date_value!r}.") from exc
        extracted = {"date": str(date_value)}
        for key in ("amount", "amount_sek", "belopp", "belopp_sek", "debit", "debet", "credit", "kredit"):
            if normalized.get(key) not in (None, ""):
                extracted[key] = str(normalized[key])
        rows.append(
            {
                "date": parsed_date,
                "description": description or "Bank transaction",
                "counterparty": _first(normalized, ("counterparty", "motpart", "namn", "payee")) or "",
                "amount_minor": amount.minor,
                "currency": amount.currency,
                "source_type": "bank_csv",
                "source_filename": filename,
                "source_row": line_number,
                "extracted": extracted,
            }
        )
    return rows


def parse_document_text(filename: str, content: str, kind: str = "document") -> dict[str, Any]:
    fields = _key_value_fields(content)
    lower = content.lower()
    date_value = _first(fields, ("date", "datum", "invoice_date", "fakturadatum")) or _first_date(content)
    try:
        parsed_date = parse_date(date_value).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid document date: {date_value!r}.") from exc
    total_value = _first(fields, ("total", "total_sek", "belopp", "amount", "summa", "att_betala"))
    if not total_value:
        total_value = _amount_after_label(content, ("total", "summa", "att betala", "belopp"))
    vat_value = _first(fields, ("vat", "moms", "vat_sek", "moms_sek"))
    supplier = _first(fields, ("supplier", "vendor", "leverantor", "leverantör", "seller", "säljare"))
    customer = _first(fields, ("customer", "kund", "buyer", "köpare"))
    description = _first(fields, ("description", "beskrivning", "specification", "specifikation"))

    amount = parse_money(total_value, "auto", "SEK")
    is_income = any(marker in lower for marker in ("customer invoice", "kundfaktura", "invoice to", "faktura till"))
    signed_amount_minor = amount.minor if is_income else -abs(amount.minor)
    counterparty = customer if is_income else supplier

    raw: dict[str, Any] = {
        "date": parsed_date,
        "description": description or _fallback_description(filename, content),
        "counterparty": counterparty or supplier or customer or Path(filename).stem,
        "amount_minor": signed_amount_minor,
        "currency": amount.currency,
        "source_type": kind,
        "source_filename": filename,
        "document_text": content[:5000],
        "extracted": {"date": str(date_value), "amount": str(total_value)},
    }
    if vat_value:
        raw["vat_amount_minor"] = parse_money(vat_value, "auto", amount.currency).minor
        raw["extracted"]["vat_amount"] = str(vat_value)
    return raw


def manual_transaction(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("date") in (None, ""):
        raise ValueError("Manual transaction date is required.")
    try:
        parsed_date = parse_date(payload["date"]).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid manual transaction date: {payload.get('date')!r}.") from exc
    currency = str(payload.get("currency") or "SEK").strip().upper()
    amount = parse_money(payload.get("amount"), "plain", currency)
    return {
        "date": parsed_date,
        "description": str(payload.get("description") or "Manual transaction").strip(),
        "counterparty": str(payload.get("counterparty") or "").strip(),
        "amount_minor": amount.minor,
        "currency": amount.currency,
        "source_type": "manual",
        "source_filename": "manual-entry",
        "extracted": {"date": str(payload["date"]), "amount": str(payload.get("amount"))},
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


def _bank_amount(mapping: dict[str, Any], currency: str) -> Money | None:
    amount_value = _first(
        mapping,
        ("amount", "amount_sek", "belopp", "belopp_sek", "value", "summa", "transaction_amount"),
    )
    if amount_value not in (None, ""):
        return parse_money(amount_value, "auto", currency)

    debit_value = _first(
        mapping,
        ("debit", "debet", "withdrawal", "withdrawals", "uttag", "ut", "paid_out", "money_out", "utbetalt"),
    )
    credit_value = _first(
        mapping,
        ("credit", "kredit", "deposit", "deposits", "insattning", "insättning", "in", "paid_in", "money_in", "inbetalt"),
    )
    debit = parse_money(debit_value, "auto", currency) if debit_value not in (None, "") else Money(0, currency)
    credit = parse_money(credit_value, "auto", currency) if credit_value not in (None, "") else Money(0, currency)
    if debit.minor == 0 and credit.minor == 0:
        return None
    return Money(abs(credit.minor) - abs(debit.minor), currency)


def _parse_date(value: Any) -> str:
    return parse_date(value).isoformat()


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
    if match is None:
        raise ValueError("Document date is required.")
    return match.group(1)


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
