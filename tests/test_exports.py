import json
import tempfile
import unittest
from pathlib import Path

from bokpilot.exports import create_csv_batch, create_json_batch, read_export_batch
from bokpilot.repository import Repository
from bokpilot.review import record_review
from bokpilot.domain import ReviewDecision, TransactionNature, VatTreatment
from tests.helpers import approved_test_catalog, company_profile, source_record


class ExportBatchTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temporary.name) / "data" / "bokpilot.sqlite3")
        record = source_record("=HYPERLINK(\"bad\")\nsecond line", -12500)
        record = record.__class__(**{**record.__dict__, "extracted": {"document_text": "PRIVATE RAW", "local_path": "/secret/file"}})
        self.repository.import_sources([record])
        result = record_review(
            self.repository,
            record.id,
            action="approved",
            decision=ReviewDecision(
                TransactionNature.EXPENSE,
                "5420",
                VatTreatment.RATE_25,
                None,
                "Synthetic approval",
                True,
            ),
            profile=company_profile(),
            catalog=approved_test_catalog(),
            expected_version=1,
        )
        self.review_id = result.decision_id

    def tearDown(self):
        self.temporary.cleanup()

    def test_json_is_share_safe_and_download_is_immutable(self):
        batch = create_json_batch(self.repository, [self.review_id])
        content = read_export_batch(self.repository, batch.id)
        payload = json.loads(content)
        rendered = content.decode("utf-8")

        self.assertEqual(payload["schema_version"], 2)
        self.assertNotIn("PRIVATE RAW", rendered)
        self.assertNotIn("/secret/file", rendered)
        self.assertNotIn("document_text", rendered)
        self.assertEqual(content, read_export_batch(self.repository, batch.id))
        self.assertEqual(batch.sha256, __import__("hashlib").sha256(content).hexdigest())

    def test_csv_neutralizes_formula_text_but_keeps_numeric_amount(self):
        batch = create_csv_batch(self.repository, [self.review_id])
        text = read_export_batch(self.repository, batch.id).decode("utf-8")

        self.assertIn("'=HYPERLINK", text)
        self.assertIn("-125.00", text)
        self.assertNotIn(",=HYPERLINK", text)


if __name__ == "__main__":
    unittest.main()
