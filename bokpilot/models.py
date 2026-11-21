"""Core data structures for Bokpilot.

Bokpilot intentionally keeps the model small and serializable so the API,
exports, and legacy migration remain inspectable without a database server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from . import __version__
from .domain import PostingDraft, ReviewDecision


__all__ = ["JournalLine", "Suggestion", "ReviewDecision", "PostingDraft", "empty_workspace"]


@dataclass
class JournalLine:
    account: str
    account_name: str
    debit_minor: int = 0
    credit_minor: int = 0

    def __post_init__(self) -> None:
        if type(self.debit_minor) is not int or type(self.credit_minor) is not int:
            raise TypeError("Journal minor-unit amounts must be integers.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "account_name": self.account_name,
            "debit_minor": self.debit_minor,
            "credit_minor": self.credit_minor,
        }


@dataclass
class Suggestion:
    category: str
    bas_account: str
    bas_account_name: str
    vat_rate: Decimal
    vat_amount_minor: int
    confidence: float
    explanation: str
    journal_lines: list[JournalLine]
    risk_flags: list[str] = field(default_factory=list)
    review_required: bool = True

    def __post_init__(self) -> None:
        if type(self.vat_amount_minor) is not int:
            raise TypeError("Suggestion VAT minor units must be an integer.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "bas_account": self.bas_account,
            "bas_account_name": self.bas_account_name,
            "vat_rate": float(self.vat_rate),
            "vat_amount_minor": self.vat_amount_minor,
            "confidence": round(self.confidence, 2),
            "explanation": self.explanation,
            "journal_lines": [line.to_dict() for line in self.journal_lines],
            "risk_flags": list(self.risk_flags),
            "review_required": self.review_required,
        }


def empty_workspace() -> dict[str, Any]:
    return {
        "metadata": {
            "project": "Bokpilot",
            "version": __version__,
            "schema_version": 2,
            "locale": "sv-SE",
            "disclaimer": (
                "Bokpilot generates accounting suggestions only. A qualified "
                "human must review every item before export or posting."
            ),
        },
        "items": [],
        "events": [],
    }
