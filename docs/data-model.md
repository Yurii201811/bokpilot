# Data model

The workspace is stored as JSON:

```json
{
  "metadata": {
    "project": "Bokpilot",
    "version": "0.1.0",
    "schema_version": 2,
    "locale": "sv-SE",
    "disclaimer": "..."
  },
  "items": [],
  "events": []
}
```

Schema 2 stores accounting money as integer minor units. For SEK, `24900`
means `249.00 SEK`. Binary floats are not used for source amounts, VAT, debit,
or credit values. Bokpilot can read schema-v1 workspaces containing legacy
major-unit `amount`, `vat_amount`, `debit`, and `credit` fields; the next save
upgrades them to schema 2 and does not write those legacy fields again.

## Item

Each imported receipt, invoice, bank row, or manual transaction becomes one item:

```json
{
  "id": "BP-0001",
  "source": "sample_data",
  "raw": {
    "date": "2026-05-02",
    "description": "Fortnox subscription May",
    "counterparty": "Fortnox AB",
    "amount_minor": -24900,
    "currency": "SEK",
    "source_type": "bank_csv",
    "source_filename": "seb-export-june.csv",
    "source_row": 2
  },
  "suggestion": {},
  "status": "needs_review",
  "human_reviewed": false,
  "reviewer_note": "",
  "reviewed_at": null,
  "created_at": "2026-05-16T00:00:00+00:00"
}
```

## Suggestion

```json
{
  "category": "Software and cloud services",
  "bas_account": "5420",
  "bas_account_name": "Programvaror",
  "vat_rate": 25.0,
  "vat_amount_minor": 4980,
  "confidence": 0.88,
  "explanation": "The description looks like a software or cloud service purchase...",
  "journal_lines": [],
  "risk_flags": [],
  "review_required": true
}
```

## Journal line

```json
{
  "account": "5420",
  "account_name": "Programvaror",
  "debit_minor": 19920,
  "credit_minor": 0
}
```

For an expense, Bokpilot usually suggests:

- Debit expense account net of VAT.
- Debit `2641 Ingående moms` when input VAT is present.
- Credit `1930 Företagskonto` with the gross paid amount.

For income, Bokpilot usually suggests:

- Debit `1930 Företagskonto`.
- Credit revenue account net of VAT.
- Credit `2611 Utgående moms` when output VAT is present.

## Status values

- `needs_review`: default state; not exportable.
- `approved`: human accepted the item; exportable.
- `rejected`: human rejected the item; not exportable.

Exports include approved human-reviewed items only.

CSV exports name minor-unit columns explicitly (`amount_minor` and
`vat_amount_minor`). Human-readable SIE-style output renders major units from
the exact integers through `Decimal`, without a float conversion.
