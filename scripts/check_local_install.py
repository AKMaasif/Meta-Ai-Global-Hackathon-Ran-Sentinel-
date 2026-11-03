"""Offline install smoke check in a temporary copy, using no keys or existing DB."""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="ran-sentinel-install-") as folder:
        temp = Path(folder)
        for name in ("backend", "frontend"):
            shutil.copytree(ROOT / name, temp / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "run.py", temp / "run.py")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = dict(os.environ, MODEL_API_KEY="", GOOGLE_API_KEY="", FIREWORKS_API_KEY="", MAVERIC_URL="",
                   SIM_TICK_SECONDS="0.5", OPS_EMAIL="ops@northstar.demo", OPS_PASSWORD="sentinel-demo",
                   CUSTOMER_EMAIL="customer@northstar.demo", CUSTOMER_PASSWORD="connect-demo", PYTHONIOENCODING="utf-8")
        base = f"http://127.0.0.1:{port}"
        with (temp / "server.log").open("w+", encoding="utf-8") as log:
            proc = subprocess.Popen([sys.executable, str(temp / "run.py"), "--port", str(port)], cwd=temp,
                                    env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                with httpx.Client(base_url=base, timeout=15) as ops, httpx.Client(base_url=base, timeout=15) as customer:
                    until = time.monotonic() + 90
                    while True:
                        if proc.poll() is not None:
                            raise RuntimeError("Server exited before startup")
                        try:
                            if ops.get("/ops/").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        if time.monotonic() > until:
                            raise RuntimeError("Server did not become ready within 90 seconds")
                        time.sleep(.5)
                    for url in ("/ops/", "/connect/", "/ops/app.js", "/connect/app.js", "/shared/ui.js",
                                "/shared/base.css", "/shared/geomap.js", "/shared/vendor/leaflet/leaflet.js",
                                "/shared/vendor/us-states-10m.json"):
                        r = ops.get(url)
                        assert r.status_code == 200 and r.content, url
                    print("PASS: both portals and bundled static assets")
                    assert ops.get("/api/state").status_code == 401
                    for client, portal, email, pw in ((ops, "ops", "ops@northstar.demo", "sentinel-demo"),
                                                     (customer, "connect", "customer@northstar.demo", "connect-demo")):
                        r = client.post("/api/login", json={"portal": portal, "email": email, "password": pw})
                        assert r.status_code == 200, (portal, r.text)
                    state = ops.get("/api/state").json()
                    assert state["offline"] and len(state["cells"]) == 36
                    assert customer.get("/api/state").status_code == 401
                    for url in ("/api/care/home", "/api/care/network", "/api/care/account", "/api/care/map", "/api/care/signal"):
                        assert customer.get(url).status_code == 200, url
                    print("PASS: default logins, offline mode, 36 cells and customer access boundary")
                    before = state["tick"]
                    assert ops.post("/api/demo/inject", json={"cell_id": "SEA-RAN-001", "fault_type": "hardware", "severity": 2}).status_code == 200
                    until = time.monotonic() + 60
                    while time.monotonic() < until:
                        state = ops.get("/api/state").json()
                        if state["incidents"] and ops.get("/api/tickets").json():
                            break
                        time.sleep(.5)
                    else:
                        raise RuntimeError("Offline incident did not reach the ticket queue")
                    assert state["tick"] > before
                    print("PASS: live telemetry, offline fault investigation and department ticket")
                    print("Local install smoke check passed. No external model requests were made.")
                return 0
            except Exception as exc:
                print(f"FAIL: {exc}", file=sys.stderr)
                log.flush()
                print((temp / "server.log").read_text(encoding="utf-8")[-5000:], file=sys.stderr)
                return 1
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
