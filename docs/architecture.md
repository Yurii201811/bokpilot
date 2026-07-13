# Architecture

Bokpilot is a dependency-light local web app.

## Runtime

```text
Browser UI
  -> Python stdlib HTTP server
  -> parsers/rules/store/export modules
  -> repository transactions
  -> local SQLite database
```

No external service is required for the demo. The default workspace file is:

```text
data/bokpilot.sqlite3
```

Override it with:

```bash
BOKPILOT_DATA_PATH=/tmp/bokpilot.sqlite3 python3 -m bokpilot --port 8765
```

## Backend modules

- `bokpilot.server`: static web server and JSON API.
- `bokpilot.parsers`: bank CSV, receipt/invoice text, and manual transaction parsing.
- `bokpilot.rules`: deterministic BAS/VAT classification and journal-line generation.
- `bokpilot.store`: compatibility workspace API and human review operations.
- `bokpilot.repository`: schema-v2 SQLite persistence, transactions, revisions, and query paging.
- `bokpilot.migrations`: explicit, idempotent migration from legacy JSON workspaces.
- `bokpilot.backups`: integrity-checked backup creation and atomic restore.
- `bokpilot.exports`: immutable privacy-safe JSON/CSV and SIE 4I export batches.
- `bokpilot.sample_data`: sample workspace loader.
- `bokpilot.models`: serializable money, suggestion, and journal-line structures.

## Frontend modules

- `static/index.html`: semantic UI shell.
- `static/styles.css`: responsive layout and visual system.
- `static/app.js`: local state, API calls, import flow, review actions, and export preview.

## API routes

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/session` | GET | Return the startup session token, version, and current workspace revision. |
| `/api/workspace` | GET | Load current workspace and summary metrics. |
| `/api/profile` | POST | Save a revision-checked company profile. |
| `/api/load-sample` | POST | Import synthetic scenarios into an empty workspace. |
| `/api/reset` | POST | Create a verified backup, then clear the workspace after exact confirmation. |
| `/api/imports/preview` | POST | Validate and stage original file bytes without creating review items. |
| `/api/imports/{batch_id}` | GET | Read an immutable import preview. |
| `/api/imports/{batch_id}/commit` | POST | Commit a revision-checked preview idempotently. |
| `/api/sources/{id}/attachment` | POST | Add verified source evidence when a migrated item lacks original bytes. |
| `/api/sources/{id}/review` | POST | Approve, reject, reopen, or override account/VAT with an expected item version. |
| `/api/sources/{id}/reviews` | GET | Read immutable review history. |
| `/api/sources/{id}/matches` | GET | Read explainable same-currency match suggestions. |
| `/api/matches/{id}/decision` | POST | Confirm or reject a suggested match. |
| `/api/sources/{id}/duplicate-decision` | POST | Resolve a duplicate candidate with a reviewer note. |
| `/api/exports` | POST | Create an immutable approved-review JSON, CSV, or SIE 4I batch. |
| `/api/exports/{id}/download` | GET | Verify and download the stored artifact bytes. |

The direct `/api/import/bank-csv`, `/api/import/document`, and
`/api/import/manual` routes remain for compatibility with v0.1 clients. File
imports through those routes do not possess preserved original bytes and are
therefore marked `legacy_unavailable`; approval stays blocked until evidence
is attached. New file-import clients must use preview and commit.

## Safety controls

- Every suggestion has `review_required: true`.
- New items start as `needs_review`.
- Export functions include only `status == approved` and `human_reviewed == true`.
- `legacy_unavailable` source evidence blocks approval; attaching verified bytes clears only that gate and advances the item version.
- `manual_attested` evidence requires a non-empty reviewer note.
- The UI displays the disclaimer and does not offer posting, filing, payment, or live accounting-system mutation.
- Risk flags are attached to low-confidence or context-dependent suggestions.

## Storage and concurrency

SQLite is used through Python's standard library, so the app remains dependency-light and needs no database server. Application mutations run in explicit transactions. Each committed mutation advances a monotonic workspace revision; stale writes are rejected instead of silently overwriting newer review work.

The database and its parent directory are created with owner-only permissions where the platform supports POSIX modes. This protects against accidental local disclosure, but it is not encryption and does not replace operating-system account security.

Legacy JSON files are never opened as live workspaces. Migration must be requested explicitly:

```bash
python3 -m bokpilot migrate --from-json data/workspace.json --to-sqlite data/bokpilot.sqlite3
```

The source JSON is preserved, and repeated migration of the same source is detected. Backup archives contain a manifest and SHA-256 hashes; restore validates archive paths and hashes before replacing the destination database atomically.
