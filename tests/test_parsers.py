import unittest
from datetime import date

from bokpilot.parsers import (
    manual_transaction,
    parse_bank_csv,
    parse_date_exact,
    parse_document_text,
    parse_money,
    parse_money_exact,
)


class ParserTest(unittest.TestCase):
    def test_public_parser_boundary_returns_exact_types(self):
        from bokpilot.parsers import parse_date

        self.assertEqual(parse_money("1 248,75 SEK", "sv-SE").minor, 124875)
        self.assertEqual(parse_date("2026-05-02"), date(2026, 5, 2))
        with self.assertRaises(TypeError):
            parse_money(12.5, "plain")

    def test_parser_outputs_schema_v2_minor_fields(self):
        rows = parse_bank_csv("Datum;Beskrivning;Belopp\n2026-05-02;Fortnox subscription;-249,00\n")

        self.assertEqual(rows[0]["amount_minor"], -24900)
        self.assertIs(type(rows[0]["amount_minor"]), int)
        self.assertNotIn("amount", rows[0])
        self.assertEqual(rows[0]["date"], "2026-05-02")

    def test_parser_boundaries_reject_missing_or_invalid_dates(self):
        with self.assertRaisesRegex(ValueError, "date"):
            parse_bank_csv("Datum;Beskrivning;Belopp\n2026-99-99;Invalid date;-249,00\n")
        with self.assertRaisesRegex(ValueError, "date"):
            parse_document_text("receipt.txt", "Supplier: Demo AB\nTotal: 100.00", "receipt")
        with self.assertRaisesRegex(ValueError, "date"):
            manual_transaction({"description": "Manual", "amount": "100.00"})

    def test_manual_entries_require_and_preserve_attestation(self):
        with self.assertRaisesRegex(ValueError, "attestation"):
            manual_transaction({"date": "2026-07-01", "amount": "100.00"})
        value = manual_transaction(
            {
                "date": "2026-07-01",
                "amount": "100.00",
                "reviewer_note": "Matched to the signed cash log.",
            }
        )
        self.assertEqual(value["evidence_status"], "manual_attested")
        self.assertEqual(value["extracted"]["manual_attestation"], "Matched to the signed cash log.")

    def test_parse_money_exact_supports_locale_specific_formats(self):
        self.assertEqual(parse_money_exact("1 248,75 SEK", "sv-SE").minor, 124875)
        self.assertEqual(parse_money_exact("1,248.75", "en-US").minor, 124875)
        self.assertEqual(parse_money_exact("(1 248,75 SEK)", "sv-SE").minor, -124875)

    def test_parse_money_exact_rejects_ambiguous_auto_format(self):
        with self.assertRaisesRegex(ValueError, "Ambiguous money format; choose the source locale"):
            parse_money_exact("1,234", "auto")

    def test_parse_money_exact_rejects_malformed_text(self):
        with self.assertRaises(ValueError):
            parse_money_exact("abc123xyz", "sv-SE")

    def test_parse_money_exact_rejects_sub_minor_precision(self):
        with self.assertRaisesRegex(ValueError, "at most two decimal places"):
            parse_money_exact("12.3456", "en-US")

    def test_parse_money_exact_rejects_trailing_zero_sub_minor_precision(self):
        for value, locale in (("12.340", "en-US"), ("12,340", "sv-SE"), ("12.340", "plain")):
            with self.subTest(value=value, locale=locale), self.assertRaisesRegex(
                ValueError, "at most two decimal places"
            ):
                parse_money_exact(value, locale)

    def test_parse_date_exact_supports_documented_layouts(self):
        for value in ("2026-05-02", "2026/05/02", "20260502", "02/05/2026", "02.05.2026", "02-05-2026"):
            with self.subTest(value=value):
                self.assertEqual(parse_date_exact(value), date(2026, 5, 2))

    def test_parse_date_exact_rejects_invalid_or_missing_dates(self):
        for value in ("2026-99-99", "", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_date_exact(value)

    def test_parse_swedish_money_formats(self):
        self.assertEqual(parse_money("1 248,75 SEK").minor, 124875)
        self.assertEqual(parse_money("-59.00").minor, -5900)
        self.assertEqual(parse_money("(1 248,75 SEK)").minor, -124875)

    def test_parse_bank_csv_semicolon_headers(self):
        rows = parse_bank_csv(
            "Datum;Beskrivning;Belopp;Valuta\n"
            "2026-05-02;Fortnox subscription;-249,00;SEK\n"
            "\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-05-02")
        self.assertEqual(rows[0]["description"], "Fortnox subscription")
        self.assertEqual(rows[0]["amount_minor"], -24900)

    def test_parse_bank_csv_accepts_explicit_source_locales(self):
        cases = (
            ("sv-SE", "Datum;Beskrivning;Belopp;Valuta\n2026-05-02;Swedish grouped;12.340;SEK\n"),
            ("en-US", "Date;Description;Amount;Currency\n2026-05-02;English grouped;12,340;SEK\n"),
        )
        for locale, content in cases:
            with self.subTest(locale=locale):
                rows = parse_bank_csv(content, locale=locale)
                self.assertEqual(rows[0]["amount_minor"], 1234000)

    def test_parse_bank_csv_auto_locale_keeps_grouped_values_ambiguous(self):
        for value in ("12.340", "12,340"):
            content = f"Datum;Beskrivning;Belopp;Valuta\n2026-05-02;Ambiguous;{value};SEK\n"
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "Ambiguous money format; choose the source locale"
            ):
                parse_bank_csv(content)

    def test_parse_bank_csv_preserves_source_filename_and_row(self):
        rows = parse_bank_csv(
            "Datum;Beskrivning;Belopp\n"
            "2026-05-02;Fortnox subscription;-249,00\n"
            "2026-05-05;Customer invoice paid;12500,00\n",
            "seb-export-june.csv",
        )

        self.assertEqual(rows[0]["source_filename"], "seb-export-june.csv")
        self.assertEqual(rows[0]["source_row"], 2)
        self.assertEqual(rows[1]["source_row"], 3)

    def test_parse_bank_csv_swedish_diacritic_headers(self):
        rows = parse_bank_csv(
            "Bokföringsdag;Text;Belopp;Valuta\n"
            "2026-05-02;Fortnox subscription;-249,00;SEK\n"
        )

        self.assertEqual(rows[0]["date"], "2026-05-02")
        self.assertEqual(rows[0]["description"], "Fortnox subscription")
        self.assertEqual(rows[0]["amount_minor"], -24900)

    def test_parse_bank_csv_common_swedish_bank_aliases(self):
        rows = parse_bank_csv(
            "Bokföringsdatum;Meddelande;Belopp SEK;Valuta\n"
            "20260502;Bankavgift företagskonto;(59,00 SEK);SEK\n",
            "bank-export.csv",
        )

        self.assertEqual(rows[0]["date"], "2026-05-02")
        self.assertEqual(rows[0]["description"], "Bankavgift företagskonto")
        self.assertEqual(rows[0]["amount_minor"], -5900)
        self.assertEqual(rows[0]["source_filename"], "bank-export.csv")

    def test_parse_bank_csv_debit_credit_columns(self):
        rows = parse_bank_csv(
            "Bokföringsdag;Text;Debet;Kredit;Valuta\n"
            "2026-05-02;Fortnox subscription;249,00;;SEK\n"
            "2026-05-05;Customer invoice paid;;12500,00;SEK\n"
        )

        self.assertEqual(rows[0]["amount_minor"], -24900)
        self.assertEqual(rows[1]["amount_minor"], 1250000)

    def test_parse_bank_csv_in_out_columns(self):
        rows = parse_bank_csv(
            "Datum;Beskrivning;Ut;In\n"
            "2026-05-02;Fortnox subscription;249,00;\n"
            "2026-05-05;Customer invoice paid;;12500,00\n"
        )

        self.assertEqual(rows[0]["amount_minor"], -24900)
        self.assertEqual(rows[1]["amount_minor"], 1250000)

    def test_parse_receipt_text(self):
        raw = parse_document_text(
            "receipt.txt",
            "Supplier: Pressbyran\nDate: 2026-05-03\nTotal: 129.00\nVAT: 25.80\nDescription: Kontorsmaterial\n",
            "receipt",
        )

        self.assertEqual(raw["counterparty"], "Pressbyran")
        self.assertEqual(raw["amount_minor"], -12900)
        self.assertEqual(raw["vat_amount_minor"], 2580)

    def test_parse_customer_invoice_as_income(self):
        raw = parse_document_text(
            "invoice.txt",
            "Customer invoice: 2026-104\nDate: 2026-05-05\nCustomer: Nordic Design Studio\nTotal: 12500\nVAT: 2500\nDescription: Customer invoice paid\n",
            "invoice",
        )

        self.assertEqual(raw["amount_minor"], 1250000)
        self.assertEqual(raw["counterparty"], "Nordic Design Studio")


if __name__ == "__main__":
    unittest.main()
