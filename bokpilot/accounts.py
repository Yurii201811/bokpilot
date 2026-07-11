"""Evidence-gated account catalog for safe posting drafts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable


_ACCOUNT_CODE = re.compile(r"^[0-9]{4}$")
_EVIDENCE_STATUSES = {"pending_review", "approved"}


@dataclass(frozen=True)
class AccountEntry:
    code: str
    name: str
    source_url: str
    evidence_status: str = "pending_review"
    reviewer: str | None = None
    review_date: date | None = None

    def __post_init__(self) -> None:
        if _ACCOUNT_CODE.fullmatch(self.code) is None:
            raise ValueError(f"Invalid BAS account code: {self.code!r}.")
        if not self.name.strip():
            raise ValueError("Account name is required.")
        if self.evidence_status not in _EVIDENCE_STATUSES:
            raise ValueError(f"Unsupported account evidence status: {self.evidence_status!r}.")
        if self.evidence_status == "approved" and not (
            self.source_url.strip() and str(self.reviewer or "").strip() and self.review_date
        ):
            raise ValueError("Approved account evidence requires source, reviewer, and review date.")


class AccountCatalog:
    """Catalog whose public lookup exposes approved accounts only."""

    def __init__(self, entries: Iterable[AccountEntry]):
        materialized = tuple(entries)
        by_code = {entry.code: entry for entry in materialized}
        if len(by_code) != len(materialized):
            raise ValueError("Account codes must be unique.")
        self._entries = by_code

    def __contains__(self, code: object) -> bool:
        return str(code) in self._entries

    def entry(self, code: str) -> AccountEntry | None:
        """Return catalog evidence for inspection, even when not enabled."""
        return self._entries.get(str(code))

    def get(self, code: str) -> AccountEntry | None:
        """Return an account only when its evidence row is approved."""
        normalized = str(code)
        if _ACCOUNT_CODE.fullmatch(normalized) is None:
            return None
        entry = self._entries.get(normalized)
        if entry is None or entry.evidence_status != "approved":
            return None
        return entry

    @classmethod
    def from_json_file(cls, path: str | Path) -> "AccountCatalog":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        accounts = payload.get("accounts")
        if not isinstance(accounts, list):
            raise ValueError("Account catalog must contain an accounts list.")
        return cls(_entry_from_payload(item) for item in accounts)

    @classmethod
    def production_default(cls) -> "AccountCatalog":
        return cls(_production_entries())


def _entry_from_payload(payload: Any) -> AccountEntry:
    if not isinstance(payload, dict):
        raise ValueError("Each account catalog entry must be an object.")
    review_date = payload.get("review_date")
    return AccountEntry(
        code=str(payload.get("code") or ""),
        name=str(payload.get("name") or ""),
        source_url=str(payload.get("source_url") or ""),
        evidence_status=str(payload.get("evidence_status") or "pending_review"),
        reviewer=str(payload["reviewer"]) if payload.get("reviewer") else None,
        review_date=date.fromisoformat(str(review_date)) if review_date else None,
    )


def _production_entries() -> tuple[AccountEntry, ...]:
    source = "https://www.bas.se/kontoplaner/"
    accounts = {
        "1510": "Kundfordringar",
        "1930": "Företagskonto",
        "2440": "Leverantörsskulder",
        "2611": "Utgående moms på försäljning inom Sverige, 25%",
        "2641": "Ingående moms",
        "3011": "Försäljning inom Sverige, 25% moms",
        "3054": "Försäljning tjänster momsfri",
        "5410": "Förbrukningsinventarier",
        "5420": "Programvaror",
        "5611": "Drivmedel för personbilar",
        "5800": "Resekostnader",
        "6071": "Representation, avdragsgill",
        "6110": "Kontorsmateriel",
        "6230": "Datakommunikation",
        "6570": "Bankkostnader",
        "6991": "Övriga externa kostnader, avdragsgilla",
        "8410": "Räntekostnader för långfristiga skulder",
    }
    return tuple(
        AccountEntry(code, name, source, evidence_status="pending_review")
        for code, name in accounts.items()
    )
