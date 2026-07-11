# Release evidence checklist

## Automated export evidence

- [x] Share-safe JSON omits raw document text, local paths, and evidence bytes.
- [x] CSV user-controlled text is neutralized against spreadsheet formulas.
- [x] SIE text rejects control characters and invalid account, date, currency, and voucher-series tokens.
- [x] SIE vouchers are balanced and encode once with strict CP437 handling.
- [x] Export artifacts are content-addressed, private, immutable, and checksum-verified on download.

The synthetic local fixture is `tests/fixtures/sie/approved-packet.se`. It is
test data only and contains no user records. The local structural/CP437 test
passes. Current pre-release SHA-256:
`a481b59eccd23e15fd0ed7afeecd419cd6345952791ccf0fce5e5d986c520f42`.
Regenerate it after setting the final release version; that final checksum
supersedes this pre-release value.

## Manual external gate

- [ ] Upload the final synthetic SIE 4I fixture to the official SIE test service.
- [ ] Record the specification edition, validation date, SHA-256, and result.

This external validation is intentionally open. It must not be marked complete without the real service result.
