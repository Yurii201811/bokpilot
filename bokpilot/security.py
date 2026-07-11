"""Fail-closed policy helpers for Bokpilot's localhost HTTP boundary."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from http import HTTPStatus
from urllib.parse import urlparse


@dataclass
class ApiError(Exception):
    code: str
    message: str
    status: HTTPStatus = HTTPStatus.BAD_REQUEST
    fields: dict[str, str] = field(default_factory=dict)


def require_loopback_bind(host: str) -> None:
    normalized = str(host).strip().lower()
    if normalized == "localhost":
        return
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise ValueError("Bokpilot must bind to an explicit loopback address.") from exc
    if not address.is_loopback:
        raise ValueError("Bokpilot must bind to a loopback address, not a public interface.")


def allowed_host_headers(bound_host: str, port: int) -> frozenset[str]:
    normalized = str(bound_host).strip().lower()
    values = {f"{normalized}:{port}"}
    if normalized in {"127.0.0.1", "localhost"}:
        values.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    if normalized == "::1":
        values.add(f"[::1]:{port}")
    return frozenset(values)


def validate_host(value: str | None, allowed: frozenset[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ApiError(
            "misdirected_request",
            "Request Host is not accepted by this local Bokpilot server.",
            HTTPStatus.MISDIRECTED_REQUEST,
        )
    return normalized


def validate_origin(value: str | None, validated_host: str) -> None:
    if value is None:
        return
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.netloc.lower() != validated_host
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ApiError(
            "origin_forbidden",
            "Cross-origin mutation requests are not allowed.",
            HTTPStatus.FORBIDDEN,
        )
