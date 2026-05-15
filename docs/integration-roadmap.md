# Integration roadmap

Bokpilot should integrate with real accounting systems carefully and in stages.

## Stage 1: Export compatibility

- Keep JSON and CSV stable.
- Improve SIE-style export toward validated SIE 4.
- Add example import notes for Fortnox, Visma, Bokio, ERPNext, and Frappe Books.
- Keep exports approved-only.

## Stage 2: Read-only adapters

- Read chart of accounts from a configured accounting system.
- Read supplier/customer lists to improve matching.
- Read previous coding history to suggest more consistent BAS accounts.
- Do not write vouchers yet.

## Stage 3: Draft-only write adapters

- Create draft vouchers or supplier invoice drafts.
- Attach source documents.
- Add reviewer notes and confidence metadata.
- Never create payments, submit VAT returns, or post final vouchers without explicit human approval.

## Stage 4: Accountant workflow

- Multi-reviewer comments.
- Monthly packet status.
- Missing-information requests.
- Audit trail and immutable export logs.
- Policy gates for high-risk categories.

## Integration notes

- Fortnox and Visma have APIs that can support accounting and invoice workflows, but they require real authentication and permission design.
- Bokio supports SIE export, which makes SIE compatibility valuable even before direct API work.
- Frappe Books is local-first and open source, so an adapter can focus on JSON/CSV import patterns and account mapping rather than cloud authentication.
