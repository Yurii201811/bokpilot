"""Exact schema-v2 domain types for accounting data."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


class VatTreatment(str, Enum):
    UNKNOWN = "unknown"
    EXEMPT = "exempt"
    RATE_0 = "0"
    RATE_6 = "6"
    RATE_12 = "12"
    RATE_25 = "25"


class SourceKind(str, Enum):
    BANK_TRANSACTION = "bank_transaction"
    RECEIPT = "receipt"
    SUPPLIER_INVOICE = "supplier_invoice"
    CUSTOMER_INVOICE = "customer_invoice"
    MANUAL = "manual"


class EvidenceStatus(str, Enum):
    AVAILABLE = "available"
    MANUAL_ATTESTED = "manual_attested"
    LEGACY_UNAVAILABLE = "legacy_unavailable"


class TransactionNature(str, Enum):
    UNKNOWN = "unknown"
    EXPENSE = "expense"
    REVENUE = "revenue"
    TRANSFER = "transfer"
    OWNER_MOVEMENT = "owner_movement"
    REFUND = "refund"
    LOAN = "loan"


class AccountingMethod(str, Enum):
    CASH = "cash"
    ACCRUAL = "accrual"


@dataclass(frozen=True)
class Money:
    minor: int
    currency: str = "SEK"

    def __post_init__(self) -> None:
        if type(self.minor) is not int:
            raise TypeError("Money.minor must be an integer.")
        normalized = self.currency.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Currency must be a three-letter ISO code.")
        object.__setattr__(self, "currency", normalized)

    @classmethod
    def from_major(cls, value: str | int | Decimal, currency: str = "SEK") -> "Money":
        scaled = Decimal(str(value)) * 100
        if scaled != scaled.to_integral_value():
            raise ValueError("Money supports at most two decimal places.")
        return cls(int(scaled), currency)

    def to_dict(self) -> dict[str, Any]:
        return {"minor": self.minor, "currency": self.currency}


@dataclass(frozen=True)
class SourceRecord:
    id: str
    kind: SourceKind
    occurred_on: date
    amount: Money
    description: str
    counterparty: str
    source_filename: str
    source_row: int | None
    import_key: str
    attachment_sha256: str | None
    evidence_status: EvidenceStatus
    extracted: Mapping[str, str] = field(default_factory=dict)
    source_vat: VatTreatment | None = None
    source_vat_minor: int | None = None
    matched_source_id: str | None = None
    high_risk: bool = False

    def __post_init__(self) -> None:
        if self.source_vat is not None and not isinstance(self.source_vat, VatTreatment):
            raise TypeError("Source VAT treatment must be a VatTreatment value.")
        if self.source_vat_minor is not None and type(self.source_vat_minor) is not int:
            raise TypeError("Source VAT minor units must be an integer.")
        if self.source_vat_minor is not None and self.source_vat_minor < 0:
            raise ValueError("Source VAT minor units cannot be negative.")
        if type(self.high_risk) is not bool:
            raise TypeError("SourceRecord.high_risk must be a boolean.")


@dataclass(frozen=True)
class CompanyProfile:
    name: str
    accounting_method: AccountingMethod
    fiscal_year_start: date
    fiscal_year_end: date
    currency: str
    voucher_series: str
    organization_number: str | None = None


@dataclass(frozen=True)
class JournalLine:
    account: str
    account_name: str
    debit_minor: int = 0
    credit_minor: int = 0

    def __post_init__(self) -> None:
        if self.debit_minor < 0 or self.credit_minor < 0:
            raise ValueError("Journal amounts cannot be negative.")
        if self.debit_minor and self.credit_minor:
            raise ValueError("A journal line cannot be both debit and credit.")


@dataclass(frozen=True)
class Suggestion:
    nature: TransactionNature
    category: str
    account: str | None
    account_name: str | None
    vat: VatTreatment
    vat_minor: int | None
    confidence: float
    explanation: str
    risk_flags: tuple[str, ...]
    rule_id: str | None
    rule_version: int | None


@dataclass(frozen=True)
class ReviewDecision:
    nature: TransactionNature
    account: str
    vat: VatTreatment
    vat_minor: int | None
    reviewer_note: str
    risk_acknowledged: bool

    def __post_init__(self) -> None:
        if self.vat_minor is not None and type(self.vat_minor) is not int:
            raise TypeError("Review VAT minor units must be an integer.")
        if self.vat_minor is not None and self.vat_minor < 0:
            raise ValueError("Review VAT minor units cannot be negative.")
        if type(self.risk_acknowledged) is not bool:
            raise TypeError("risk_acknowledged must be a boolean.")


@dataclass(frozen=True)
class PostingDraft:
    source_id: str
    lines: tuple[JournalLine, ...]
    rule_id: str | None
    rule_version: int | None
    issues: tuple[str, ...]
