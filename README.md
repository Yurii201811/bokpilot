# Bokpilot

**Local-first pre-accounting assistant for Swedish small businesses.**

Bokpilot helps freelancers, micro-business owners, bookkeepers, accountants, and immigrant entrepreneurs prepare cleaner bookkeeping material before it reaches an accounting system. It imports receipts, invoices, and bank CSV rows; suggests BAS accounts and VAT treatment; explains the reasoning; requires human review; and exports approved-only immutable JSON, CSV, or SIE 4I review packets.

It is not an autonomous accountant. Bokpilot generates suggestions only and does not provide professional accounting, tax, or legal advice.

## Why this exists

Small businesses often lose time before the actual bookkeeping starts: receipts are scattered, bank rows are unclear, VAT rates vary, BAS accounts are unfamiliar, and accountants receive incomplete material. Bokpilot focuses on the pre-accounting step: collect, classify, explain, review, and export.

The first version is deliberately local-first and dependency-light. It does not require Fortnox, Visma, Bokio, paid OCR, or an AI provider to run.

## What works in the MVP

- Import sample receipts, supplier invoices, customer invoices, and bank CSV transactions.
- Add manual transactions from the UI.
- Parse basic text documents with fields such as `Supplier`, `Date`, `Total`, `VAT`, and `Description`.
- Parse CSV files with common Swedish or English headers for date, description, signed amount, currency, or split debit/credit and in/out amount columns.
- Preserve bank CSV source filename and row number on imported items for reviewer traceability.
- Suggest BAS account mappings and VAT treatment using deterministic rules.
- Explain each suggestion in plain language.
- Show confidence, risk flags, and draft double-entry journal lines.
- Let a human approve, reject, keep open, or override BAS/VAT treatment.
- Export current approved review decisions as privacy-safe JSON, formula-safe CSV, or strict CP437 SIE 4I batches.
- Store data locally in `data/bokpilot.sqlite3` by default, with transactional writes and revision checks.
- Run tests without external services.

## Quick start

Requires Python 3.10 or newer.

```bash
git clone YOUR_BOKPILOT_REPOSITORY_URL
cd bokpilot
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m bokpilot --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765), then:

1. Select `Load samples`.
2. Open a review item.
3. Inspect the BAS/VAT reasoning and journal lines.
4. Approve only when the configured account/rule evidence is qualified and every issue is resolved.
5. Download an immutable JSON, CSV, or SIE 4I batch and record its SHA-256.

For a synthetic end-to-end approval demo that never enables its test catalog in
normal startup:

```bash
python3 scripts/run_demo.py --data-path /tmp/bokpilot-demo/bokpilot.sqlite3 --port 8765
```

The persistent banner identifies this mode as synthetic and unsuitable for real bookkeeping.

Use a separate local workspace file:

```bash
BOKPILOT_DATA_PATH=/tmp/bokpilot-data/bokpilot.sqlite3 python3 -m bokpilot --port 8765
```

Legacy JSON workspaces require an explicit, non-destructive migration:

```bash
python3 -m bokpilot migrate --from-json data/workspace.json --to-sqlite data/bokpilot.sqlite3
```

Create and restore integrity-checked local backups:

```bash
python3 -m bokpilot backup --to /tmp/bokpilot-backups/bokpilot.bokpilot-backup
python3 -m bokpilot restore \
  --from /tmp/bokpilot-backups/bokpilot.bokpilot-backup \
  --to /tmp/restored-bokpilot \
  --sha256 SHA256_PRINTED_BY_BACKUP
```

Run tests:

```bash
python3 -m unittest
```

Install the package and run the console command:

```bash
python3 -m pip install .
bokpilot --port 8765
```

For a non-editable wheel install, run the wheel smoke command below, then install
the generated wheel from its reported temporary wheelhouse or build one with
`python3 -m pip wheel . --no-deps --wheel-dir dist`.

To build a wheel in a temporary directory and smoke-test its installed web assets and sample data from outside the checkout:

```bash
python3 scripts/smoke_installed.py --build-wheel
```

## Inputs and local data

- Bank CSV: UTF-8, UTF-8 with BOM, or Windows-1252 text, with explicit preview and column mapping when detection is incomplete.
- Receipt and invoice text: structured labels such as Date, Supplier, Total, VAT, and Description.
- Manual entries: require a reviewer attestation note.
- Decoded file content is capped at 10 MiB and preserved byte-for-byte under its SHA-256 after commit.

The default database is `data/bokpilot.sqlite3`; attachments, exports, staging,
and reset backups live beside it. `.env.example` documents process variables,
but Bokpilot does not auto-load `.env` files. Set variables in your shell or
service manager.

## Backup, migration, and troubleshooting

See [backup and restore](docs/backup-and-restore.md) for rehearsable commands.

- `Legacy JSON workspaces require explicit migration`: run the migration command; do not point the server at the JSON file.
- `Repository requires a dedicated data directory`: choose a private subdirectory rather than a database directly under `/tmp` or `/`.
- `Workspace revision conflict`: refresh the page and repeat the decision against the current version.
- Approval blocked: resolve every field in the error summary; production account/rule rows remain disabled until qualified review is recorded.
- Port already in use: select another loopback port with `--port`; never solve this by binding to a public interface.

## Uninstall without deleting data

```bash
python3 -m pip uninstall bokpilot
```

Uninstalling the package does not delete the local data directory. Back it up,
then remove that directory separately only when you intentionally want to erase
the database, attachments, exports, and backups.

## Demo flow

The sample dataset includes:

- `Fortnox subscription May` -> software expense, BAS 5420, 25% input VAT.
- `Pressbyran kontorsmaterial` -> office supplies, BAS 6110, 25% input VAT.
- `Customer invoice 2026-104 paid` -> Swedish sales, BAS 3011, output VAT 2611.
- `Bankavgift foretagskonto` -> bank fees, BAS 6570, no VAT.
- `SJ train ticket client meeting` -> travel, BAS 5800, 6% VAT, review flag.
- `Lunch with client Stockholm` -> meals/representation, review flag.
- `IKEA desk lamp workspace` -> small equipment, review flag.
- `Circle K fuel client visit` -> vehicle fuel, review flag.

Example input files ship inside [the Bokpilot package](bokpilot/resources/samples). Illustrative export snapshots live in [examples/exports](examples/exports).

## Screenshots

Desktop review and export flow:

![Bokpilot desktop dashboard](docs/assets/bokpilot-dashboard.png)

Mobile responsive view:

![Bokpilot mobile view](docs/assets/bokpilot-mobile.png)

## Project structure

```text
bokpilot/             Python backend, parsers, rules, data store, exporters
  resources/static/   Packaged web UI
  resources/samples/  Packaged Swedish demo receipt, invoice, and bank CSV inputs
examples/exports/     Example export snapshots
tests/                Standard-library unit tests
docs/                 Product brief, architecture, data model, workflows
```

## Documentation

- [Product brief](docs/product-brief.md)
- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Example workflows](docs/example-workflows.md)
- [Safety and privacy](docs/safety-and-privacy.md)
- [Integration roadmap](docs/integration-roadmap.md)
- [Launch checklist](docs/launch-checklist.md)
- [Backup and restore](docs/backup-and-restore.md)
- [Release evidence checklist](docs/release-checklist.md)

## Safety principles

- Suggestions are drafts until a person approves them.
- Exports include approved items only.
- Risky areas such as representation, vehicle costs, cross-border VAT, reverse charge, assets, owner deposits, refunds, and tax filings need human review.
- Bokpilot does not file VAT returns, post vouchers to live systems, move money, send client messages, or delete source documents.
- The local-first default avoids unnecessary upload of sensitive receipts and invoices.

## Roadmap

- Better receipt and invoice extraction for common Swedish formats.
- First-class BAS 2026 import from machine-readable account files.
- Configurable company profile, fiscal years, voucher series, and accounting method.
- Attach original PDFs/images to review packets.
- Optional OCR and optional AI explanation provider with deterministic fallback.
- Validated SIE 4 export and SIE 5 exploration.
- Fortnox, Visma, Bokio, ERPNext, and Frappe Books compatibility adapters.
- Accountant review mode with comments, change history, and monthly close packets.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first contributions include parser fixtures, Swedish bookkeeping examples, BAS account rule improvements, accessibility fixes, and export validation.

## License

MIT. See [LICENSE](LICENSE).
