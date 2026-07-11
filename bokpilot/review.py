"""Auditable human review policy and immutable decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .accounting import build_posting, posting_issues
from .accounts import AccountCatalog
from .domain import CompanyProfile, PostingDraft, ReviewDecision, SourceRecord
from .repository import Repository


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message}


@dataclass(frozen=True)
class ReviewResult:
    decision_id: str
    source_id: str
    status: str
    item_version: int
    workspace_revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "source_id": self.source_id,
            "status": self.status,
            "item_version": self.item_version,
            "workspace_revision": self.workspace_revision,
        }


class ApprovalBlocked(ValueError):
    def __init__(self, issues: tuple[ReviewIssue, ...]):
        self.issues = issues
        super().__init__("Approval is blocked by unresolved review issues.")


_MESSAGES = {
    "unknown_nature": ("nature", "Choose the transaction nature."),
    "unknown_vat": ("vat", "Choose the VAT treatment."),
    "unsupported_currency": ("currency", "Only SEK posting drafts are supported."),
    "invalid_account": ("account", "Choose an enabled BAS account."),
    "vat_treatment_mismatch": ("vat", "VAT amount and treatment disagree."),
    "unbalanced_lines": ("posting", "Draft journal lines are not balanced."),
    "missing_risk_acknowledgement": ("risk", "Acknowledge the highlighted risk."),
    "unresolved_duplicate": ("duplicate", "Resolve the duplicate candidate first."),
}


def approval_issues(
    record: SourceRecord,
    decision: ReviewDecision,
    draft: PostingDraft,
    *,
    repository: Repository | None = None,
) -> tuple[ReviewIssue, ...]:
    codes = list(posting_issues(draft))
    if repository is not None and repository.unresolved_duplicate_ids(record.id):
        codes.append("unresolved_duplicate")
    values: list[ReviewIssue] = []
    for code in dict.fromkeys(codes):
        field, message = _MESSAGES.get(code, ("review", code.replace("_", " ").capitalize() + "."))
        values.append(ReviewIssue(code, field, message))
    return tuple(values)


def record_review(
    repository: Repository,
    source_id: str,
    *,
    action: str,
    decision: ReviewDecision,
    profile: CompanyProfile,
    catalog: AccountCatalog,
    expected_version: int,
) -> ReviewResult:
    if action not in {"approved", "rejected", "reopened"}:
        raise ValueError("Review action must be approved, rejected, or reopened.")
    record = repository.get_source(source_id)
    if record is None:
        raise ValueError(f"Unknown source id: {source_id}")
    draft = build_posting(record, decision, profile, catalog)
    issues = approval_issues(record, decision, draft, repository=repository)
    if action == "approved" and issues:
        raise ApprovalBlocked(issues)
    if action == "rejected" and not decision.reviewer_note.strip():
        raise ValueError("Rejection requires a reviewer note.")
    before = repository.latest_suggestion_snapshot(source_id)
    with repository.transaction() as transaction:
        decision_id, version = transaction.record_review_revision(
            source_id,
            decision=decision,
            draft=draft,
            action=action,
            expected_version=expected_version,
            before_suggestion=before,
        )
        if action == "approved":
            transaction.save_posting_draft(draft)
        revision = transaction.projected_revision
    status = {"approved": "approved", "rejected": "rejected", "reopened": "needs_review"}[action]
    return ReviewResult(decision_id, source_id, status, version, revision)


def record_duplicate_decision(
    repository: Repository,
    source_id: str,
    *,
    candidate_id: str,
    decision: str,
    note: str,
    expected_version: int,
) -> ReviewResult:
    if decision not in {"not_duplicate", "confirmed_duplicate"}:
        raise ValueError("Duplicate decision must be not_duplicate or confirmed_duplicate.")
    if not str(note).strip():
        raise ValueError("Duplicate decisions require a reviewer note.")
    with repository.transaction() as transaction:
        decision_id, version = transaction.record_duplicate_decision_revision(
            source_id,
            candidate_id=candidate_id,
            decision=decision,
            note=str(note).strip(),
            expected_version=expected_version,
        )
        revision = transaction.projected_revision
    status = "duplicate" if decision == "confirmed_duplicate" else "needs_review"
    return ReviewResult(decision_id, source_id, status, version, revision)
