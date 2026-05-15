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

The MVP runs locally and stores data in a JSON workspace file. It does not require external APIs or AI providers.

Default storage:

```text
data/workspace.json
```

Recommended handling:

- Do not commit real receipts or invoices.
- Keep workspace files out of public repositories.
- Remove or redact personal data before sharing issue reports.
- If optional OCR or AI providers are added later, make them opt-in and document what leaves the machine.

## Current limitations

- Text parsing is simple and intended for demos and structured text.
- The SIE-style export is not a certified SIE implementation.
- BAS rules cover only common sample scenarios.
- The app has no authentication because it is intended for local use.
- There is no encrypted document store yet.

## Future safety work

- Validated SIE 4 output with fixtures.
- Append-only review history.
- Workspace encryption option.
- Source document attachment checks.
- Permissioned integrations that can create drafts but not post or pay without explicit approval.
