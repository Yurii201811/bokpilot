import json
import base64
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bokpilot.server import make_server
from bokpilot.store import WorkspaceStore
from tests.helpers import approved_test_catalog, company_profile


class ServerApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        store = WorkspaceStore(Path(self.temp_dir.name) / "workspace.json")
        self.store = store
        self.server = make_server(
            "127.0.0.1", 0, store, catalog=approved_test_catalog(), profile=company_profile()
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        self.session = self._json_request("/api/session")

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
        self.assertIs(type(workspace["revision"]), int)
        self.assertGreaterEqual(workspace["revision"], 1)
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

        first = workspace["items"][0]
        second = workspace["items"][1]
        approved = self._json_request(
            f"/api/sources/{first_id}/review",
            {
                "status": "approved",
                "nature": "expense",
                "bas_account": first["suggestion"]["bas_account"],
                "vat_rate": str(first["suggestion"]["vat_rate"]),
                "reviewer_note": "Synthetic test approval",
                "risk_acknowledged": True,
                "expected_version": first["version"],
            },
            method="POST",
        )
        self._json_request(
            f"/api/sources/{second_id}/review",
            {
                "status": "rejected",
                "nature": "expense",
                "bas_account": second["suggestion"]["bas_account"],
                "vat_rate": str(second["suggestion"]["vat_rate"]),
                "reviewer_note": "Synthetic test rejection",
                "risk_acknowledged": True,
                "expected_version": second["version"],
            },
            method="POST",
        )

        export_packet = self._text_request("/api/export/json")

        self.assertIn(first_id, export_packet)
        self.assertNotIn(second_id, export_packet)

        current = self._json_request("/api/workspace")
        batch = self._json_request(
            "/api/exports",
            {
                "format": "json",
                "review_ids": [approved["decision_id"]],
                "expected_workspace_revision": current["revision"],
            },
            method="POST",
            expected_status=201,
        )
        with urlopen(f"{self.base_url}/api/exports/{batch['id']}/download", timeout=5) as response:
            downloaded = response.read()
            self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(__import__("hashlib").sha256(downloaded).hexdigest(), batch["sha256"])

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

    def test_preview_commit_and_match_routes(self):
        content = b"Datum;Beskrivning;Belopp\n2026-07-01;Invoice 42;249,00\n"
        preview = self._json_request(
            "/api/imports/preview",
            {
                "kind": "bank_transaction",
                "filename": "bank.csv",
                "media_type": "text/csv; charset=utf-8",
                "content_base64": base64.b64encode(content).decode("ascii"),
                "locale": "sv-SE",
            },
            method="POST",
            expected_status=201,
        )
        loaded = self._json_request(f"/api/imports/{preview['batch_id']}")
        self.assertEqual(loaded["source_sha256"], preview["source_sha256"])
        self.assertFalse(loaded["committed"])

        committed = self._json_request(
            f"/api/imports/{preview['batch_id']}/commit",
            {"expected_workspace_revision": preview["workspace_revision"]},
            method="POST",
        )
        source_id = committed["created_ids"][0]
        self.assertGreater(committed["workspace_revision"], preview["workspace_revision"])
        self.assertEqual(self._json_request(f"/api/sources/{source_id}/matches")["matches"], [])

    def test_source_attachment_route_is_add_only_and_versioned(self):
        workspace = self.store.add_transactions(
            [
                {
                    "date": "2026-07-01",
                    "description": "Manual evidence target",
                    "amount_minor": 10000,
                    "currency": "SEK",
                    "source_type": "manual",
                    "source_filename": "manual-entry",
                    "evidence_status": "manual_attested",
                    "extracted": {"manual_attestation": "Signed cash log"},
                }
            ],
            "manual",
        )
        source_id = workspace["items"][0]["id"]
        payload = {
            "filename": "receipt.txt",
            "media_type": "text/plain",
            "content_base64": base64.b64encode(b"original evidence").decode("ascii"),
            "expected_version": 1,
        }

        attached = self._json_request(
            f"/api/sources/{source_id}/attachment", payload, method="POST", expected_status=201
        )
        self.assertEqual(attached["source_version"], 2)
        with self.assertRaises(HTTPError) as raised:
            self._json_request(
                f"/api/sources/{source_id}/attachment",
                {**payload, "expected_version": 2},
                method="POST",
                expected_status=201,
            )
        self.assertEqual(raised.exception.code, 400)

    def test_sample_load_refuses_nonempty_workspace(self):
        workspace = self._json_request(
            "/api/load-sample",
            {"expected_workspace_revision": self.session["workspace_revision"]},
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            self._json_request(
                "/api/load-sample",
                {"expected_workspace_revision": workspace["revision"]},
                method="POST",
            )
        payload = json.loads(raised.exception.read())
        self.assertEqual(raised.exception.code, 409)
        self.assertEqual(payload["error"]["code"], "workspace_not_empty")

    def test_reset_requires_confirmation_and_creates_verified_backup(self):
        workspace = self._json_request(
            "/api/load-sample",
            {"expected_workspace_revision": self.session["workspace_revision"]},
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            self._json_request(
                "/api/reset",
                {"confirmation": "no", "expected_revision": workspace["revision"]},
                method="POST",
            )
        self.assertEqual(raised.exception.code, 400)

        reset = self._json_request(
            "/api/reset",
            {"confirmation": "RESET", "expected_revision": workspace["revision"]},
            method="POST",
        )
        self.assertEqual(reset["items"], [])
        self.assertEqual(len(reset["backup"]["sha256"]), 64)
        self.assertTrue(Path(reset["backup"]["path"]).is_file())

    def _json_request(self, path, payload=None, method="GET", expected_status=200):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if method != "GET":
            headers["X-Bokpilot-Token"] = self.session["token"]
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
