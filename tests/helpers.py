from __future__ import annotations

from datetime import date

from bokpilot.accounts import AccountCatalog
from bokpilot.domain import (
    AccountingMethod,
    CompanyProfile,
    EvidenceStatus,
    Money,
    SourceKind,
    SourceRecord,
    VatTreatment,
)


def source_record(
    description: str,
    minor: int,
    *,
    kind: SourceKind = SourceKind.BANK_TRANSACTION,
    currency: str = "SEK",
    source_vat: VatTreatment | None = None,
    source_vat_minor: int | None = None,
    matched_source_id: str | None = None,
    high_risk: bool = False,
) -> SourceRecord:
    identifier = "test-" + "-".join(description.lower().split())
    return SourceRecord(
        id=identifier,
        kind=kind,
        occurred_on=date(2026, 7, 11),
        amount=Money(minor, currency),
        description=description,
        counterparty="Synthetic Counterparty",
        source_filename="synthetic-source.txt",
        source_row=1,
        import_key=f"test:{identifier}",
        attachment_sha256=None,
        evidence_status=EvidenceStatus.AVAILABLE,
        extracted={},
        source_vat=source_vat,
        source_vat_minor=source_vat_minor,
        matched_source_id=matched_source_id,
        high_risk=high_risk,
    )


def company_profile(
    accounting_method: AccountingMethod = AccountingMethod.CASH,
) -> CompanyProfile:
    return CompanyProfile(
        name="Synthetic Test Company",
        accounting_method=accounting_method,
        fiscal_year_start=date(2026, 1, 1),
        fiscal_year_end=date(2026, 12, 31),
        currency="SEK",
        voucher_series="BP",
    )


def approved_test_catalog() -> AccountCatalog:
    return AccountCatalog.from_json_file(
        __file__.replace("helpers.py", "fixtures/accounts/approved-test-catalog.json")
    )
