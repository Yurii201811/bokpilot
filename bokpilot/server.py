"""Local Bokpilot web server and JSON API."""

from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import socket
import sys
from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from typing import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .exports import (
    create_csv_batch,
    create_json_batch,
    create_sie4i_batch,
    export_csv,
    export_json,
    export_sie_style,
    export_summary,
    read_export_batch,
)
from . import __version__
from .accounts import AccountCatalog
from .domain import AccountingMethod, CompanyProfile, ReviewDecision, TransactionNature, VatTreatment
from .imports import attach_source_evidence, commit_import, get_import_preview, preview_import
from .matching import record_match_decision, suggest_matches
from .parsers import manual_transaction, parse_bank_csv, parse_document_text
from .resources import resource_file
from .sample_data import load_sample_transactions
from .review import ApprovalBlocked, record_duplicate_decision, record_review
from .security import (
    ApiError,
    allowed_host_headers,
    require_loopback_bind,
    validate_host,
    validate_origin,
)
from .store import WorkspaceStore


STATIC_ASSETS = {
    "": "index.html",
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
}

MAX_JSON_BODY = 14 * 1024 * 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


class BokpilotHandler(BaseHTTPRequestHandler):
    store: WorkspaceStore
    session_token: str
    allowed_hosts: frozenset[str]
    account_catalog: AccountCatalog
    company_profile: CompanyProfile
    demo_mode: bool

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        request_id = uuid4().hex
        try:
            self._validated_host = validate_host(self.headers.get("Host"), self.allowed_hosts)
            if path == "/api/session":
                self._json(
                    {
                        "token": self.session_token,
                        "workspace_revision": self.store.repository.workspace_revision(),
                        "version": __version__,
                    }
                )
                return
            if path == "/api/workspace":
                workspace = self.store.load()
                workspace["summary"] = export_summary(workspace)
                workspace["demo_mode"] = self.demo_mode
                self._json(workspace)
            elif path.startswith("/api/imports/") and len(path.split("/")) == 4:
                preview = get_import_preview(self.store.repository, path.split("/")[3])
                payload = preview.to_dict()
                payload["workspace_revision"] = self.store.repository.workspace_revision()
                self._json(payload)
            elif path.startswith("/api/sources/") and path.endswith("/matches"):
                source_id = path.split("/")[3]
                self._json(
                    {
                        "source_id": source_id,
                        "matches": [
                            value.to_dict()
                            for value in suggest_matches(self.store.repository, source_id)
                        ],
                        "workspace_revision": self.store.repository.workspace_revision(),
                    }
                )
            elif path.startswith("/api/sources/") and path.endswith("/reviews"):
                source_id = path.split("/")[3]
                self._json(
                    {
                        "source_id": source_id,
                        "reviews": list(self.store.repository.review_history(source_id)),
                        "workspace_revision": self.store.repository.workspace_revision(),
                    }
                )
            elif path == "/api/export/json":
                self._text(export_json(self.store.load()), "application/json; charset=utf-8")
            elif path == "/api/export/csv":
                self._text(export_csv(self.store.load()), "text/csv; charset=utf-8")
            elif path == "/api/export/sie":
                self._text(export_sie_style(self.store.load()), "text/plain; charset=utf-8")
            elif path.startswith("/api/exports/") and path.endswith("/download"):
                batch_id = path.split("/")[3]
                record = self.store.repository.export_record(batch_id)
                if record is None:
                    raise ApiError("not_found", "Export batch was not found.", HTTPStatus.NOT_FOUND)
                content = read_export_batch(self.store.repository, batch_id)
                format_name = str(record["format"])
                extension = "se" if format_name == "sie4i" else format_name
                filename = f"bokpilot-export-{str(record['created_at'])[:10].replace('-', '')}.{extension}"
                content_type = {
                    "json": "application/json; charset=utf-8",
                    "csv": "text/csv; charset=utf-8",
                    "sie4i": "application/octet-stream",
                }.get(format_name, "application/octet-stream")
                self._bytes(
                    content,
                    content_type,
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            elif path.startswith("/api/"):
                raise ApiError("not_found", "API route was not found.", HTTPStatus.NOT_FOUND)
            else:
                self._static(path)
        except Exception as exc:  # noqa: BLE001 - centralized safe API boundary.
            self._handle_exception(exc, path, request_id)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        request_id = uuid4().hex
        try:
            self._validated_host = validate_host(self.headers.get("Host"), self.allowed_hosts)
            self._authorize_mutation()
            payload = self._payload()
            if path == "/api/reset":
                if payload.get("confirmation") != "RESET":
                    raise ValueError("Reset requires the exact confirmation RESET.")
                expected_revision = payload.get("expected_revision")
                if type(expected_revision) is not int:
                    raise ValueError("Reset expected_revision must be an integer.")
                if self.store.repository.workspace_revision() != expected_revision:
                    raise ValueError(
                        f"Workspace revision conflict: expected {expected_revision}, "
                        f"current {self.store.repository.workspace_revision()}."
                    )
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup_path = self.store.path.parent / "backups" / f"reset-{stamp}-{uuid4().hex[:8]}.bokpilot-backup"
                backup = self.store.repository.backup_to(
                    backup_path,
                    self.store.path.parent / "attachments",
                    self.store.path.parent / "exports",
                )
                workspace = self.store.reset(expected_revision=expected_revision)
                workspace["summary"] = export_summary(workspace)
                workspace["backup"] = {
                    "path": str(backup.bundle_path),
                    "sha256": backup.sha256,
                    "workspace_revision": backup.workspace_revision,
                }
                self._json(workspace)
            elif path == "/api/load-sample":
                expected_revision = payload.get("expected_workspace_revision")
                if type(expected_revision) is not int:
                    raise ValueError("Sample loading requires expected_workspace_revision.")
                workspace = self.store.add_transactions(
                    load_sample_transactions(),
                    "sample_data",
                    expected_revision=expected_revision,
                    require_empty=True,
                )
                workspace["summary"] = export_summary(workspace)
                self._json(workspace)
            elif path == "/api/import/bank-csv":
                filename = str(payload.get("filename") or "bank-csv")
                locale = str(payload.get("locale") or "auto")
                rows = parse_bank_csv(str(payload.get("content", "")), filename, locale)
                workspace = self.store.add_transactions(rows, filename)
                workspace["summary"] = export_summary(workspace)
                self._json(workspace, HTTPStatus.CREATED)
            elif path == "/api/imports/preview":
                preview = preview_import(self.store.repository, payload)
                response = preview.to_dict()
                response["workspace_revision"] = self.store.repository.workspace_revision()
                self._json(response, HTTPStatus.CREATED)
            elif path.startswith("/api/imports/") and path.endswith("/commit"):
                batch_id = path.split("/")[3]
                result = commit_import(
                    self.store.repository,
                    batch_id,
                    expected_workspace_revision=payload.get("expected_workspace_revision"),
                )
                self._json(result.to_dict())
            elif path.startswith("/api/sources/") and path.endswith("/attachment"):
                source_id = path.split("/")[3]
                self._json(
                    attach_source_evidence(self.store.repository, source_id, payload),
                    HTTPStatus.CREATED,
                )
            elif path.startswith("/api/matches/") and path.endswith("/decision"):
                match_id = path.split("/")[3]
                result = record_match_decision(
                    self.store.repository,
                    match_id,
                    source_id=str(payload.get("source_id") or ""),
                    matched_source_id=str(payload.get("matched_source_id") or ""),
                    decision=str(payload.get("decision") or ""),
                    matched_minor=payload.get("matched_minor"),
                    expected_version=payload.get("expected_version"),
                )
                self._json(result.to_dict())
            elif path.startswith("/api/sources/") and path.endswith("/duplicate-decision"):
                source_id = path.split("/")[3]
                result = record_duplicate_decision(
                    self.store.repository,
                    source_id,
                    candidate_id=str(payload.get("duplicate_candidate_id") or ""),
                    decision=str(payload.get("decision") or ""),
                    note=str(payload.get("note") or ""),
                    expected_version=payload.get("expected_version"),
                )
                self._json(result.to_dict())
            elif path.startswith("/api/sources/") and path.endswith("/review"):
                source_id = path.split("/")[3]
                status = str(payload.get("status") or "")
                action = {"approved": "approved", "rejected": "rejected", "needs_review": "reopened"}.get(status)
                if action is None:
                    raise ValueError("Review status must be approved, rejected, or needs_review.")
                decision = ReviewDecision(
                    nature=TransactionNature(str(payload.get("nature") or "unknown")),
                    account=str(payload.get("bas_account") or payload.get("account") or ""),
                    vat=VatTreatment(
                        str(payload.get("vat"))
                        if payload.get("vat") not in (None, "")
                        else (
                            format(Decimal(str(payload.get("vat_rate"))), "f").rstrip("0").rstrip(".")
                            or "0"
                            if payload.get("vat_rate") not in (None, "")
                            else "unknown"
                        )
                    ),
                    vat_minor=(
                        int(payload["vat_minor"])
                        if payload.get("vat_minor") not in (None, "")
                        else None
                    ),
                    reviewer_note=str(payload.get("reviewer_note") or ""),
                    risk_acknowledged=bool(payload.get("risk_acknowledged", False)),
                )
                result = record_review(
                    self.store.repository,
                    source_id,
                    action=action,
                    decision=decision,
                    profile=self.store.repository.company_profile() or self.company_profile,
                    catalog=self.account_catalog,
                    expected_version=payload.get("expected_version"),
                )
                self._json(result.to_dict())
            elif path == "/api/exports":
                format_name = str(payload.get("format") or "")
                review_ids = payload.get("review_ids")
                if not isinstance(review_ids, list) or not all(isinstance(value, str) for value in review_ids):
                    raise ValueError("Export review_ids must be a list of strings.")
                expected_revision = payload.get("expected_workspace_revision")
                if format_name == "json":
                    batch = create_json_batch(
                        self.store.repository,
                        review_ids,
                        expected_revision=expected_revision,
                    )
                elif format_name == "csv":
                    batch = create_csv_batch(
                        self.store.repository,
                        review_ids,
                        expected_revision=expected_revision,
                    )
                elif format_name == "sie4i":
                    profile = self.store.repository.company_profile()
                    if profile is None:
                        raise ValueError("Complete the company profile before SIE 4I export.")
                    batch = create_sie4i_batch(
                        self.store.repository,
                        review_ids,
                        profile,
                        expected_revision=expected_revision,
                    )
                else:
                    raise ValueError("Export format must be json, csv, or sie4i.")
                self._json(batch.to_dict(), HTTPStatus.CREATED)
            elif path == "/api/profile":
                profile = CompanyProfile(
                    name=str(payload.get("name") or "").strip(),
                    accounting_method=AccountingMethod(str(payload.get("accounting_method") or "")),
                    fiscal_year_start=date.fromisoformat(str(payload.get("fiscal_year_start") or "")),
                    fiscal_year_end=date.fromisoformat(str(payload.get("fiscal_year_end") or "")),
                    currency=str(payload.get("currency") or "SEK").upper(),
                    voucher_series=str(payload.get("voucher_series") or "").strip(),
                    organization_number=(
                        str(payload["organization_number"]).strip()
                        if payload.get("organization_number")
                        else None
                    ),
                )
                if not profile.name:
                    raise ValueError("Company name is required.")
                result = self.store.repository.save_company_profile(
                    profile,
                    expected_revision=payload.get("expected_workspace_revision"),
                )
                self._json(
                    {
                        "company_profile": {
                            "name": profile.name,
                            "accounting_method": profile.accounting_method.value,
                            "fiscal_year_start": profile.fiscal_year_start.isoformat(),
                            "fiscal_year_end": profile.fiscal_year_end.isoformat(),
                            "currency": profile.currency,
                            "voucher_series": profile.voucher_series,
                            "organization_number": profile.organization_number,
                        },
                        "workspace_revision": result.revision,
                    }
                )
            elif path == "/api/import/document":
                raw = parse_document_text(
                    str(payload.get("filename") or "document.txt"),
                    str(payload.get("content") or ""),
                    str(payload.get("kind") or "document"),
                )
                workspace = self.store.add_transactions([raw], payload.get("filename") or "document")
                workspace["summary"] = export_summary(workspace)
                self._json(workspace, HTTPStatus.CREATED)
            elif path == "/api/import/manual":
                raw = manual_transaction(payload)
                workspace = self.store.add_transactions([raw], "manual")
                workspace["summary"] = export_summary(workspace)
                self._json(workspace, HTTPStatus.CREATED)
            else:
                raise ApiError("not_found", "API route was not found.", HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self._handle_exception(exc, path, request_id)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _payload(self) -> dict:
        value = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(value)
        except ValueError as exc:
            raise ApiError("invalid_content_length", "Content-Length must be an integer.") from exc
        if length < 0:
            raise ApiError("invalid_content_length", "Content-Length cannot be negative.")
        if length > MAX_JSON_BODY:
            raise ApiError(
                "request_too_large",
                "JSON request body exceeds the 14 MiB limit.",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if length == 0:
            return {}
        try:
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("invalid_json", "Request body must contain valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise ApiError("invalid_json_shape", "Request JSON must be an object.")
        return payload

    def _authorize_mutation(self) -> None:
        validate_origin(self.headers.get("Origin"), self._validated_host)
        supplied = self.headers.get("X-Bokpilot-Token") or ""
        if not secrets.compare_digest(supplied, self.session_token):
            raise ApiError(
                "session_forbidden",
                "A valid local Bokpilot session token is required.",
                HTTPStatus.FORBIDDEN,
            )
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(
                "unsupported_media_type",
                "Mutation requests require application/json.",
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            )

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, content_type: str) -> None:
        self._bytes(body.encode("utf-8"), content_type)

    def _bytes(
        self,
        encoded: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, error: ApiError) -> None:
        self._json(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "fields": dict(error.fields),
                }
            },
            error.status,
        )

    def _handle_exception(self, exc: Exception, path: str, request_id: str) -> None:
        if isinstance(exc, ApiError):
            error = exc
        elif isinstance(exc, ApprovalBlocked):
            error = ApiError(
                "approval_blocked",
                "Resolve the highlighted review issues before approval.",
                HTTPStatus.CONFLICT,
                {issue.field: issue.message for issue in exc.issues},
            )
        elif isinstance(exc, ValueError):
            message = str(exc)
            if "not empty" in message.casefold():
                status = HTTPStatus.CONFLICT
                code = "workspace_not_empty"
            else:
                status = HTTPStatus.CONFLICT if "conflict" in message.casefold() else HTTPStatus.BAD_REQUEST
                code = "version_conflict" if status is HTTPStatus.CONFLICT else "invalid_request"
            error = ApiError(code, message, status)
        else:
            error = ApiError(
                "internal_error",
                "Bokpilot could not complete the request.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        print(
            f"bokpilot_error code={error.code} route={path} request_id={request_id}",
            file=sys.stderr,
        )
        self._error(error)

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def _static(self, path: str) -> None:
        filename = STATIC_ASSETS.get(path, "index.html")
        target = resource_file("static", filename)
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    host: str,
    port: int,
    store: WorkspaceStore | None = None,
    *,
    catalog: AccountCatalog | None = None,
    profile: CompanyProfile | None = None,
    demo_mode: bool = False,
) -> ThreadingHTTPServer:
    require_loopback_bind(host)
    configured_store = store or WorkspaceStore()
    server_class = ThreadingHTTPServer
    if ":" in host:
        server_class = type(
            "IPv6ThreadingHTTPServer",
            (ThreadingHTTPServer,),
            {"address_family": socket.AF_INET6},
        )
    server = server_class((host, port), BokpilotHandler)
    bound_host, bound_port = server.server_address[:2]
    handler = type(
        "ConfiguredBokpilotHandler",
        (BokpilotHandler,),
        {
            "store": configured_store,
            "session_token": secrets.token_urlsafe(32),
            "allowed_hosts": allowed_host_headers(str(bound_host), int(bound_port)),
            "account_catalog": catalog or AccountCatalog.production_default(),
            "company_profile": profile
            or CompanyProfile(
                name="Local Bokpilot workspace",
                accounting_method=AccountingMethod.CASH,
                fiscal_year_start=date(date.today().year, 1, 1),
                fiscal_year_end=date(date.today().year, 12, 31),
                currency="SEK",
                voucher_series="A",
            ),
            "demo_mode": bool(demo_mode),
        },
    )
    server.RequestHandlerClass = handler
    return server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local Bokpilot web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-path", type=Path, default=None)
    args = parser.parse_args(argv)

    store = WorkspaceStore(args.data_path) if args.data_path else WorkspaceStore()
    try:
        server = make_server(args.host, args.port, store)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Bokpilot running at http://{args.host}:{args.port}")
    print(f"Local workspace: {store.path}")
    server.serve_forever()


if __name__ == "__main__":
    main()
