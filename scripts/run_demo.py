"""Run a disposable preview-and-commit demonstration from the checkout."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from bokpilot.imports import commit_import, preview_import  # noqa: E402
from bokpilot.repository import Repository  # noqa: E402


def main() -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
