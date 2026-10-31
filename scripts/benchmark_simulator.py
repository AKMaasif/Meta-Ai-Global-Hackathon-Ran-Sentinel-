# py scripts/benchmark_simulator.py
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import orchestrator  # noqa: E402
from app.config import Settings  # noqa: E402
from app.detection import ALERT_THRESHOLD, CONSECUTIVE, Detector, check_quality, threshold_breaches  # noqa: E402
from app.providers import OfflineProvider  # noqa: E402
from app.detection import features  # noqa: E402
from app.simulator import NetworkSimulator, training_rows  # noqa: E402

import numpy as np  # noqa: E402
from app.store import Store  # noqa: E402

EXPECTED = {"capacity_surge": "capacity_congestion", "interference": "external_interference",
            "overshoot": "overshooting_coverage", "hardware": "hardware_fault"}
CELLS = ["SEA-RAN-001", "SEA-RAN-011", "SEA-RAN-020", "SEA-RAN-032"]
MAX_TICKS = 6
DETECTORS = ("thresholds_only", "iforest_only", "cell_baseline_only", "rules_plus_iforest", "combined")


def detectors(det: Detector, row: dict) -> dict[str, bool]:
    s, _ = det.score(row)
    b, _ = det.baseline.score(row)
    rules, model, base = bool(threshold_breaches(row)), s >= ALERT_THRESHOLD, b >= 1.0
    return {"thresholds_only": rules, "iforest_only": model, "cell_baseline_only": base,
            "rules_plus_iforest": rules or model, "combined": rules or model or base}


def false_alarms(det: Detector, days: int = 3, seed: int = 99) -> dict:
    sim = NetworkSimulator(seed=seed, history=False)
    streak = {k: {} for k in DETECTORS}
    alerts = {k: 0 for k in streak}
    for _ in range(days * 96):
        sim.step()
        for cid in sim.cells:
            hits = detectors(det, sim.latest(cid))
            for k, hit in hits.items():
                streak[k][cid] = streak[k].get(cid, 0) + 1 if hit else 0
                if streak[k][cid] == CONSECUTIVE:
                    alerts[k] += 1
    cell_days = days * len(sim.cells)
    return {k: {"alerts": v, "per_cell_day": round(v / cell_days, 4)} for k, v in alerts.items()} | {"cell_days": cell_days}


def detection(det: Detector) -> dict:
    out = {k: {"detected": 0, "total": 0, "ticks": []} for k in DETECTORS}
    for fault in EXPECTED:
        for sev in (1, 2, 3):
            for cid in CELLS:
                sim = NetworkSimulator(seed=7)
                sim.inject_fault(cid, fault, sev)
                first = {}
                streak = {k: 0 for k in out}
                for t in range(1, MAX_TICKS + 1):
                    sim.step()
                    for k, hit in detectors(det, sim.latest(cid)).items():
                        streak[k] = streak[k] + 1 if hit else 0
                        if streak[k] >= CONSECUTIVE and k not in first:
                            first[k] = t
                for k in out:
                    out[k]["total"] += 1
                    if k in first:
                        out[k]["detected"] += 1
                        out[k]["ticks"].append(first[k])
    res = {}
    for k, v in out.items():
        res[k] = {"detection_rate": round(v["detected"] / v["total"], 3), "detected": v["detected"], "total": v["total"],
                  "mean_minutes_to_alert": round(15 * sum(v["ticks"]) / len(v["ticks"]), 1) if v["ticks"] else None}
    return res


def diagnosis(rows) -> dict:
    orchestrator.training_rows = lambda: rows
    s = Settings()
    s.api_key, s.maveric_url = "", ""
    per = {f: {"correct": 0, "total": 0} for f in EXPECTED}
    confusion: dict[str, dict[str, int]] = {}
    dq = {"detected": 0, "total": 0}
    for fault, want in EXPECTED.items():
        for sev in (1, 2, 3):
            for cid in CELLS:
                sen = orchestrator.Sentinel(s, Store(":memory:"), OfflineProvider())
                sen.sync = True
                sen.inject(cid, fault, sev)
                for _ in range(MAX_TICKS):
                    sen.tick()
                    if cid in sen.open_by_cell:
                        break
                inc = sen.incidents.get(sen.open_by_cell.get(cid, ""))
                got = ((inc or {}).get("diagnosis") or {}).get("hypotheses", [{}])[0].get("cause", "not detected")
                per[fault]["total"] += 1
                per[fault]["correct"] += int(got == want)
                confusion.setdefault(want, {}).setdefault(got, 0)
                confusion[want][got] += 1
    for cid in CELLS:
        sim = NetworkSimulator(seed=7)
        sim.inject_fault(cid, "data_dropout", 2)
        streak, hit = 0, False
        for _ in range(MAX_TICKS):
            sim.step()
            streak = streak + 1 if check_quality(sim.latest(cid)) else 0
            hit = hit or streak >= CONSECUTIVE
        dq["total"] += 1
        dq["detected"] += int(hit)
    total = sum(v["total"] for v in per.values())
    correct = sum(v["correct"] for v in per.values())
    return {"top1_accuracy": round(correct / total, 3), "correct": correct, "total": total,
            "per_fault": {f: round(v["correct"] / v["total"], 3) for f, v in per.items()},
            "confusion": confusion, "data_dropout_detected": dq}


def main() -> None:
    t0 = time.time()
    rows = training_rows()
    det = Detector(np.array([features(r) for r in rows]), rows=rows)
    result = {
        "dataset": "RAN Sentinel simulator (36 cells, Seattle, 15-minute KPIs)",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "setup": {"fault_types": list(EXPECTED), "severities": [1, 2, 3], "cells": CELLS,
                  "max_minutes": MAX_TICKS * 15, "consecutive_windows": CONSECUTIVE},
        "false_alarms_normal_traffic": false_alarms(det),
        "detection": detection(det),
        "diagnosis_offline_rules": diagnosis(rows),
        "caveat": "Simulated data written by us; these numbers show the pipeline works as designed, not field accuracy.",
    }
    result["runtime_s"] = round(time.time() - t0, 1)
    out = ROOT / "data" / "benchmarks" / "simulator.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("false_alarms_normal_traffic", "detection")}, indent=2))
    print("diagnosis:", result["diagnosis_offline_rules"]["top1_accuracy"], result["diagnosis_offline_rules"]["per_fault"])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
