import tempfile
import unittest
from pathlib import Path

from bokpilot.accounts import AccountCatalog
from tests.helpers import approved_test_catalog


class AccountCatalogTest(unittest.TestCase):
    def test_synthetic_fixture_exposes_only_approved_accounts(self):
        catalog = approved_test_catalog()

        self.assertEqual(catalog.get("1930").name, "Synthetic bank account")
        self.assertIsNone(catalog.get("NOT-BAS"))
        self.assertIsNone(catalog.get("9999"))

    def test_production_catalog_defaults_to_pending_review(self):
        catalog = AccountCatalog.production_default()

        self.assertIsNone(catalog.get("1930"))
        self.assertIn("1930", catalog)
        self.assertEqual(catalog.entry("1930").evidence_status, "pending_review")
        self.assertIn("1930", catalog.pending_codes())
        self.assertEqual(tuple(sorted(entry.code for entry in catalog.entries())), tuple(entry.code for entry in catalog.entries()))

    def test_incomplete_approved_evidence_is_rejected(self):
        payload = (
            '{"accounts":[{"code":"1930","name":"Bank","source_url":"",'
            '"evidence_status":"approved","reviewer":"","review_date":null}]}'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(payload, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "(?i)approved account evidence"):
                AccountCatalog.from_json_file(path)


if __name__ == "__main__":
    unittest.main()
