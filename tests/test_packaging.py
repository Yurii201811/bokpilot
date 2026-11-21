import tempfile
import threading
import unittest
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from bokpilot.resources import resource_file
from bokpilot import __version__
from bokpilot.server import make_server
from bokpilot.store import WorkspaceStore


class PackagingTest(unittest.TestCase):
    def test_release_version_is_centralized(self):
        self.assertEqual(__version__, "0.2.0")
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceStore(Path(directory) / "bokpilot.sqlite3").load()
        self.assertEqual(workspace["metadata"]["version"], __version__)

    def test_source_smoke_script_runs_from_outside_checkout(self):
        project = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, str(project / "scripts" / "smoke_installed.py")],
            cwd="/tmp",
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_assets_are_inside_package(self):
        root = files("bokpilot").joinpath("resources")
        self.assertTrue(root.joinpath("static", "index.html").is_file())
        self.assertTrue(root.joinpath("static", "app.js").is_file())
        self.assertTrue(root.joinpath("static", "styles.css").is_file())
        self.assertTrue(root.joinpath("samples", "bank", "bank-transactions.csv").is_file())

    def test_resource_file_resolves_packaged_asset(self):
        target = resource_file("static", "index.html")

        self.assertTrue(target.is_file())

    def test_resource_file_rejects_missing_asset(self):
        with self.assertRaisesRegex(FileNotFoundError, "Packaged Bokpilot resource was not found"):
            resource_file("static", "missing.txt")

    def test_server_serves_static_assets_from_package_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory) / "bokpilot.sqlite3")
            server = make_server("127.0.0.1", 0, store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            base = f"http://{host}:{port}"
            try:
                for path, marker in {
                    "/": b"<!doctype html>",
                    "/app.js": b"const state =",
                    "/styles.css": b":root {",
                }.items():
                    with self.subTest(path=path):
                        try:
                            with urlopen(base + path, timeout=5) as response:
                                self.assertEqual(response.status, 200)
                                self.assertIn(marker, response.read())
                        except HTTPError as error:
                            self.fail(f"Static request {path} returned HTTP {error.code}")

                try:
                    with urlopen(base + "/not-allowlisted", timeout=5) as response:
                        self.assertIn(b"<!doctype html>", response.read())
                except HTTPError as error:
                    self.fail(f"Fallback request returned HTTP {error.code}")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
