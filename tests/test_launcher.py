"""Launcher failures must not initialize application data."""
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def launch(*args):
    return subprocess.run([sys.executable, str(ROOT / "run.py"), *args], capture_output=True, text=True, timeout=15)


def test_launcher_help():
    r = launch("--help")
    assert r.returncode == 0 and "--port" in r.stdout


def test_launcher_rejects_invalid_port():
    r = launch("--port", "70000")
    assert r.returncode != 0 and "between 1 and 65535" in r.stderr


def test_busy_port_exits_before_application_startup():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        r = launch("--port", str(listener.getsockname()[1]))
    assert r.returncode == 1 and "unavailable" in r.stderr
    assert "Application startup" not in r.stderr and "RAN Sentinel ready" not in r.stdout
