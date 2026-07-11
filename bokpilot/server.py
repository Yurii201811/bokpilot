"""Local Bokpilot web server and JSON API."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .exports import export_csv, export_json, export_sie_style, export_summary
from .parsers import manual_transaction, parse_bank_csv, parse_document_text
from .sample_data import load_sample_transactions
from .store import WorkspaceStore


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "static"


class BokpilotHandler(BaseHTTPRequestHandler):
    store: WorkspaceStore

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/workspace":
                workspace = self.store.load()
                workspace["summary"] = export_summary(workspace)
                self._json(workspace)
            elif path == "/api/export/json":
                self._text(export_json(self.store.load()), "application/json; charset=utf-8")
            elif path == "/api/export/csv":
                self._text(export_csv(self.store.load()), "text/csv; charset=utf-8")
            elif path == "/api/export/sie":
                self._text(export_sie_style(self.store.load()), "text/plain; charset=utf-8")
            else:
                self._static(path)
        except Exception as exc:  # noqa: BLE001 - API errors must return JSON, not crash the server.
            self._error(str(exc))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._payload()
            if path == "/api/reset":
                self._json(self.store.reset())
            elif path == "/api/load-sample":
                self.store.reset()
                workspace = self.store.add_transactions(load_sample_transactions(), "sample_data")
                workspace["summary"] = export_summary(workspace)
                self._json(workspace)
            elif path == "/api/import/bank-csv":
                filename = str(payload.get("filename") or "bank-csv")
                rows = parse_bank_csv(str(payload.get("content", "")), filename)
                workspace = self.store.add_transactions(rows, filename)
                workspace["summary"] = export_summary(workspace)
                self._json(workspace, HTTPStatus.CREATED)
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
            elif path.startswith("/api/items/") and path.endswith("/review"):
                item_id = path.split("/")[3]
                workspace = self.store.review_item(item_id, payload)
                workspace["summary"] = export_summary(workspace)
                self._json(workspace)
            else:
                self._error("Unknown API route.", HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self._error(str(exc))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    def _static(self, path: str) -> None:
        target = STATIC_ROOT / ("index.html" if path in {"/", ""} else path.lstrip("/"))
        if not target.exists() or not target.resolve().is_relative_to(STATIC_ROOT.resolve()):
            target = STATIC_ROOT / "index.html"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host: str, port: int, store: WorkspaceStore | None = None) -> ThreadingHTTPServer:
    handler = type("ConfiguredBokpilotHandler", (BokpilotHandler,), {"store": store or WorkspaceStore()})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Bokpilot web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-path", type=Path, default=None)
    args = parser.parse_args()

    store = WorkspaceStore(args.data_path) if args.data_path else WorkspaceStore()
    server = make_server(args.host, args.port, store)
    print(f"Bokpilot running at http://{args.host}:{args.port}")
    print(f"Local workspace: {store.path}")
    server.serve_forever()


if __name__ == "__main__":
    main()
