import unittest

from bokpilot.parsers import parse_bank_csv, parse_document_text, parse_money


class ParserTest(unittest.TestCase):
    def test_parse_swedish_money_formats(self):
        self.assertEqual(str(parse_money("1 248,75 SEK")), "1248.75")
        self.assertEqual(str(parse_money("-59.00")), "-59.00")

    def test_parse_bank_csv_semicolon_headers(self):
        rows = parse_bank_csv(
            "Datum;Beskrivning;Belopp;Valuta\n"
            "2026-05-02;Fortnox subscription;-249,00;SEK\n"
        )

        self.assertEqual(rows[0]["date"], "2026-05-02")
        self.assertEqual(rows[0]["description"], "Fortnox subscription")
        self.assertEqual(rows[0]["amount"], -249.00)

    def test_parse_receipt_text(self):
        raw = parse_document_text(
            "receipt.txt",
            "Supplier: Pressbyran\nDate: 2026-05-03\nTotal: 129.00\nVAT: 25.80\nDescription: Kontorsmaterial\n",
            "receipt",
        )

        self.assertEqual(raw["counterparty"], "Pressbyran")
        self.assertEqual(raw["amount"], -129.00)
        self.assertEqual(raw["vat_amount"], 25.80)

    def test_parse_customer_invoice_as_income(self):
        raw = parse_document_text(
            "invoice.txt",
            "Customer invoice: 2026-104\nDate: 2026-05-05\nCustomer: Nordic Design Studio\nTotal: 12500\nVAT: 2500\nDescription: Customer invoice paid\n",
            "invoice",
        )

        self.assertEqual(raw["amount"], 12500.00)
        self.assertEqual(raw["counterparty"], "Nordic Design Studio")


if __name__ == "__main__":
    unittest.main()
