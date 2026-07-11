"""Local JSON workspace store."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import empty_workspace
from .rules import apply_account_override, classify_transaction
from .serialization import normalize_source, normalize_workspace


def default_data_path() -> Path:
    configured = os.environ.get("BOKPILOT_DATA_PATH")
    if configured:
        return Path(configured)
    return Path.cwd() / "data" / "workspace.json"


class WorkspaceStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_data_path()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return normalize_workspace(empty_workspace())
        with self.path.open("r", encoding="utf-8") as handle:
            return normalize_workspace(json.load(handle))

    def save(self, workspace: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_workspace(workspace)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return normalized

    def reset(self) -> dict[str, Any]:
        workspace = empty_workspace()
        self.save(workspace)
        return workspace

    def add_transactions(self, raw_items: list[dict[str, Any]], source: str) -> dict[str, Any]:
        workspace = self.load()
        for raw in raw_items:
            normalized = normalize_source(raw)
            workspace["items"].append(_build_item(workspace, normalized, source))
        workspace["events"].append(_event(f"Imported {len(raw_items)} item(s) from {source}."))
        return self.save(workspace)

    def review_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        workspace = self.load()
        target = _find_item(workspace, item_id)
        status = payload.get("status")
        if status not in {"approved", "rejected", "needs_review"}:
            raise ValueError("Review status must be approved, rejected, or needs_review.")
        if _review_changes_suggestion(target, payload):
            apply_account_override(target, str(payload["bas_account"]), payload.get("vat_rate"))
        target["status"] = status
        target["human_reviewed"] = status in {"approved", "rejected"}
        target["reviewer_note"] = str(payload.get("reviewer_note") or "").strip()
        target["reviewed_at"] = _now() if target["human_reviewed"] else None
        workspace["events"].append(_event(f"{item_id} marked {status}."))
        return self.save(workspace)


def _build_item(workspace: dict[str, Any], raw: dict[str, Any], source: str) -> dict[str, Any]:
    suggestion = classify_transaction(raw)
    item_number = len(workspace.get("items", [])) + 1
    item_id = f"BP-{item_number:04d}"
    duplicate_flags = _duplicate_flags(workspace, raw)
    suggestion_dict = suggestion.to_dict()
    suggestion_dict["risk_flags"] = suggestion_dict["risk_flags"] + duplicate_flags
    return {
        "id": item_id,
        "source": source,
        "raw": raw,
        "suggestion": suggestion_dict,
        "status": "needs_review",
        "human_reviewed": False,
        "reviewer_note": "",
        "reviewed_at": None,
        "created_at": _now(),
    }


def _duplicate_flags(workspace: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    key = (raw.get("date"), _minor_amount(raw), _normalized_description(raw))
    for item in workspace.get("items", []):
        existing = item.get("raw", {})
        existing_key = (
            existing.get("date"),
            _minor_amount(existing),
            _normalized_description(existing),
        )
        if key == existing_key:
            return ["Possible duplicate: same date, amount, and description already exist."]
    return []


def _minor_amount(raw: dict[str, Any]) -> int:
    amount_minor = raw.get("amount_minor")
    if type(amount_minor) is not int:
        raise TypeError("amount_minor must be an integer.")
    return amount_minor


def _normalized_description(raw: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(raw.get("description") or "")).strip().casefold()


def _find_item(workspace: dict[str, Any], item_id: str) -> dict[str, Any]:
    for item in workspace.get("items", []):
        if item.get("id") == item_id:
            return item
    raise ValueError(f"Unknown item id: {item_id}")


def _review_changes_suggestion(item: dict[str, Any], payload: dict[str, Any]) -> bool:
    suggestion = item["suggestion"]
    requested_account = str(payload.get("bas_account") or "").strip()
    requested_rate = payload.get("vat_rate")
    account_changed = bool(requested_account) and requested_account != str(suggestion.get("bas_account"))
    if requested_rate in (None, ""):
        rate_changed = False
    else:
        rate_changed = Decimal(str(requested_rate)).quantize(Decimal("0.01")) != Decimal(
            str(suggestion.get("vat_rate"))
        ).quantize(Decimal("0.01"))
    return account_changed or rate_changed


def _event(message: str) -> dict[str, str]:
    return {"at": _now(), "message": message}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
