# Release evidence checklist

## Automated export evidence

- [x] Share-safe JSON omits raw document text, local paths, and evidence bytes.
- [x] CSV user-controlled text is neutralized against spreadsheet formulas.
- [x] SIE text rejects control characters and invalid account, date, currency, and voucher-series tokens.
- [x] SIE vouchers are balanced and encode once with strict CP437 handling.
- [x] Export artifacts are content-addressed, private, immutable, and checksum-verified on download.

The synthetic local fixture is `tests/fixtures/sie/approved-packet.se`. It is
test data only and contains no user records. The local structural/CP437 test
passes. The fixture was regenerated with Bokpilot `0.2.0`. Current local
SHA-256: `7c7e8060f25233048d6e86b53c4cb4e0a672fdd74428fc29fffb426fd7943786`.
This is the checksum that must accompany the future official service result;
regenerate and replace it if the fixture changes.

## Manual external gate

- [ ] **Blocked:** all enabled account and rule rows in `docs/accounting-evidence.md` are marked approved by a named qualified reviewer with a real review date.
- [ ] **Blocked:** upload the final version-`0.2.0` synthetic SIE fixture to the official SIE test service and record specification edition, validation date, SHA-256, and result.
- [x] Zero known unresolved high-priority security/privacy regressions in the local suite.
- [x] Legacy v0.1 migration and verified restore are rehearsed by automated fixtures.
- [x] Wheel smoke confirmed on Python 3.10 and 3.14 in required CI (PR #2 matrix: Python 3.10–3.14).
- [x] Desktop, mobile, and keyboard-oriented review corridor evidence recorded.
- [x] Default export tests confirm no raw documents or local paths.
- [x] Tracked package samples and parser/export fixtures are synthetic; no user workspace artifacts are tracked.

This external validation is intentionally open. It must not be marked complete without the real service result.

Overall v0.2 release gate: **BLOCKED on the two manual external gates.** No
reviewer identity or SIE service result has been inferred or fabricated.

## Local UI evidence (2026-07-12)

- [x] Desktop corridor verified at 1440×900.
- [x] Mobile corridor verified at 390×844 with no horizontal overflow, two-column metrics, and card-style queue rows.
- [x] Risk approval blocked until acknowledgement and a reviewer note were supplied.
- [x] Synthetic approval advanced focus to the next review item and persisted immutable history.
- [x] Normal server startup does not enable the synthetic accounting catalog; demo mode displays a persistent warning.
- [x] Updated synthetic screenshots: `docs/assets/bokpilot-dashboard.png` and `docs/assets/bokpilot-mobile.png`.
