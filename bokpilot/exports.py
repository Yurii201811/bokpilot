"""Exports for approved Bokpilot review items."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Any


def approved_items(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in workspace.get("items", [])
        if item.get("status") == "approved" and item.get("human_reviewed") is True
    ]


def export_json(workspace: dict[str, Any]) -> str:
    packet = {
        "metadata": {
            "program": "Bokpilot",
            "schema_version": 2,
            "generated_on": date.today().isoformat(),
            "export_policy": "Only human-approved items are included.",
            "disclaimer": "Draft bookkeeping suggestions only; verify before posting or filing.",
        },
        "items": approved_items(workspace),
    }
    return json.dumps(packet, ensure_ascii=False, indent=2) + "\n"


def export_csv(workspace: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "item_id",
            "date",
            "description",
            "amount_minor",
            "currency",
            "source_type",
            "source_filename",
            "source_row",
            "status",
            "bas_account",
            "bas_account_name",
            "vat_rate",
            "vat_amount_minor",
            "confidence",
            "reviewer_note",
            "explanation",
        ],
    )
    writer.writeheader()
    for item in approved_items(workspace):
        raw = item["raw"]
        suggestion = item["suggestion"]
        writer.writerow(
            {
                "item_id": item["id"],
                "date": raw.get("date"),
                "description": raw.get("description"),
                "amount_minor": raw.get("amount_minor"),
                "currency": raw.get("currency", "SEK"),
                "source_type": raw.get("source_type", ""),
                "source_filename": raw.get("source_filename", ""),
                "source_row": raw.get("source_row", ""),
                "status": item.get("status"),
                "bas_account": suggestion.get("bas_account"),
                "bas_account_name": suggestion.get("bas_account_name"),
                "vat_rate": suggestion.get("vat_rate"),
                "vat_amount_minor": suggestion.get("vat_amount_minor"),
                "confidence": suggestion.get("confidence"),
                "reviewer_note": item.get("reviewer_note", ""),
                "explanation": suggestion.get("explanation"),
            }
        )
    return output.getvalue()


def export_sie_style(workspace: dict[str, Any]) -> str:
    lines = [
        "#FLAGGA 0",
        '#PROGRAM "Bokpilot" 0.1.0',
        "#FORMAT PC8",
        f"#GEN {date.today().strftime('%Y%m%d')}",
        '#FNAMN "Bokpilot Demo Company"',
        "#RAR 0 20260101 20261231",
    ]
    accounts = _used_accounts(workspace)
    for account, name in sorted(accounts.items()):
        lines.append(f'#KONTO {account} "{name}"')

    for index, item in enumerate(approved_items(workspace), start=1):
        raw = item["raw"]
        description = _escape(str(raw.get("description") or item["id"]))
        ver_date = str(raw.get("date", "")).replace("-", "")
        lines.append(f'#VER "BP" "{index}" {ver_date} "{description}"')
        lines.append("{")
        for journal_line in item["suggestion"]["journal_lines"]:
            account = journal_line["account"]
            debit_minor = _minor_value(journal_line, "debit_minor")
            credit_minor = _minor_value(journal_line, "credit_minor")
            amount = Decimal(debit_minor - credit_minor) / Decimal(100)
            lines.append(f"#TRANS {account} {{}} {amount:.2f}")
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def export_summary(workspace: dict[str, Any]) -> dict[str, Any]:
    items = workspace.get("items", [])
    approved = approved_items(workspace)
    return {
        "total_items": len(items),
        "needs_review": sum(1 for item in items if item.get("status") == "needs_review"),
        "approved": len(approved),
        "rejected": sum(1 for item in items if item.get("status") == "rejected"),
        "export_ready": len(approved),
    }


def _used_accounts(workspace: dict[str, Any]) -> dict[str, str]:
    accounts: dict[str, str] = {}
    for item in approved_items(workspace):
        for line in item["suggestion"].get("journal_lines", []):
            accounts[str(line["account"])] = str(line["account_name"])
    return accounts


def _escape(value: str) -> str:
    return value.replace('"', "'")


def _minor_value(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise TypeError(f"{key} must be an integer.")
    return value
