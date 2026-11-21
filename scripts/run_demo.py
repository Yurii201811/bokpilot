"""Run a disposable preview-and-commit demonstration from the checkout."""

from __future__ import annotations

import base64
import argparse
import json
import sys
import tempfile
from pathlib import Path
from dataclasses import replace
from datetime import date


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from bokpilot.imports import commit_import, preview_import  # noqa: E402
from bokpilot.accounts import AccountCatalog  # noqa: E402
from bokpilot.domain import AccountingMethod, CompanyProfile  # noqa: E402
from bokpilot.repository import Repository  # noqa: E402
from bokpilot.sample_data import load_sample_transactions  # noqa: E402
from bokpilot.server import make_server  # noqa: E402
from bokpilot.store import WorkspaceStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", type=Path)
    parser.add_argument("--port", type=int)
    arguments = parser.parse_args()
    if arguments.port is not None:
        return serve_demo(arguments.data_path, arguments.port)
    return run_disposable_demo()


def run_disposable_demo() -> int:
    content = (
        "Datum;Beskrivning;Belopp\n"
        "2026-07-01;Fortnox subscription;-249,00\n"
        "not-a-date;This row becomes an issue;-10,00\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory() as directory:
        repository = Repository(Path(directory) / "data" / "bokpilot.sqlite3")
        preview = preview_import(
            repository,
            {
                "kind": "bank_transaction",
                "filename": "demo.csv",
                "media_type": "text/csv; charset=utf-8",
                "content_base64": base64.b64encode(content).decode("ascii"),
                "locale": "sv-SE",
            },
        )
        commit = commit_import(
            repository,
            preview.batch_id,
            expected_workspace_revision=repository.workspace_revision(),
        )
        print(
            json.dumps(
                {
                    "preview_candidates": len(preview.candidates),
                    "preview_issues": [issue.to_dict() for issue in preview.issues],
                    "commit": commit.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def serve_demo(data_path: Path | None, port: int) -> int:
    path = (data_path or Path("/tmp/bokpilot-ui.sqlite3")).expanduser().resolve()
    system_temp = Path(tempfile.gettempdir()).resolve()
    if path.parent in {system_temp, Path("/private/tmp")}:
        path = system_temp / f".{path.stem}-data" / path.name
    store = WorkspaceStore(path)
    if store.repository.source_count() == 0:
        store.add_transactions(
            load_sample_transactions(),
            "synthetic_demo",
            expected_revision=store.repository.workspace_revision(),
            require_empty=True,
        )
    if store.repository.company_profile() is None:
        store.repository.save_company_profile(
            CompanyProfile(
                "Synthetic Bokpilot AB",
                AccountingMethod.CASH,
                date(2026, 1, 1),
                date(2026, 12, 31),
                "SEK",
                "BP",
            ),
            expected_revision=store.repository.workspace_revision(),
        )
    pending = AccountCatalog.production_default()
    approved = AccountCatalog(
        replace(
            entry,
            evidence_status="approved",
            reviewer="Synthetic test fixture",
            review_date=date(2026, 7, 11),
        )
        for entry in pending.entries()
    )
    server = make_server("127.0.0.1", port, store, catalog=approved, demo_mode=True)
    print(f"Synthetic Bokpilot demo at http://127.0.0.1:{port}")
    print("Synthetic accounting rules—do not use for real bookkeeping")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
