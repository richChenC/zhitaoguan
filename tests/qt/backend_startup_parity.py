"""Compare source and bundled backends using fresh isolated databases."""
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(os.environ["THIMBLE_QT_TEST_DATA_ROOT"]).resolve()
CREDS = {"username": "parityadmin", "display_name": "parityadmin", "password": "testpass123"}


def run(name, command):
    root = BASE / name
    root.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update({
        "THIMBLE_USER_DATA_DIR": str(root),
        "THIMBLE_DATA_DIR": str(root / "data"),
        "THIMBLE_DB_PATH": str(root / "data" / "thimble.db"),
        "THIMBLE_OUTPUT_DIR": str(root / "output"),
        "THIMBLE_REPORT_DIR": str(root / "reports"),
        "THIMBLE_LOG_PATH": str(root / "server.log"),
        "THIMBLE_PORT": str(port),
        "THIMBLE_DESKTOP_INSTANCE": name,
        "PYTHONPATH": str(ROOT / ".vendor"),
    })
    env.pop("THIMBLE_MIGRATE_LEGACY", None)
    env.pop("THIMBLE_LEGACY_DATA_DIRS", None)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f"http://127.0.0.1:{port}"

    def request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers={
            "Content-Type": "application/json", "X-Thimble-Request": "1",
        })
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    started = time.monotonic()
    proc = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        while True:
            if time.monotonic() - started > 40 or proc.poll() is not None:
                raise RuntimeError(f"{name} backend failed to start")
            try:
                status, payload = request("/api/health")
                if status == 200 and json.loads(payload)["desktop_instance"] == name:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        elapsed = round(time.monotonic() - started, 2)
        assert request("/api/auth/setup", CREDS)[0] == 200
        assert request("/api/auth/login", CREDS)[0] == 200
        results = {}
        for route in ["/api/auth/status", "/api/backup-policy",
                      "/api/findings", "/api/data-quality", "/api/import-batches",
                      "/api/analytics/bases", "/login.html", "/login.js", "/app.js"]:
            code, body = request(route)
            results[route] = (code, body)
        return elapsed, results
    finally:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    executable = Path(os.environ.get("THIMBLE_PARITY_EXE", ROOT / "build" / "backend" / "thimble-backend.exe"))
    bundled_time, bundled = run("bundled", [str(executable)])
    source_time, source = run("source", [sys.executable, str(ROOT / "src" / "backend" / "server.py")])
    differences = [route for route in bundled if bundled[route] != source[route]]
    print(json.dumps({"bundled_seconds": bundled_time, "source_seconds": source_time,
                      "routes": len(bundled), "differences": differences}, ensure_ascii=False))
    if differences:
        raise SystemExit(1)
