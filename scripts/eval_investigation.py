# py scripts/eval_investigation.py
# py scripts/eval_investigation.py --live
# py scripts/eval_investigation.py --severity 1
# py scripts/eval_investigation.py --live --runs 2 --json data/benchmarks/investigation.json
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import verify  # noqa: E402
from app.config import Settings  # noqa: E402
from app.orchestrator import Sentinel  # noqa: E402
from app.providers import OfflineProvider, make_provider  # noqa: E402
from app.store import Store  # noqa: E402

FAULTS = ["capacity_surge", "interference", "overshoot", "hardware"]
CELLS = ["SEA-RAN-001", "SEA-RAN-004", "SEA-RAN-007"]


def one(settings: Settings, live: bool, cell: str, fault: str, severity: int = 2) -> dict:
    sen = Sentinel(settings, Store(":memory:"), make_provider(settings) if live else OfflineProvider())
    sen.sync = True
    t0 = time.time()
    sen.inject(cell, fault, severity)
    inc = None
    for _ in range(10):
        sen.tick()
        if cell in sen.open_by_cell:
            inc = sen.incidents[sen.open_by_cell[cell]]
            break
    if not inc:
        return {"cell": cell, "fault": fault, "opened": False}
    ver = inc.get("verification") or {}
    truth = verify.truth_score(inc.get("diagnosis"), fault)
    return {"cell": cell, "fault": fault, "opened": True, "diagnosed": truth["diagnosed"], "correct": truth["correct"],
            "verified": bool(ver.get("passed")), "verify_attempts": ver.get("attempt"),
            "playbook": f"{ver['coverage']['covered']}/{ver['coverage']['total']}" if ver else None,
            "facts_ok": sum(f["verified"] for f in ver.get("facts", [])), "facts": len(ver.get("facts", [])),
            "status": inc["status"], "escalation": (inc.get("escalation") or "")[:160], "tool_calls": inc["tool_calls"],
            "model_calls": len(inc["agent_runs"]), "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the Meta Model API (needs MODEL_API_KEY in .env)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--severity", type=int, default=2, choices=[1, 2, 3], help="1 = mild faults, harder to tell apart")
    ap.add_argument("--json", help="save results to this file")
    a = ap.parse_args()
    s = Settings()
    s.maveric_url = ""
    if not a.live:
        s.api_key = ""
    elif not s.api_key:
        sys.exit("No MODEL_API_KEY found. Put it in .env or run without --live.")
    rows = []
    for _ in range(a.runs):
        for fault in FAULTS:
            for cell in CELLS:
                r = one(s, a.live, cell, fault, a.severity)
                rows.append(r)
                print(f"{fault:15} {cell}  " + ("not opened" if not r["opened"] else
                      f"{'OK ' if r['correct'] else 'BAD'} {r['diagnosed'] or '-':22} verified={r['verified']!s:5} "
                      f"attempts={r['verify_attempts']} playbook={r['playbook']} facts={r['facts_ok']}/{r['facts']} "
                      f"{r['status']:19} {r['seconds']}s"))
    opened = [r for r in rows if r["opened"]]
    summary = {"engine": "live" if a.live else "offline", "severity": a.severity, "incidents": len(opened),
               "accuracy": round(sum(r["correct"] for r in opened) / max(1, len(opened)), 3),
               "verified_rate": round(sum(r["verified"] for r in opened) / max(1, len(opened)), 3),
               "verified_first_try": sum(r["verify_attempts"] == 1 and r["verified"] for r in opened),
               "escalated": sum(r["status"] == "ESCALATED" for r in opened),
               "wrong_but_verified": sum(r["verified"] and not r["correct"] for r in opened)}
    print(json.dumps(summary, indent=2))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
