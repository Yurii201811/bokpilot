# Launch checklist

Use this before publishing the repository.

## Product

- [x] Clear project name and tagline.
- [x] README explains the mission and safety boundary.
- [x] MVP works without paid APIs.
- [x] Sample Swedish scenarios are included.
- [x] Human review is required before export.
- [x] Limitations are documented honestly.

## Engineering

- [x] App runs with `python3 -m bokpilot --port 8765`.
- [x] Tests run with `python3 -m unittest`.
- [x] No external service required for the demo.
- [x] Local workspace path can be overridden.
- [x] Export includes only approved human-reviewed items.
- [x] Error handling returns JSON for API failures.

## Open source

- [x] MIT license.
- [x] Contributing guide.
- [x] Code of conduct.
- [x] Security policy.
- [x] Documentation folder.
- [x] Sample data and export examples.

## Before wider promotion

- [x] Add screenshots captured from the running app.
- [x] Add synthetic SIE validator fixtures and strict local parser coverage.
- [ ] Ask a Swedish accountant/bookkeeper to review sample mappings and wording.
- [ ] Add more BAS 2026 account coverage.
- [x] Add privacy and integrity controls for local document attachment handling.

## v0.2 release status

**Blocked.** Automated engineering gates are green, but release readiness is
not complete until both manual gates in `docs/release-checklist.md` have real
evidence: named/date-qualified accounting review and official SIE test-service
validation of the final synthetic fixture.
