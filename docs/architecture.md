# Architecture

Bokpilot is a dependency-light local web app.

## Runtime

```text
Browser UI
  -> Python stdlib HTTP server
  -> parsers/rules/store/export modules
  -> local JSON workspace file
```

No external service is required for the demo. The default workspace file is:

```text
data/workspace.json
```

Override it with:

```bash
BOKPILOT_DATA_PATH=/tmp/bokpilot-workspace.json python3 -m bokpilot --port 8765
```

## Backend modules

- `bokpilot.server`: static web server and JSON API.
- `bokpilot.parsers`: bank CSV, receipt/invoice text, and manual transaction parsing.
- `bokpilot.rules`: deterministic BAS/VAT classification and journal-line generation.
- `bokpilot.store`: local JSON persistence and human review status.
- `bokpilot.exports`: JSON, CSV, and SIE-style draft export.
- `bokpilot.sample_data`: sample workspace loader.
- `bokpilot.models`: serializable money, suggestion, and journal-line structures.

## Frontend modules

- `static/index.html`: semantic UI shell.
- `static/styles.css`: responsive layout and visual system.
- `static/app.js`: local state, API calls, import flow, review actions, and export preview.

## API routes

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/workspace` | GET | Load current workspace and summary metrics. |
| `/api/load-sample` | POST | Import sample Swedish scenarios. Replacing a non-empty workspace requires `X-Bokpilot-Confirmation: replace-with-samples`. |
| `/api/reset` | POST | Clear the local workspace. Resetting a non-empty workspace requires `X-Bokpilot-Confirmation: reset-workspace`. |
| `/api/import/bank-csv` | POST | Import CSV text. |
| `/api/import/document` | POST | Import receipt/invoice text. |
| `/api/import/manual` | POST | Add one manual transaction. |
| `/api/items/{id}/review` | POST | Approve, reject, keep open, or override account/VAT. |
| `/api/export/json` | GET | Export approved human-reviewed items as JSON. |
| `/api/export/csv` | GET | Export approved human-reviewed summary CSV. |
| `/api/export/sie` | GET | Export approved human-reviewed SIE-style draft. |

## Safety controls

- Every suggestion has `review_required: true`.
- New items start as `needs_review`.
- Export functions include only `status == approved` and `human_reviewed == true`.
- Destructive sample replacement and workspace reset are rejected unless a non-empty workspace receives the matching custom confirmation header. A body token alone is never sufficient, so a cross-origin simple POST cannot erase data.
- One per-server lock serializes every POST mutation, keeping the destructive check and reset atomic relative to imports and reviews handled by that server.
- The UI displays the disclaimer and does not offer posting, filing, payment, or live accounting-system mutation.
- Risk flags are attached to low-confidence or context-dependent suggestions.

The server binds to `127.0.0.1` by default and has no authentication. A
non-loopback `--host` prints a warning; the confirmation header is a browser
CSRF guard, not authorization for network exposure.

## Why no database framework yet

The MVP is a public, easy-to-run demo. A JSON workspace is transparent, inspectable, and enough for import-review-export. A later multi-user or production deployment should move to SQLite/PostgreSQL with migrations, authentication, row-level permissions, and encrypted storage for documents.
