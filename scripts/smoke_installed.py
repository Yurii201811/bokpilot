from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen


def request(
    url: str,
    *,
    body: bytes | None = None,
    token: str | None = None,
) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token is not None:
        headers["X-Bokpilot-Token"] = token
    method = "POST" if body is not None else "GET"
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=5) as response:
        return response.status, response.read()


def smoke() -> None:
    from bokpilot.server import make_server
    from bokpilot.store import WorkspaceStore

    with tempfile.TemporaryDirectory() as directory:
        store = WorkspaceStore(Path(directory) / "data" / "bokpilot.sqlite3")
        server = make_server("127.0.0.1", 0, store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base = f"http://{host}:{port}"
        try:
            for path in ("/", "/app.js", "/styles.css"):
                status, payload = request(base + path)
                if status != 200 or not payload:
                    raise RuntimeError(f"Installed asset smoke failed for {path}.")
            status, session_payload = request(base + "/api/session")
            session = json.loads(session_payload.decode("utf-8"))
            if status != 200 or not session.get("token"):
                raise RuntimeError("Installed session-token smoke failed.")
            status, payload = request(
                base + "/api/load-sample",
                body=json.dumps(
                    {"expected_workspace_revision": session["workspace_revision"]}
                ).encode("utf-8"),
                token=session["token"],
            )
            workspace = json.loads(payload.decode("utf-8"))
            if status != 200 or len(workspace["items"]) < 10:
                raise RuntimeError("Installed sample-data smoke failed.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def build_wheel_and_smoke() -> None:
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        wheelhouse = root / "wheelhouse"
        environment = root / "venv"
        wheelhouse.mkdir()
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(project), "--no-deps", "--wheel-dir", str(wheelhouse)],
            check=True,
        )
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        python = environment / "bin" / "python"
        wheel = next(wheelhouse.glob("bokpilot-*.whl"))
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], check=True)
        subprocess.run(
            [str(python), str(Path(__file__).resolve()), "--installed"],
            cwd="/tmp",
            check=True,
        )


def prepare_source_checkout_import() -> None:
    project = Path(__file__).resolve().parents[1]
    if (project / "pyproject.toml").is_file():
        sys.path.insert(0, str(project))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-wheel", action="store_true")
    parser.add_argument("--installed", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if not arguments.installed:
        prepare_source_checkout_import()
    build_wheel_and_smoke() if arguments.build_wheel else smoke()
