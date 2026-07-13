import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from bokpilot.server import (
    DESTRUCTIVE_CONFIRMATION_HEADER,
    REPLACE_WITH_SAMPLES_CONFIRMATION,
    RESET_CONFIRMATION,
    _binding_warning,
    make_server,
)
from bokpilot.store import WorkspaceStore


class PausingWorkspaceStore(WorkspaceStore):
    def __init__(self, path):
        super().__init__(path)
        self.load_reached = threading.Event()
        self.continue_load = threading.Event()
        self._pause_guard = threading.Lock()
        self._pause_next_load = False

    def pause_after_next_load(self):
        with self._pause_guard:
            self._pause_next_load = True
        self.load_reached.clear()
        self.continue_load.clear()

    def load(self):
        workspace = super().load()
        with self._pause_guard:
            should_pause = self._pause_next_load
            self._pause_next_load = False
        if should_pause:
            self.load_reached.set()
            if not self.continue_load.wait(timeout=2):
                raise TimeoutError("Timed out waiting to resume the destructive mutation test.")
        return workspace


class InstrumentedLock:
    def __init__(self):
        self._lock = threading.Lock()
        self.contender_waiting = threading.Event()

    def __enter__(self):
        if self._lock.acquire(blocking=False):
            return self
        self.contender_waiting.set()
        if not self._lock.acquire(timeout=2):
            raise TimeoutError("Timed out waiting for the mutation lock.")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._lock.release()


class ServerSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = PausingWorkspaceStore(Path(self.tempdir.name) / "workspace.json")
        self.server = make_server("127.0.0.1", 0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def post(self, path, payload, extra_headers=None):
        body = json.dumps(payload)
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        headers.update(extra_headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def test_samples_load_without_confirmation_when_workspace_is_empty(self):
        status, payload = self.post("/api/load-sample", {})

        self.assertEqual(status, 200)
        self.assertGreater(len(payload["items"]), 0)

    def test_samples_require_custom_header_to_replace_existing_workspace(self):
        original = self.store.add_transactions(
            [{"date": "2026-05-02", "description": "My real transaction", "amount": -249}],
            "manual",
        )

        status, payload = self.post(
            "/api/load-sample",
            {"confirmation": REPLACE_WITH_SAMPLES_CONFIRMATION},
            {"Content-Type": "text/plain"},
        )

        self.assertEqual(status, 409)
        self.assertIn("Confirm in the Bokpilot UI", payload["error"])
        self.assertEqual(self.store.load()["items"], original["items"])

        status, payload = self.post(
            "/api/load-sample",
            {},
            {DESTRUCTIVE_CONFIRMATION_HEADER: REPLACE_WITH_SAMPLES_CONFIRMATION},
        )

        self.assertEqual(status, 200)
        self.assertNotEqual(payload["items"][0]["raw"]["description"], "My real transaction")

    def test_reset_requires_custom_header_to_erase_existing_workspace(self):
        original = self.store.add_transactions(
            [{"date": "2026-05-02", "description": "Keep this transaction", "amount": -59}],
            "manual",
        )

        status, payload = self.post(
            "/api/reset",
            {"confirmation": RESET_CONFIRMATION},
            {"Content-Type": "text/plain"},
        )

        self.assertEqual(status, 409)
        self.assertIn("Confirm in the Bokpilot UI", payload["error"])
        self.assertEqual(self.store.load()["items"], original["items"])

        status, payload = self.post(
            "/api/reset",
            {},
            {DESTRUCTIVE_CONFIRMATION_HEADER: RESET_CONFIRMATION},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [])

    def test_all_post_mutations_share_one_lock(self):
        self.store.add_transactions(
            [{"date": "2026-05-02", "description": "Original transaction", "amount": -59}],
            "manual",
        )
        instrumented_lock = InstrumentedLock()
        self.server.RequestHandlerClass.mutation_lock = instrumented_lock
        self.store.pause_after_next_load()
        results = {}
        errors = []

        def call(name, path, payload, headers=None):
            try:
                results[name] = self.post(path, payload, headers)
            except Exception as exc:  # noqa: BLE001 - thread failures are asserted in the parent test.
                errors.append((name, exc))

        reset_thread = threading.Thread(
            target=call,
            args=(
                "reset",
                "/api/reset",
                {},
                {DESTRUCTIVE_CONFIRMATION_HEADER: RESET_CONFIRMATION},
            ),
        )
        import_thread = threading.Thread(
            target=call,
            args=(
                "import",
                "/api/import/manual",
                {"date": "2026-05-03", "description": "Concurrent import", "amount": -125},
            ),
        )

        reset_thread.start()
        import_started = False
        try:
            self.assertTrue(self.store.load_reached.wait(timeout=2), "Reset did not reach its guarded load.")
            import_thread.start()
            import_started = True
            self.assertTrue(
                instrumented_lock.contender_waiting.wait(timeout=2),
                "Concurrent import did not wait on the shared POST mutation lock.",
            )
        finally:
            self.store.continue_load.set()

        reset_thread.join(timeout=2)
        if import_started:
            import_thread.join(timeout=2)
        self.assertFalse(reset_thread.is_alive())
        self.assertFalse(import_started and import_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results["reset"][0], 200)
        self.assertEqual(results["import"][0], 201)
        workspace = self.store.load()
        self.assertEqual([item["raw"]["description"] for item in workspace["items"]], ["Concurrent import"])

    def test_non_loopback_binding_warns_about_missing_authentication(self):
        self.assertIsNone(_binding_warning("127.0.0.1"))
        self.assertIsNone(_binding_warning("::1"))
        warning = _binding_warning("0.0.0.0")

        self.assertIn("no authentication", warning)
        self.assertIn("untrusted network", warning)


if __name__ == "__main__":
    unittest.main()
