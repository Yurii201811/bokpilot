"""Strict SIE 4I byte generation for approved synthetic or reviewed postings."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping

from . import __version__
from .domain import CompanyProfile, JournalLine


_ACCOUNT = re.compile(r"^[0-9]{4}$")
_SERIES = re.compile(r"^[A-Za-z0-9]{1,8}$")


def sie_text(value: str) -> str:
    original = str(value)
    if any(ord(character) < 32 and character not in "\r\n\t" for character in original):
        raise ValueError("SIE text contains a control character.")
    cleaned = " ".join(original.replace("\r", " ").replace("\n", " ").split())
    return cleaned.replace('"', "'")


def sie4i_bytes(profile: CompanyProfile, packets: Iterable[Mapping[str, Any]]) -> bytes:
    if profile.currency.upper() != "SEK":
        raise ValueError("SIE 4I export supports SEK currency only.")
    if not profile.name.strip():
        raise ValueError("SIE company name is required.")
    if _SERIES.fullmatch(profile.voucher_series) is None:
        raise ValueError("SIE voucher series must be 1-8 letters or digits.")
    materialized = tuple(packets)
    accounts: dict[str, str] = {}
    normalized: list[tuple[Mapping[str, Any], tuple[JournalLine, ...]]] = []
    for packet in materialized:
        posting_lines = tuple(_line(value) for value in packet.get("posting_lines", []))
        if not posting_lines or sum(line.debit_minor for line in posting_lines) != sum(
            line.credit_minor for line in posting_lines
        ):
            raise ValueError("SIE voucher posting lines must be present and balanced.")
        for line in posting_lines:
            if _ACCOUNT.fullmatch(line.account) is None:
                raise ValueError("SIE account tokens must contain exactly four digits.")
            accounts[line.account] = sie_text(line.account_name)
        normalized.append((packet, posting_lines))
    lines = [
        "#FLAGGA 0",
        f'#PROGRAM "Bokpilot" {__version__}',
        "#FORMAT PC8",
        f"#GEN {date.today().strftime('%Y%m%d')}",
        "#SIETYP 4",
        f'#FNAMN "{sie_text(profile.name)}"',
        f"#RAR 0 {profile.fiscal_year_start.strftime('%Y%m%d')} {profile.fiscal_year_end.strftime('%Y%m%d')}",
    ]
    for account, name in sorted(accounts.items()):
        lines.append(f'#KONTO {account} "{name}"')
    for index, (packet, posting_lines) in enumerate(normalized, start=1):
        occurred = str(packet.get("date") or "")
        try:
            token = date.fromisoformat(occurred).strftime("%Y%m%d")
        except ValueError as exc:
            raise ValueError("SIE voucher date must be ISO YYYY-MM-DD.") from exc
        description = sie_text(str(packet.get("description") or packet.get("source_id") or "Voucher"))
        lines.extend([f'#VER "{profile.voucher_series}" "{index}" {token} "{description}"', "{"])
        for line in posting_lines:
            minor = line.debit_minor - line.credit_minor
            amount = Decimal(minor) / Decimal(100)
            lines.append(f"#TRANS {line.account} {{}} {amount:.2f}")
        lines.append("}")
    return ("\r\n".join(lines) + "\r\n").encode("cp437", errors="strict")


def _line(value: Any) -> JournalLine:
    if isinstance(value, JournalLine):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("SIE posting lines must be objects.")
    return JournalLine(
        account=str(value.get("account") or ""),
        account_name=str(value.get("account_name") or ""),
        debit_minor=int(value.get("debit_minor") or 0),
        credit_minor=int(value.get("credit_minor") or 0),
    )
