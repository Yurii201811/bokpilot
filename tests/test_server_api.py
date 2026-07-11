import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bokpilot.server import make_server
from bokpilot.store import WorkspaceStore


class ServerApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        store = WorkspaceStore(Path(self.temp_dir.name) / "workspace.json")
        self.server = make_server("127.0.0.1", 0, store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def test_import_bank_csv_route_returns_workspace_summary(self):
        payload = {
            "filename": "bank.csv",
            "content": (
                "Bokföringsdag;Text;Debet;Kredit;Valuta\n"
                "2026-05-02;Fortnox subscription;249,00;;SEK\n"
                "2026-05-05;Customer invoice paid;;12500,00;SEK\n"
            ),
        }

        workspace = self._json_request("/api/import/bank-csv", payload, method="POST", expected_status=201)

        self.assertEqual(workspace["summary"]["total_items"], 2)
        self.assertEqual(workspace["summary"]["needs_review"], 2)
        self.assertEqual(workspace["metadata"]["schema_version"], 2)
        self.assertEqual(workspace["items"][0]["raw"]["amount_minor"], -24900)
        self.assertIs(type(workspace["items"][0]["raw"]["amount_minor"]), int)
        self.assertNotIn("amount", workspace["items"][0]["raw"])
        self.assertEqual(workspace["items"][0]["raw"]["source_filename"], "bank.csv")
        self.assertEqual(workspace["items"][0]["raw"]["source_row"], 2)
        self.assertEqual(workspace["items"][1]["raw"]["amount_minor"], 1250000)
        suggestion = workspace["items"][0]["suggestion"]
        self.assertIs(type(suggestion["vat_amount_minor"]), int)
        self.assertNotIn("vat_amount", suggestion)
        for line in suggestion["journal_lines"]:
            self.assertIs(type(line["debit_minor"]), int)
            self.assertIs(type(line["credit_minor"]), int)
            self.assertNotIn("debit", line)
            self.assertNotIn("credit", line)

    def test_export_routes_include_only_approved_items(self):
        workspace = self._json_request(
            "/api/import/bank-csv",
            {
                "filename": "bank.csv",
                "content": (
                    "Datum;Beskrivning;Belopp\n"
                    "2026-05-02;Fortnox subscription;-249,00\n"
                    "2026-05-06;Bankavgift;-59,00\n"
                ),
            },
            method="POST",
            expected_status=201,
        )
        first_id = workspace["items"][0]["id"]
        second_id = workspace["items"][1]["id"]

        self._json_request(f"/api/items/{first_id}/review", {"status": "approved"}, method="POST")
        self._json_request(f"/api/items/{second_id}/review", {"status": "rejected"}, method="POST")

        export_packet = self._text_request("/api/export/json")

        self.assertIn(first_id, export_packet)
        self.assertNotIn(second_id, export_packet)

    def test_import_bank_csv_route_propagates_explicit_locale(self):
        workspace = self._json_request(
            "/api/import/bank-csv",
            {
                "filename": "swedish-bank.csv",
                "locale": "sv-SE",
                "content": "Datum;Beskrivning;Belopp;Valuta\n2026-05-02;Grouped amount;12.340;SEK\n",
            },
            method="POST",
            expected_status=201,
        )

        self.assertEqual(workspace["items"][0]["raw"]["amount_minor"], 1234000)

    def test_import_routes_reject_missing_dates(self):
        cases = (
            ("/api/import/document", {"filename": "receipt.txt", "kind": "receipt", "content": "Total: 100.00"}),
            ("/api/import/manual", {"description": "Manual", "amount": "100.00"}),
        )
        for path, payload in cases:
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as raised:
                    self._json_request(path, payload, method="POST", expected_status=201)
                self.assertEqual(raised.exception.code, 400)

    def _json_request(self, path, payload=None, method="GET", expected_status=200):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, expected_status)
            return json.loads(response.read().decode("utf-8"))

    def _text_request(self, path):
        with urlopen(f"{self.base_url}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode("utf-8")


if __name__ == "__main__":
    unittest.main()
