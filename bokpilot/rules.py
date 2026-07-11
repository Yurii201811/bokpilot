"""Deterministic Swedish BAS/VAT suggestion rules.

The rules are deliberately conservative. They explain why an account was
suggested, attach risk flags to fuzzy cases, and always require human review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .models import JournalLine, Suggestion


BAS_ACCOUNTS: dict[str, str] = {
    "1510": "Kundfordringar",
    "1930": "Företagskonto",
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


@dataclass(frozen=True)
class Rule:
    keywords: tuple[str, ...]
    category: str
    account: str
    vat_rate: Decimal
    confidence: float
    explanation: str
    risk_flags: tuple[str, ...] = field(default_factory=tuple)


EXPENSE_RULES: tuple[Rule, ...] = (
    Rule(
        ("fortnox", "bokio", "visma", "frappe", "erpnext", "software", "programvara", "saas", "openai", "github"),
        "Software and cloud services",
        "5420",
        Decimal("25"),
        0.88,
        "The description looks like a software or cloud service purchase, commonly mapped to BAS 5420 with Swedish input VAT when the invoice supports it.",
    ),
    Rule(
        ("telia", "tele2", "telenor", "bredband", "internet", "mobil", "telefon", "datakommunikation"),
        "Telecom and connectivity",
        "6230",
        Decimal("25"),
        0.86,
        "The text points to telecom or internet costs, which are often booked as datakommunikation on BAS 6230 with input VAT.",
    ),
    Rule(
        ("kontorsmaterial", "office", "papper", "penna", "block", "pressbyran", "clas ohlson"),
        "Office supplies",
        "6110",
        Decimal("25"),
        0.84,
        "The wording looks like ordinary office material. BAS 6110 is a common account for smaller office supplies.",
    ),
    Rule(
        ("ikea", "stol", "skrivbord", "hylla", "möbel", "inventarie", "chair", "desk"),
        "Small equipment",
        "5410",
        Decimal("25"),
        0.76,
        "This looks like equipment or furniture. BAS 5410 can fit low-value consumable equipment, but larger assets need separate review.",
        ("Check whether this should be treated as equipment, inventory, or a fixed asset.",),
    ),
    Rule(
        ("bankavgift", "bank fee", "banktjänst", "serviceavgift", "kortavgift"),
        "Bank fees",
        "6570",
        Decimal("0"),
        0.9,
        "Bank fees are commonly booked to BAS 6570 and normally do not include deductible VAT.",
    ),
    Rule(
        ("ränta", "interest", "loan interest", "räntekostnad"),
        "Interest expense",
        "8410",
        Decimal("0"),
        0.87,
        "The transaction appears to be interest. Interest costs are usually outside VAT and can be booked as BAS 8410.",
    ),
    Rule(
        ("sj", "sl", "vy", "taxi", "uber", "bolt", "resa", "train", "travel", "biljett"),
        "Travel",
        "5800",
        Decimal("6"),
        0.72,
        "The text suggests business travel. Passenger transport often has 6% VAT in Sweden, but the receipt decides the final treatment.",
        ("Confirm business purpose and VAT from the actual receipt.",),
    ),
    Rule(
        ("restaurant", "restaurang", "cafe", "café", "lunch", "middag", "fika", "mat"),
        "Meals and representation",
        "6071",
        Decimal("12"),
        0.58,
        "Meals and representation have special deduction rules. Bokpilot can prepare the packet, but this should be reviewed carefully.",
        ("Representation and meal deductions have limits; check policy and current rules.",),
    ),
    Rule(
        ("okq8", "circle k", "shell", "bensin", "diesel", "drivmedel", "fuel"),
        "Vehicle fuel",
        "5611",
        Decimal("25"),
        0.62,
        "The transaction looks like fuel. Vehicle and mileage rules can affect deductibility, so this is a review item.",
        ("Vehicle costs can depend on company car/private car treatment and mileage records.",),
    ),
)


def normalize_text(text: str) -> str:
    lowered = text.lower()
    return re.sub(r"\s+", " ", lowered).strip()


def classify_transaction(raw: dict[str, Any]) -> Suggestion:
    description = normalize_text(
        " ".join(
            str(raw.get(key, ""))
            for key in ("description", "counterparty", "source_filename", "notes")
        )
    )
    amount_minor = _minor_field(raw, "amount_minor")
    explicit_vat_minor = raw.get("vat_amount_minor")
    if explicit_vat_minor is not None and type(explicit_vat_minor) is not int:
        raise TypeError("vat_amount_minor must be an integer.")
    explicit_rate = raw.get("vat_rate")

    if amount_minor >= 0:
        return _income_suggestion(amount_minor, description, explicit_vat_minor, explicit_rate)

    for rule in EXPENSE_RULES:
        if any(keyword in description for keyword in rule.keywords):
            return _expense_suggestion(amount_minor, rule, explicit_vat_minor, explicit_rate)

    fallback = Rule(
        (),
        "Unclassified expense",
        "6991",
        Decimal("25"),
        0.42,
        "No strong rule matched. BAS 6991 is used as a temporary catch-all suggestion so a human can choose the right account.",
        ("Low confidence: choose the final BAS account manually.",),
    )
    return _expense_suggestion(amount_minor, fallback, explicit_vat_minor, explicit_rate)


def _income_suggestion(
    amount_minor: int, description: str, explicit_vat_minor: int | None, explicit_rate: Any
) -> Suggestion:
    rate = _decide_rate(explicit_rate, Decimal("25"))
    if "momsfri" in description or "vat exempt" in description:
        rate = Decimal("0")
        account = "3054"
        category = "VAT-exempt sales"
        explanation = "The text indicates VAT-exempt sales. Bokpilot suggests a VAT-free sales account, but human review is required."
        confidence = 0.68
    else:
        account = "3011"
        category = "Swedish sales"
        explanation = "A positive bank transaction or customer invoice usually means income. This suggests Swedish sales with output VAT."
        confidence = 0.82

    vat_amount_minor = _decide_vat_amount_minor(amount_minor, rate, explicit_vat_minor)
    net_minor = amount_minor - vat_amount_minor
    lines = [
        JournalLine("1930", BAS_ACCOUNTS["1930"], debit_minor=amount_minor),
        JournalLine(account, BAS_ACCOUNTS[account], credit_minor=net_minor),
    ]
    if vat_amount_minor > 0:
        lines.append(JournalLine("2611", BAS_ACCOUNTS["2611"], credit_minor=vat_amount_minor))

    return Suggestion(
        category=category,
        bas_account=account,
        bas_account_name=BAS_ACCOUNTS[account],
        vat_rate=rate,
        vat_amount_minor=vat_amount_minor,
        confidence=confidence,
        explanation=explanation,
        journal_lines=lines,
        risk_flags=("Confirm that income is revenue and not a loan, owner deposit, or refund.",),
    )


def _expense_suggestion(
    amount_minor: int, rule: Rule, explicit_vat_minor: int | None, explicit_rate: Any
) -> Suggestion:
    gross_minor = abs(amount_minor)
    rate = _decide_rate(explicit_rate, rule.vat_rate)
    vat_amount_minor = _decide_vat_amount_minor(gross_minor, rate, explicit_vat_minor)
    net_minor = gross_minor - vat_amount_minor
    lines = [
        JournalLine(rule.account, BAS_ACCOUNTS[rule.account], debit_minor=net_minor),
    ]
    if vat_amount_minor > 0:
        lines.append(JournalLine("2641", BAS_ACCOUNTS["2641"], debit_minor=vat_amount_minor))
    lines.append(JournalLine("1930", BAS_ACCOUNTS["1930"], credit_minor=gross_minor))

    return Suggestion(
        category=rule.category,
        bas_account=rule.account,
        bas_account_name=BAS_ACCOUNTS[rule.account],
        vat_rate=rate,
        vat_amount_minor=vat_amount_minor,
        confidence=rule.confidence,
        explanation=rule.explanation,
        journal_lines=lines,
        risk_flags=list(rule.risk_flags),
    )


def _decide_rate(explicit_rate: Any, default_rate: Decimal) -> Decimal:
    if explicit_rate in (None, "", "null"):
        return default_rate
    return Decimal(str(explicit_rate)).quantize(Decimal("0.01"))


def _decide_vat_amount_minor(gross_minor: int, rate: Decimal, explicit_vat_minor: int | None) -> int:
    if explicit_vat_minor is not None:
        return explicit_vat_minor
    if rate == 0:
        return 0
    divisor = Decimal("1.00") + (rate / Decimal("100"))
    net_minor = int((Decimal(gross_minor) / divisor).quantize(Decimal("1")))
    return gross_minor - net_minor


def _minor_field(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise TypeError(f"{key} must be an integer.")
    return value


def apply_account_override(item: dict[str, Any], account: str, vat_rate: Any | None = None) -> dict[str, Any]:
    """Recalculate an item with a reviewer-selected BAS account."""
    raw = item["raw"]
    amount_minor = _minor_field(raw, "amount_minor")
    rate = Decimal(str(vat_rate if vat_rate is not None else item["suggestion"]["vat_rate"]))
    account_name = BAS_ACCOUNTS.get(account, "Reviewer-selected account")
    gross_minor = abs(amount_minor)
    explicit_vat_minor = raw.get("vat_amount_minor")
    if explicit_vat_minor is not None and type(explicit_vat_minor) is not int:
        raise TypeError("vat_amount_minor must be an integer.")
    vat_amount_minor = _decide_vat_amount_minor(gross_minor, rate, explicit_vat_minor)
    net_minor = gross_minor - vat_amount_minor

    if amount_minor >= 0:
        lines = [
            JournalLine("1930", BAS_ACCOUNTS["1930"], debit_minor=gross_minor),
            JournalLine(account, account_name, credit_minor=net_minor),
        ]
        if vat_amount_minor > 0:
            lines.append(JournalLine("2611", BAS_ACCOUNTS["2611"], credit_minor=vat_amount_minor))
    else:
        lines = [JournalLine(account, account_name, debit_minor=net_minor)]
        if vat_amount_minor > 0:
            lines.append(JournalLine("2641", BAS_ACCOUNTS["2641"], debit_minor=vat_amount_minor))
        lines.append(JournalLine("1930", BAS_ACCOUNTS["1930"], credit_minor=gross_minor))

    suggestion = Suggestion(
        category="Reviewer override",
        bas_account=account,
        bas_account_name=account_name,
        vat_rate=rate,
        vat_amount_minor=vat_amount_minor,
        confidence=min(float(item["suggestion"].get("confidence", 0.5)), 0.75),
        explanation="A human reviewer changed the account or VAT treatment. The export records this as a reviewer override.",
        journal_lines=lines,
        risk_flags=["Reviewer override: keep the source document attached to the bookkeeping packet."],
    )
    item["suggestion"] = suggestion.to_dict()
    return item
