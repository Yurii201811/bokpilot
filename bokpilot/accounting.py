"""Posting drafts built only from explicit, reviewable accounting decisions."""

from __future__ import annotations

from decimal import Decimal

from .accounts import AccountCatalog, AccountEntry
from .domain import (
    AccountingMethod,
    CompanyProfile,
    JournalLine,
    PostingDraft,
    ReviewDecision,
    SourceKind,
    SourceRecord,
    TransactionNature,
    VatTreatment,
)


_HIGH_RISK_NATURES = {
    TransactionNature.TRANSFER,
    TransactionNature.OWNER_MOVEMENT,
    TransactionNature.REFUND,
    TransactionNature.LOAN,
}
_RESERVED_CONTROL_ACCOUNTS = {"1510", "1930", "2440", "2611", "2641"}
_VAT_RATES = {
    VatTreatment.RATE_6: Decimal("6"),
    VatTreatment.RATE_12: Decimal("12"),
    VatTreatment.RATE_25: Decimal("25"),
}


def build_posting(
    record: SourceRecord,
    decision: ReviewDecision,
    profile: CompanyProfile,
    catalog: AccountCatalog,
) -> PostingDraft:
    """Build a non-exportable posting draft and all blocking issue codes."""
    issues: list[str] = []
    gross_minor = abs(record.amount.minor)
    account = catalog.get(decision.account)

    if record.amount.currency != "SEK" or profile.currency.upper() != "SEK":
        issues.append("unsupported_currency")
    if record.amount.currency != profile.currency.upper():
        _append_once(issues, "unsupported_currency")
    if decision.nature is TransactionNature.UNKNOWN:
        issues.append("unknown_nature")
    if decision.vat is VatTreatment.UNKNOWN:
        issues.append("unknown_vat")
    if (
        decision.nature not in {TransactionNature.EXPENSE, TransactionNature.REVENUE}
        and decision.vat not in {VatTreatment.UNKNOWN, VatTreatment.EXEMPT, VatTreatment.RATE_0}
    ):
        issues.append("vat_treatment_mismatch")
    if account is None:
        issues.append("invalid_account")
    if decision.account in _RESERVED_CONTROL_ACCOUNTS:
        issues.append("reserved_control_account")

    high_risk = record.high_risk or decision.nature in _HIGH_RISK_NATURES
    if high_risk and not decision.risk_acknowledged:
        issues.append("missing_risk_acknowledgement")
    if high_risk and not decision.reviewer_note.strip():
        issues.append("missing_high_risk_note")

    vat_minor = _reviewed_vat_minor(record, decision, gross_minor, issues)
    if vat_minor > gross_minor:
        _append_once(issues, "vat_exceeds_gross")

    if record.kind is SourceKind.CUSTOMER_INVOICE and decision.nature is not TransactionNature.REVENUE:
        issues.append("nature_source_mismatch")
    if record.kind is SourceKind.SUPPLIER_INVOICE and decision.nature is not TransactionNature.EXPENSE:
        issues.append("nature_source_mismatch")
    if record.kind in {SourceKind.RECEIPT, SourceKind.MANUAL}:
        issues.append("source_kind_requires_payment")
    accrual_bank_payment = (
        record.kind is SourceKind.BANK_TRANSACTION
        and profile.accounting_method is AccountingMethod.ACCRUAL
        and decision.nature in {TransactionNature.EXPENSE, TransactionNature.REVENUE}
    )
    if accrual_bank_payment and not record.matched_source_id:
        issues.append("accrual_bank_payment_requires_match")
    if accrual_bank_payment and record.matched_source_id:
        if (
            (decision.nature is TransactionNature.REVENUE and record.amount.minor <= 0)
            or (decision.nature is TransactionNature.EXPENSE and record.amount.minor >= 0)
        ):
            issues.append("matched_payment_direction_mismatch")
        if decision.vat not in {VatTreatment.EXEMPT, VatTreatment.RATE_0} or vat_minor != 0:
            issues.append("matched_payment_vat_must_be_zero")
    if (
        record.kind in {SourceKind.CUSTOMER_INVOICE, SourceKind.SUPPLIER_INVOICE}
        and profile.accounting_method is AccountingMethod.CASH
    ):
        issues.append("cash_method_invoice_requires_payment")

    required_codes = _required_control_accounts(record, decision, profile, vat_minor)
    control_accounts: dict[str, AccountEntry] = {}
    for code in required_codes:
        enabled = catalog.get(code)
        if enabled is None:
            _append_once(issues, "invalid_account")
        else:
            control_accounts[code] = enabled

    lines: tuple[JournalLine, ...] = ()
    if not issues and account is not None:
        lines = _posting_lines(
            record,
            decision,
            profile,
            account,
            control_accounts,
            gross_minor,
            vat_minor,
        )

    draft = PostingDraft(
        source_id=record.id,
        lines=lines,
        rule_id=_extracted_rule_id(record),
        rule_version=_extracted_rule_version(record),
        issues=tuple(issues),
    )
    complete_issues = posting_issues(draft)
    if complete_issues == draft.issues:
        return draft
    return PostingDraft(draft.source_id, draft.lines, draft.rule_id, draft.rule_version, complete_issues)


def posting_issues(draft: PostingDraft) -> tuple[str, ...]:
    issues = list(draft.issues)
    debit = sum(line.debit_minor for line in draft.lines)
    credit = sum(line.credit_minor for line in draft.lines)
    if debit != credit:
        _append_once(issues, "unbalanced_lines")
    return tuple(issues)


def _reviewed_vat_minor(
    record: SourceRecord,
    decision: ReviewDecision,
    gross_minor: int,
    issues: list[str],
) -> int:
    if decision.vat_minor is not None:
        vat_minor = decision.vat_minor
    elif decision.vat in {VatTreatment.EXEMPT, VatTreatment.RATE_0}:
        vat_minor = 0
    elif (
        record.source_vat == decision.vat
        and record.source_vat_minor is not None
    ):
        vat_minor = record.source_vat_minor
    elif decision.vat in _VAT_RATES:
        divisor = Decimal("1") + (_VAT_RATES[decision.vat] / Decimal("100"))
        net_minor = int((Decimal(gross_minor) / divisor).quantize(Decimal("1")))
        vat_minor = gross_minor - net_minor
    else:
        vat_minor = 0

    if decision.vat in {VatTreatment.EXEMPT, VatTreatment.RATE_0} and vat_minor != 0:
        issues.append("vat_treatment_mismatch")
    return vat_minor


def _required_control_accounts(
    record: SourceRecord,
    decision: ReviewDecision,
    profile: CompanyProfile,
    vat_minor: int,
) -> tuple[str, ...]:
    codes: list[str] = []
    if record.kind is SourceKind.BANK_TRANSACTION:
        codes.append("1930")
        if profile.accounting_method is AccountingMethod.ACCRUAL and record.matched_source_id:
            if decision.nature is TransactionNature.REVENUE:
                codes.append("1510")
            elif decision.nature is TransactionNature.EXPENSE:
                codes.append("2440")
    elif record.kind is SourceKind.CUSTOMER_INVOICE:
        codes.append("1510")
    elif record.kind is SourceKind.SUPPLIER_INVOICE:
        codes.append("2440")
    if vat_minor > 0:
        codes.append("2611" if decision.nature is TransactionNature.REVENUE else "2641")
    return tuple(codes)


def _posting_lines(
    record: SourceRecord,
    decision: ReviewDecision,
    profile: CompanyProfile,
    account: AccountEntry,
    controls: dict[str, AccountEntry],
    gross_minor: int,
    vat_minor: int,
) -> tuple[JournalLine, ...]:
    net_minor = gross_minor - vat_minor
    if (
        record.kind is SourceKind.BANK_TRANSACTION
        and profile.accounting_method is AccountingMethod.ACCRUAL
        and record.matched_source_id
    ):
        bank = controls["1930"]
        if decision.nature is TransactionNature.REVENUE:
            return (_debit(bank, gross_minor), _credit(controls["1510"], gross_minor))
        if decision.nature is TransactionNature.EXPENSE:
            return (_debit(controls["2440"], gross_minor), _credit(bank, gross_minor))
    if record.kind is SourceKind.CUSTOMER_INVOICE:
        lines = [
            _debit(controls["1510"], gross_minor),
            _credit(account, net_minor),
        ]
        if vat_minor:
            lines.append(_credit(controls["2611"], vat_minor))
        return tuple(lines)
    if record.kind is SourceKind.SUPPLIER_INVOICE:
        lines = [_debit(account, net_minor)]
        if vat_minor:
            lines.append(_debit(controls["2641"], vat_minor))
        lines.append(_credit(controls["2440"], gross_minor))
        return tuple(lines)

    bank = controls["1930"]
    if decision.nature is TransactionNature.EXPENSE:
        lines = [_debit(account, net_minor)]
        if vat_minor:
            lines.append(_debit(controls["2641"], vat_minor))
        lines.append(_credit(bank, gross_minor))
        return tuple(lines)
    if decision.nature is TransactionNature.REVENUE:
        lines = [_debit(bank, gross_minor), _credit(account, net_minor)]
        if vat_minor:
            lines.append(_credit(controls["2611"], vat_minor))
        return tuple(lines)

    if record.amount.minor >= 0:
        return (_debit(bank, gross_minor), _credit(account, gross_minor))
    return (_debit(account, gross_minor), _credit(bank, gross_minor))


def _debit(account: AccountEntry, minor: int) -> JournalLine:
    return JournalLine(account.code, account.name, debit_minor=minor)


def _credit(account: AccountEntry, minor: int) -> JournalLine:
    return JournalLine(account.code, account.name, credit_minor=minor)


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _extracted_rule_id(record: SourceRecord) -> str | None:
    value = record.extracted.get("rule_id")
    return str(value) if value else None


def _extracted_rule_version(record: SourceRecord) -> int | None:
    value = record.extracted.get("rule_version")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
