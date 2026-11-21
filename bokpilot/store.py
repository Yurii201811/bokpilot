"""SQLite-backed v0.1 workspace compatibility wrapper."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .models import empty_workspace
from .repository import Repository, RepositoryTransaction
from .rules import apply_account_override, classify_transaction
from .serialization import decode_source, normalize_source


def default_data_path() -> Path:
    configured = os.environ.get("BOKPILOT_DATA_PATH")
    if configured:
        return Path(configured)
    return Path.cwd() / "data" / "bokpilot.sqlite3"


class WorkspaceStore:
    def __init__(
        self,
        path: Path | None = None,
        *,
        repository: Repository | None = None,
    ):
        self.path = Path(path or default_data_path())
        if repository is None:
            _reject_legacy_json_file(self.path)
            repository = Repository(self.path)
        self.repository = repository
        self.path = repository.path

    def load(self) -> dict[str, Any]:
        workspace = empty_workspace()
        workspace["items"] = list(self.repository.compatibility_items())
        workspace["events"] = list(self.repository.workspace_events())
        workspace["revision"] = self.repository.workspace_revision()
        profile = self.repository.company_profile()
        workspace["company_profile"] = (
            None
            if profile is None
            else {
                "name": profile.name,
                "accounting_method": profile.accounting_method.value,
                "fiscal_year_start": profile.fiscal_year_start.isoformat(),
                "fiscal_year_end": profile.fiscal_year_end.isoformat(),
                "currency": profile.currency,
                "voucher_series": profile.voucher_series,
                "organization_number": profile.organization_number,
            }
        )
        return workspace

    def save(
        self,
        workspace: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        requested_revision = (
            expected_revision if expected_revision is not None else workspace.get("revision")
        )
        if type(requested_revision) is not int:
            raise ValueError("Workspace save requires an integer revision.")
        items = workspace.get("items", [])
        events = workspace.get("events", [])
        if not isinstance(items, list) or not isinstance(events, list):
            raise ValueError("Workspace items and events must be lists.")
        with self.repository.transaction() as transaction:
            if transaction.base_revision != requested_revision:
                raise ValueError(
                    f"Workspace revision conflict: expected {requested_revision}, "
                    f"current {transaction.base_revision}."
                )
            transaction.reset_workspace()
            for item in items:
                self._persist_compatibility_item(transaction, item)
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("Workspace events must be objects.")
                transaction.add_workspace_event(event)
        return self.load()

    def reset(self, *, expected_revision: int | None = None) -> dict[str, Any]:
        with self.repository.transaction() as transaction:
            if expected_revision is not None:
                transaction.require_revision(expected_revision)
            transaction.reset_workspace()
            transaction.add_workspace_event(_event("Workspace reset."))
        return self.load()

    def add_transactions(
        self,
        raw_items: list[dict[str, Any]],
        source: str,
        *,
        expected_revision: int | None = None,
        require_empty: bool = False,
    ) -> dict[str, Any]:
        with self.repository.transaction() as transaction:
            if expected_revision is not None:
                transaction.require_revision(expected_revision)
            if require_empty and transaction.source_count() != 0:
                raise ValueError("Workspace is not empty; sample loading was refused.")
            existing_items = list(transaction.compatibility_items())
            next_number = transaction.next_compatibility_item_number()
            for offset, raw in enumerate(raw_items):
                normalized = normalize_source(raw)
                item_id = f"BP-{next_number + offset:04d}"
                duplicate_flags = _duplicate_flags({"items": existing_items}, normalized)
                suggestion = classify_transaction(normalized).to_dict()
                suggestion["risk_flags"] = suggestion["risk_flags"] + duplicate_flags
                decoded = decode_source(normalized)
                record = replace(
                    decoded,
                    id=item_id,
                    import_key=f"compat:{item_id}",
                    high_risk=bool(suggestion.get("risk_flags")),
                )
                result = transaction.import_sources([record])
                if result.inserted != 1:
                    raise ValueError(f"Could not insert compatibility item {item_id}.")
                stored_raw = dict(normalized)
                stored_raw["import_key"] = record.import_key
                stored_raw["evidence_status"] = record.evidence_status.value
                transaction.set_source_compatibility(
                    item_id,
                    source_label=str(source),
                    raw=stored_raw,
                )
                transaction.save_suggestion_snapshot(item_id, suggestion)
                existing_items.append(
                    {
                        "id": item_id,
                        "source": str(source),
                        "raw": stored_raw,
                        "suggestion": suggestion,
                    }
                )
            transaction.add_workspace_event(
                _event(f"Imported {len(raw_items)} item(s) from {source}.")
            )
        return self.load()

    def review_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        status = payload.get("status")
        if status not in {"approved", "rejected", "needs_review"}:
            raise ValueError("Review status must be approved, rejected, or needs_review.")
        with self.repository.transaction() as transaction:
            target = next(
                (item for item in transaction.compatibility_items() if item.get("id") == item_id),
                None,
            )
            if target is None:
                raise ValueError(f"Unknown item id: {item_id}")
            if _review_changes_suggestion(target, payload):
                apply_account_override(
                    target,
                    str(payload["bas_account"]),
                    payload.get("vat_rate"),
                )
                transaction.save_suggestion_snapshot(item_id, target["suggestion"])
            human_reviewed = status in {"approved", "rejected"}
            transaction.set_compatibility_review(
                item_id,
                status=status,
                reviewer_note=str(payload.get("reviewer_note") or "").strip(),
                reviewed_at=_now() if human_reviewed else None,
            )
            transaction.add_workspace_event(_event(f"{item_id} marked {status}."))
        return self.load()

    def _persist_compatibility_item(
        self,
        transaction: RepositoryTransaction,
        item_value: Any,
    ) -> None:
        if not isinstance(item_value, dict):
            raise ValueError("Workspace items must be objects.")
        item_id = str(item_value.get("id") or "").strip()
        raw = item_value.get("raw")
        suggestion = item_value.get("suggestion")
        if not item_id or not isinstance(raw, dict) or not isinstance(suggestion, dict):
            raise ValueError("Workspace item id, raw, and suggestion are required.")
        normalized = normalize_source(raw)
        decoded = decode_source(normalized)
        import_key = str(normalized.get("import_key") or f"compat:{item_id}")
        record = replace(
            decoded,
            id=item_id,
            import_key=import_key,
            high_risk=bool(suggestion.get("risk_flags")),
        )
        inserted = transaction.import_sources([record])
        if inserted.inserted != 1:
            raise ValueError(f"Duplicate workspace item: {item_id}")
        stored_raw = dict(normalized)
        stored_raw["import_key"] = import_key
        transaction.set_source_compatibility(
            item_id,
            source_label=str(item_value.get("source") or ""),
            raw=stored_raw,
            status=str(item_value.get("status") or "needs_review"),
            reviewer_note=str(item_value.get("reviewer_note") or ""),
            reviewed_at=(
                str(item_value["reviewed_at"]) if item_value.get("reviewed_at") else None
            ),
            created_at=str(item_value["created_at"]) if item_value.get("created_at") else None,
        )
        transaction.save_suggestion_snapshot(item_id, suggestion)


def _reject_legacy_json_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    with path.open("rb") as workspace_file:
        prefix = workspace_file.read(16)
    if prefix != b"SQLite format 3\x00":
        raise ValueError(
            "Legacy JSON workspaces require explicit migration: "
            "python3 -m bokpilot migrate --from-json SOURCE --to-sqlite DEST"
        )


def _duplicate_flags(workspace: Mapping[str, Any], raw: dict[str, Any]) -> list[str]:
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


def _minor_amount(raw: Mapping[str, Any]) -> int:
    amount_minor = raw.get("amount_minor")
    if type(amount_minor) is not int:
        raise TypeError("amount_minor must be an integer.")
    return amount_minor


def _normalized_description(raw: Mapping[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(raw.get("description") or "")).strip().casefold()


def _review_changes_suggestion(item: dict[str, Any], payload: dict[str, Any]) -> bool:
    suggestion = item["suggestion"]
    requested_account = str(payload.get("bas_account") or "").strip()
    requested_rate = payload.get("vat_rate")
    account_changed = bool(requested_account) and requested_account != str(
        suggestion.get("bas_account")
    )
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
