import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bokpilot.server import make_server
from bokpilot.store import WorkspaceStore


class HttpSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.temporary.name) / "data" / "bokpilot.sqlite3")
        self.server = make_server("127.0.0.1", 0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"
        self.host = f"{host}:{port}"
        with urlopen(self.base + "/api/session", timeout=5) as response:
            self.session = json.loads(response.read())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, *, body=b"{}", headers=None, method="POST"):
        values = dict(headers or {})
        return urlopen(Request(self.base + path, data=body, headers=values, method=method), timeout=5)

    def assert_error(self, expected, *args, **kwargs):
        with self.assertRaises(HTTPError) as raised:
            self.request(*args, **kwargs)
        self.assertEqual(raised.exception.code, expected)
        return json.loads(raised.exception.read())

    def mutation_headers(self):
        return {
            "Content-Type": "application/json",
            "X-Bokpilot-Token": self.session["token"],
        }

    def test_missing_or_wrong_token_is_forbidden(self):
        self.assert_error(403, "/api/reset", headers={"Content-Type": "application/json"})
        self.assert_error(
            403,
            "/api/reset",
            headers={"Content-Type": "application/json", "X-Bokpilot-Token": "wrong"},
        )

    def test_cross_origin_text_plain_is_forbidden_without_mutation(self):
        before = self.store.repository.workspace_revision()
        headers = {
            "Content-Type": "text/plain",
            "X-Bokpilot-Token": self.session["token"],
            "Origin": "https://attacker.example",
        }
        self.assert_error(403, "/api/reset", body=b"RESET", headers=headers)
        self.assertEqual(self.store.repository.workspace_revision(), before)

    def test_non_json_and_oversized_json_are_rejected(self):
        headers = self.mutation_headers()
        headers["Content-Type"] = "text/plain"
        self.assert_error(415, "/api/reset", headers=headers)
        oversized_headers = self.mutation_headers()
        oversized_headers["Content-Length"] = str(14 * 1024 * 1024 + 1)
        self.assert_error(
            413,
            "/api/reset",
            body=b"{}",
            headers=oversized_headers,
        )

    def test_untrusted_host_is_rejected_before_session(self):
        payload = self.assert_error(
            421,
            "/api/session",
            body=None,
            headers={"Host": "attacker.example:8765"},
            method="GET",
        )
        self.assertEqual(payload["error"]["code"], "misdirected_request")

    def test_unknown_api_is_json_404_and_security_headers_are_present(self):
        payload = self.assert_error(404, "/api/not-real", body=None, method="GET")
        self.assertEqual(payload["error"]["code"], "not_found")
        with urlopen(self.base + "/api/workspace", timeout=5) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_internal_errors_are_stable_and_do_not_leak_paths(self):
        original = self.store.load
        self.store.load = lambda: (_ for _ in ()).throw(RuntimeError("/Users/private/data.sqlite3"))
        try:
            payload = self.assert_error(500, "/api/workspace", body=None, method="GET")
        finally:
            self.store.load = original
        rendered = json.dumps(payload)
        self.assertEqual(payload["error"]["code"], "internal_error")
        self.assertNotIn("Users", rendered)
        self.assertNotIn("sqlite3", rendered)

    def test_non_loopback_bind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_server("0.0.0.0", 0, self.store)


if __name__ == "__main__":
    unittest.main()
