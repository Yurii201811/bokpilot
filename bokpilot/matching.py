"""Explainable source matching that never reconciles records automatically."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .domain import SourceRecord
from .repository import Repository


@dataclass(frozen=True)
class MatchSuggestion:
    id: str
    source_id: str
    matched_source_id: str
    score: int
    reasons: tuple[str, ...]
    suggested_minor: int
    status: str
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "matched_source_id": self.matched_source_id,
            "score": self.score,
            "reasons": list(self.reasons),
            "suggested_minor": self.suggested_minor,
            "status": self.status,
            "version": self.version,
        }


@dataclass(frozen=True)
class MatchDecisionResult:
    match_id: str
    match_version: int
    source_version: int
    workspace_revision: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "match_id": self.match_id,
            "match_version": self.match_version,
            "source_version": self.source_version,
            "workspace_revision": self.workspace_revision,
        }


def suggest_matches(repository: Repository, source_id: str) -> tuple[MatchSuggestion, ...]:
    source = repository.get_source(source_id)
    if source is None:
        raise ValueError(f"Unknown source id: {source_id}")
    persisted = {value["id"]: value for value in repository.match_records_for_source(source_id)}
    suggestions: list[MatchSuggestion] = []
    for candidate in repository.all_sources():
        if candidate.id == source.id or candidate.amount.currency != source.amount.currency:
            continue
        scored = _score(source, candidate)
        if scored is None:
            continue
        score, reasons, suggested_minor = scored
        identifier = _match_id(source.id, candidate.id)
        record = persisted.get(identifier)
        suggestions.append(
            MatchSuggestion(
                id=identifier,
                source_id=source.id,
                matched_source_id=candidate.id,
                score=int(record["score"]) if record is not None else score,
                reasons=tuple(record["reasons"]) if record is not None else reasons,
                suggested_minor=(
                    int(record["amount_minor"])
                    if record is not None and int(record["amount_minor"]) > 0
                    else suggested_minor
                ),
                status=str(record["status"]) if record is not None else "suggested",
                version=int(record["version"]) if record is not None else 1,
            )
        )
    return tuple(sorted(suggestions, key=lambda value: (-value.score, value.matched_source_id)))


def record_match_decision(
    repository: Repository,
    match_id: str,
    *,
    source_id: str,
    matched_source_id: str,
    decision: str,
    matched_minor: int,
    expected_version: int,
) -> MatchDecisionResult:
    if decision not in {"confirmed", "rejected"}:
        raise ValueError("Match decision must be confirmed or rejected.")
    if type(matched_minor) is not int or matched_minor < 0:
        raise ValueError("Matched minor amount must be a non-negative integer.")
    suggestion = next(
        (
            value
            for value in suggest_matches(repository, source_id)
            if value.matched_source_id == matched_source_id
        ),
        None,
    )
    if suggestion is None:
        raise ValueError("The selected records are not eligible match candidates.")
    if decision == "rejected" and matched_minor != 0:
        raise ValueError("Rejected matches must use a zero matched amount.")
    if decision == "confirmed" and matched_minor <= 0:
        raise ValueError("Confirmed matches require a positive matched amount.")
    source = repository.get_source(source_id)
    candidate = repository.get_source(matched_source_id)
    assert source is not None and candidate is not None
    with repository.transaction() as transaction:
        source_remaining = abs(source.amount.minor) - transaction.confirmed_match_total(
            source_id, excluding=match_id
        )
        candidate_remaining = abs(candidate.amount.minor) - transaction.confirmed_match_total(
            matched_source_id, excluding=match_id
        )
        if decision == "confirmed" and matched_minor > min(source_remaining, candidate_remaining):
            raise ValueError("Confirmed amount exceeds the remaining unmatched amount.")
        match_version, source_version = transaction.decide_match(
            match_id=match_id,
            source_id=source_id,
            matched_source_id=matched_source_id,
            decision=decision,
            matched_minor=matched_minor,
            expected_version=expected_version,
            score=suggestion.score,
            reasons=suggestion.reasons,
        )
        revision = transaction.projected_revision
    return MatchDecisionResult(match_id, match_version, source_version, revision)


def _score(
    source: SourceRecord,
    candidate: SourceRecord,
) -> tuple[int, tuple[str, ...], int] | None:
    source_amount = abs(source.amount.minor)
    candidate_amount = abs(candidate.amount.minor)
    if source_amount == 0 or candidate_amount == 0:
        return None
    reasons: list[str] = []
    score = 0
    if source_amount == candidate_amount:
        score += 50
        reasons.append("Exact amount")
    elif min(source_amount, candidate_amount) < max(source_amount, candidate_amount):
        score += 25
        reasons.append("Possible partial amount")
    distance = abs((source.occurred_on - candidate.occurred_on).days)
    if distance == 0:
        score += 30
        reasons.append("Same date")
    elif distance <= 3:
        score += 20
        reasons.append(f"Date within {distance} day{'s' if distance != 1 else ''}")
    else:
        return None
    counterparty_overlap = _tokens(source.counterparty) & _tokens(candidate.counterparty)
    if counterparty_overlap:
        score += 10
        reasons.append("Counterparty tokens overlap")
    reference_overlap = _reference_tokens(source) & _reference_tokens(candidate)
    if reference_overlap:
        score += 10
        reasons.append("Reference tokens overlap")
    if score < 40:
        return None
    return score, tuple(reasons), min(source_amount, candidate_amount)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold()) if len(token) > 1}


def _reference_tokens(record: SourceRecord) -> set[str]:
    values = [record.description]
    values.extend(str(value) for key, value in record.extracted.items() if "ref" in key.casefold())
    return set().union(*(_tokens(value) for value in values))


def _match_id(source_id: str, matched_source_id: str) -> str:
    payload = f"{source_id}\0{matched_source_id}".encode()
    return "match-" + hashlib.sha256(payload).hexdigest()[:24]
