import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from bokpilot.exports import approved_items, export_csv, export_json, export_sie_style, export_summary
from bokpilot.sample_data import load_sample_transactions
from bokpilot.store import WorkspaceStore


class StoreExportTest(unittest.TestCase):
    def test_store_is_sqlite_backed_and_exposes_monotonic_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "bokpilot.sqlite3"
            store = WorkspaceStore(path)
            initial = store.load()
            imported = store.add_transactions(
                [{"date": "2026-05-02", "description": "Revision", "amount": -100}],
                "test",
            )
            reviewed = store.review_item(imported["items"][0]["id"], {"status": "approved"})

            self.assertEqual(initial["revision"], 0)
            self.assertEqual(imported["revision"], 1)
            self.assertEqual(reviewed["revision"], 2)
            self.assertEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            with self.assertRaisesRegex(ValueError, "revision"):
                store.save(imported, expected_revision=1)

    def test_exports_use_explicit_minor_units_and_exact_sie_amounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp) / "workspace.json")
            workspace = store.add_transactions(
                [{"date": "2026-05-02", "description": "Fortnox subscription", "amount": -249}],
                "test",
            )
            item_id = workspace["items"][0]["id"]
            store.review_item(item_id, {"status": "approved"})
            workspace = store.load()

        csv_rows = list(csv.DictReader(io.StringIO(export_csv(workspace))))
        json_packet = json.loads(export_json(workspace))
        self.assertEqual(json_packet["metadata"]["schema_version"], 2)
        self.assertEqual(csv_rows[0]["amount_minor"], "-24900")
        self.assertEqual(csv_rows[0]["vat_amount_minor"], "4980")
        self.assertNotIn("amount", csv_rows[0])
        sie = export_sie_style(workspace)
        self.assertIn("#TRANS 5420 {} 199.20", sie)
        self.assertIn("#TRANS 2641 {} 49.80", sie)
        self.assertIn("#TRANS 1930 {} -249.00", sie)

    def test_duplicate_detection_uses_exact_minor_amount_and_normalized_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            amount_store = WorkspaceStore(Path(tmp) / "amount-workspace.json")
            amount_store.add_transactions(
                [{"date": "2026-05-02", "description": "Demo Vendor", "amount_minor": -100}],
                "test",
            )
            different_amount = amount_store.add_transactions(
                [{"date": "2026-05-02", "description": "Demo Vendor", "amount_minor": -101}],
                "test",
            )
            description_store = WorkspaceStore(Path(tmp) / "description-workspace.json")
            description_store.add_transactions(
                [{"date": "2026-05-02", "description": "  Demo   Vendor ", "amount_minor": -100}],
                "test",
            )
            exact_duplicate = description_store.add_transactions(
                [{"date": "2026-05-02", "description": "demo vendor", "amount_minor": -100}],
                "test",
            )

        self.assertNotIn("Possible duplicate", " ".join(different_amount["items"][-1]["suggestion"]["risk_flags"]))
        self.assertIn("Possible duplicate", " ".join(exact_duplicate["items"][-1]["suggestion"]["risk_flags"]))

    def test_exports_include_only_human_approved_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp) / "workspace.json")
            workspace = store.add_transactions(
                [
                    {
                        "date": "2026-05-02",
                        "description": "Fortnox subscription",
                        "amount": -249,
                        "source_type": "bank_csv",
                        "source_filename": "bank.csv",
                        "source_row": 2,
                    },
                    {"date": "2026-05-06", "description": "Bankavgift", "amount": -59},
                ],
                "test",
            )
            first_id = workspace["items"][0]["id"]
            store.review_item(first_id, {"status": "approved", "reviewer_note": "Looks correct"})
            workspace = store.load()

            self.assertEqual(len(approved_items(workspace)), 1)
            self.assertEqual(export_summary(workspace)["export_ready"], 1)
            json_packet = json.loads(export_json(workspace))
            self.assertEqual(json_packet["items"][0]["id"], first_id)
            csv_packet = export_csv(workspace)
            csv_rows = list(csv.DictReader(io.StringIO(csv_packet)))
            self.assertEqual(csv_rows[0]["source_type"], "bank_csv")
            self.assertEqual(csv_rows[0]["source_filename"], "bank.csv")
            self.assertEqual(csv_rows[0]["source_row"], "2")
            self.assertNotIn("BP-0002", csv_packet)
            self.assertIn("#VER", export_sie_style(workspace))

    def test_approving_unchanged_item_does_not_create_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp) / "workspace.json")
            workspace = store.add_transactions(
                [{"date": "2026-05-02", "description": "Fortnox subscription", "amount": -249}],
                "test",
            )
            first = workspace["items"][0]
            store.review_item(
                first["id"],
                {
                    "status": "approved",
                    "bas_account": first["suggestion"]["bas_account"],
                    "vat_rate": first["suggestion"]["vat_rate"],
                },
            )
            approved = store.load()["items"][0]

            self.assertEqual(approved["suggestion"]["category"], "Software and cloud services")
            self.assertEqual(approved["suggestion"]["confidence"], 0.88)

    def test_rejected_items_are_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp) / "workspace.json")
            workspace = store.add_transactions(
                [{"date": "2026-05-02", "description": "Fortnox subscription", "amount": -249}],
                "test",
            )
            first_id = workspace["items"][0]["id"]
            store.review_item(first_id, {"status": "rejected", "reviewer_note": "Duplicate"})
            workspace = store.load()

            self.assertEqual(approved_items(workspace), [])
            self.assertEqual(export_summary(workspace)["export_ready"], 0)

    def test_sample_data_imports_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp) / "workspace.json")
            workspace = store.add_transactions(load_sample_transactions(), "sample_data")

            self.assertGreaterEqual(len(workspace["items"]), 10)
            self.assertTrue(all(isinstance(item["suggestion"]["risk_flags"], list) for item in workspace["items"]))


if __name__ == "__main__":
    unittest.main()
