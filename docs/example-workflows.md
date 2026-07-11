# Example workflows

## Create a review packet download

After approving items, choose JSON, CSV, or SIE 4I. Bokpilot creates one
immutable local artifact, displays its SHA-256, and downloads those exact
verified bytes. JSON and CSV are privacy-safe review packets; SIE 4I uses the
configured company profile and must still pass the release validation gate
before production use.

## Freelancer monthly packet

1. Export bank transactions from the business bank account as CSV.
2. Import the CSV into Bokpilot.
3. Import receipt text files from `samples/receipts` or your own simple text documents.
4. Review each item:
   - Check date and amount.
   - Check whether the counterparty is correct.
   - Read the BAS/VAT explanation.
   - Inspect risk flags.
   - Override BAS account or VAT rate when needed.
5. Approve items that are ready for the accountant.
6. Export JSON or CSV as a review packet.
7. Use the SIE-style draft only for inspection until proper SIE validation is added.

## Accountant cleanup queue

1. Ask the client for a bank CSV and receipt bundle.
2. Load the material into a local Bokpilot workspace.
3. Filter low-confidence items and risk flags first.
4. Add reviewer notes for missing receipts, unclear business purpose, representation, private use, or asset questions.
5. Export a CSV summary for the client and a JSON packet for internal review.

## Immigrant entrepreneur learning flow

1. Load sample data.
2. Open the Fortnox subscription row and inspect how gross amount, VAT, and BAS lines split.
3. Open the customer invoice row and compare input VAT versus output VAT.
4. Open meal, travel, and fuel examples to see why some transactions remain riskier.
5. Read the Learn section and docs before using the same pattern on real material.

## What not to do

- Do not treat approval as a legal guarantee.
- Do not upload sensitive documents to third-party AI services without consent.
- Do not post SIE-style output to production bookkeeping without validation.
- Do not use Bokpilot to file VAT returns or start payments.
