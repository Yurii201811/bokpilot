# Safety and privacy

## Accounting boundary

Bokpilot is a pre-accounting assistant. It prepares draft suggestions and review packets. It does not replace an accountant, bookkeeper, auditor, tax advisor, lawyer, or official guidance from Swedish authorities.

All accounting suggestions are marked as suggestions. Human review is required before export and before any posting in a real accounting system.

## High-risk areas

Treat these as human-review items even when Bokpilot suggests an account:

- Representation and meals.
- Vehicle costs, mileage, and private use.
- Cross-border purchases and reverse-charge VAT.
- Imports and customs VAT.
- Mixed private/business purchases.
- Owner deposits and withdrawals.
- Refunds, loans, and transfers between own accounts.
- Asset capitalization versus low-value equipment.
- Missing or incomplete receipts.
- Changed supplier bank details.
- Duplicate receipts or transactions.
- VAT returns, annual reports, and formal filings.

## Privacy model

The MVP runs locally and stores data in a SQLite database. It does not require external APIs or AI providers.

Default storage:

```text
data/bokpilot.sqlite3
```

Recommended handling:

- Do not commit real receipts or invoices.
- Keep workspace files out of public repositories.
- Keep backup archives out of public repositories too.
- Remove or redact personal data before sharing issue reports.
- If optional OCR or AI providers are added later, make them opt-in and document what leaves the machine.

Created export batches are immutable local artifacts. JSON omits raw document
text, evidence bytes, and local artifact paths by default. CSV neutralizes
user-controlled cells that spreadsheet software could interpret as formulas.
Downloads verify the stored byte count and SHA-256 before returning content.
Imported source files and later evidence attachments are stored locally by
SHA-256 with owner-only permissions. Attachments are add-only. Legacy records
without original bytes cannot be approved until the source file is attached;
manually attested records require a reviewer note.

On POSIX systems Bokpilot creates the data directory and database with
owner-only permissions. This reduces accidental exposure but does not encrypt
the database. Backup and restore commands verify archive paths and content
hashes; they are operational safeguards, not a substitute for an encrypted
off-device backup policy.

## Current limitations

- Text parsing is simple and intended for demos and structured text.
- SIE 4I has strict local conformance tests but is not certified until the recorded official-service release gate passes.
- BAS rules cover only common sample scenarios.
- The app has no user accounts or multi-user authorization. It binds only to loopback and uses Host, Origin, content-type, and per-startup session-token checks for the local browser boundary.
- There is no encrypted document store yet.

## Future safety work

- Workspace encryption option.
- Broader independently reviewed BAS/rule evidence and official SIE service validation.
- Permissioned integrations that can create drafts but not post or pay without explicit approval.
