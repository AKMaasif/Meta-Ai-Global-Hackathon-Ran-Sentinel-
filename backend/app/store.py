from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, cell_id TEXT, kind TEXT, status TEXT,
  severity TEXT, created TEXT, updated TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS ledger (seq INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, wall_ts TEXT,
  sim_ts TEXT, actor TEXT, event TEXT, summary TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS tickets (id TEXT PRIMARY KEY, incident_id TEXT, department TEXT, status TEXT,
  created TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS customer_updates (seq INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT,
  area TEXT, status TEXT, text TEXT, published TEXT);
"""


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def reset(self) -> None:
        with self.lock:
            for t in ("incidents", "ledger", "tickets", "customer_updates"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.commit()

    def save_incident(self, inc: dict) -> None:
        inc["updated"] = _now()
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?)",
                (inc["id"], inc["cell_id"], inc["kind"], inc["status"], inc.get("severity", ""),
                 inc["created"], inc["updated"], json.dumps(inc, default=str)),
            )
            self.db.commit()

    def get_incident(self, iid: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT data FROM incidents WHERE id=?", (iid,)).fetchone()
        return json.loads(r["data"]) if r else None

    def list_incidents(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM incidents ORDER BY created DESC").fetchall()
        return [json.loads(r["data"]) for r in rows]

    def count_incidents(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    def log(self, incident_id: str, sim_ts: str, actor: str, event: str, summary: str, payload: dict | None = None) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO ledger (incident_id, wall_ts, sim_ts, actor, event, summary, payload) VALUES (?,?,?,?,?,?,?)",
                (incident_id, _now(), sim_ts, actor, event, summary, json.dumps(payload or {}, default=str)),
            )
            self.db.commit()

    def ledger(self, incident_id: str | None = None, limit: int = 200) -> list[dict]:
        with self.lock:
            if incident_id:
                rows = self.db.execute("SELECT * FROM ledger WHERE incident_id=? ORDER BY seq", (incident_id,)).fetchall()
            else:
                rows = self.db.execute("SELECT * FROM ledger ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def save_ticket(self, t: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO tickets VALUES (?,?,?,?,?,?)",
                            (t["id"], t["incident_id"], t["department"], t["status"], t["created"], json.dumps(t, default=str)))
            self.db.commit()

    def get_ticket(self, tid: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT data FROM tickets WHERE id=?", (tid,)).fetchone()
        return json.loads(r["data"]) if r else None

    def list_tickets(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM tickets ORDER BY created DESC").fetchall()
        return [json.loads(r["data"]) for r in rows]

    def publish_update(self, incident_id: str, area: str, status: str, text: str, published: str | None = None) -> None:
        with self.lock:
            self.db.execute("INSERT INTO customer_updates (incident_id, area, status, text, published) VALUES (?,?,?,?,?)",
                            (incident_id, area, status, text, published or _now()))
            self.db.commit()

    def customer_updates(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM customer_updates ORDER BY seq DESC").fetchall()
        return [dict(r) for r in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
