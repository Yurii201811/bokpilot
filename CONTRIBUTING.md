# Contributing to Bokpilot

Thanks for helping build a safer open-source pre-accounting assistant for Swedish small businesses.

## Good first contributions

- Add parser fixtures for real-world Swedish bank CSV exports.
- Improve BAS account suggestions with source-backed examples.
- Add VAT edge-case notes and risk flags.
- Improve accessibility and keyboard support in the UI.
- Add export fixtures and validation tests.
- Improve plain-language explanations for beginners.
- Translate selected docs to Swedish.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m bokpilot --port 8765
```

The app uses only the Python standard library for the MVP. Keep dependencies out unless they materially improve the project and are easy for contributors to install.

Before every commit, run this exact sequence:

```bash
python3 -m unittest -v
python3 -m compileall -q bokpilot tests
node --check bokpilot/resources/static/app.js
python3 scripts/smoke_installed.py --build-wheel
git diff --check
```

## Pull request expectations

- Keep changes scoped.
- Add or update tests for parser, rule, export, or review-flow changes.
- Update docs when behavior or safety boundaries change.
- Do not commit real receipts, invoices, personal data, API tokens, or bank files.
- Mark accounting behavior as suggestions unless a qualified source and reviewer have validated the wording.

## Accounting guidance

This project should help humans prepare and understand bookkeeping material. It must not claim to replace professional accounting, tax, legal, or audit review.

High-risk actions such as posting vouchers, filing VAT returns, changing payment details, starting payments, or sending client/tax-authority messages must stay outside the MVP and require explicit future design review.
