"""Core data structures for Bokpilot.

Bokpilot intentionally keeps the model small and serializable so users can
inspect the local JSON workspace without a database server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


Money = Decimal


def money(value: Any) -> Decimal:
    """Return a currency-safe Decimal rounded to öre precision."""
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


def money_to_json(value: Decimal) -> float:
    return float(money(value))


@dataclass
class JournalLine:
    account: str
    account_name: str
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "account_name": self.account_name,
            "debit": money_to_json(self.debit),
            "credit": money_to_json(self.credit),
        }


@dataclass
class Suggestion:
    category: str
    bas_account: str
    bas_account_name: str
    vat_rate: Decimal
    vat_amount: Decimal
    confidence: float
    explanation: str
    journal_lines: list[JournalLine]
    risk_flags: list[str] = field(default_factory=list)
    review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "bas_account": self.bas_account,
            "bas_account_name": self.bas_account_name,
            "vat_rate": float(self.vat_rate),
            "vat_amount": money_to_json(self.vat_amount),
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
            "version": "0.1.0",
            "locale": "sv-SE",
            "disclaimer": (
                "Bokpilot generates accounting suggestions only. A qualified "
                "human must review every item before export or posting."
            ),
        },
        "items": [],
        "events": [],
    }
