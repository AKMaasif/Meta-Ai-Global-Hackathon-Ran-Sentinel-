from __future__ import annotations

import math

import numpy as np
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import IsolationForest

FEATURES = ["prb_util", "dl_thpt_mbps", "cqi", "sinr_db", "ul_rssi_dbm", "drop_rate", "ho_success", "far_user_share"]

VALID_RANGES = {
    "active_users": (0, 2000), "prb_util": (0, 100), "dl_thpt_mbps": (0, 1000), "cqi": (1, 15),
    "sinr_db": (-20, 40), "ul_rssi_dbm": (-130, -40), "drop_rate": (0, 100), "ho_success": (0, 100),
    "far_user_share": (0, 1), "availability": (0, 100),
}

THRESHOLDS = [
    ("prb_util", ">", 90.0, "PRB utilisation above 90%"),
    ("drop_rate", ">", 2.0, "Drop rate above 2%"),
    ("ho_success", "<", 97.0, "Handover success below 97%"),
    ("sinr_db", "<", 6.0, "SINR below 6 dB"),
    ("ul_rssi_dbm", ">", -96.0, "Uplink RSSI above -96 dBm"),
    ("far_user_share", ">", 0.18, "Far-from-site user share above 18%"),
    ("availability", "<", 99.9, "Cell availability below 99.9%"),
]

ALERT_THRESHOLD = 0.62
CONSECUTIVE = 2
DETECTOR_VERSION = "thresholds-v1+iforest-v1+baseline-maha-v1"


def features(row: dict) -> list[float]:
    vals = []
    for k in FEATURES:
        v = float(row[k])
        if k == "dl_thpt_mbps":
            v = math.log1p(v)
        vals.append(v)
    return vals


def check_quality(row: dict | None) -> list[str]:
    if row is None:
        return ["no data received"]
    if row.get("missing"):
        return ["KPI row missing from collector"]
    issues = []
    for k, (lo, hi) in VALID_RANGES.items():
        v = row.get(k)
        if v is None:
            issues.append(f"{k} missing")
        elif isinstance(v, float) and math.isnan(v):
            issues.append(f"{k} is NaN")
        elif not (lo <= v <= hi):
            issues.append(f"{k}={v} outside valid range {lo}..{hi}")
    return issues


def threshold_breaches(row: dict) -> list[str]:
    out = []
    for k, op, lim, text in THRESHOLDS:
        v = row[k]
        if (op == ">" and v > lim) or (op == "<" and v < lim):
            out.append(text)
    return out


def forecast(values: list[float], ahead: int = 4) -> float | None:
    vals = [v for v in values if v is not None]
    if len(vals) < 4:
        return None
    x = np.arange(len(vals))
    slope, intercept = np.polyfit(x, vals, 1)
    return float(intercept + slope * (len(vals) - 1 + ahead))


class Baseline:

    def __init__(self, rows: list[dict], x: np.ndarray):
        cells = np.array([r["cell_id"] for r in rows])
        hours = np.array([int(r["ts"][11:13]) for r in rows])
        floor = 0.1 * x.std(axis=0)
        self.base: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
        for c in np.unique(cells):
            for h in range(24):
                m = (cells == c) & (np.abs(((hours - h + 12) % 24) - 12) <= 1)
                a = x[m]
                med = np.median(a, axis=0)
                self.base[(c, h)] = (med, np.maximum(np.median(np.abs(a - med), axis=0) * 1.4826, floor) + 1e-6)
        z = np.array([self.z(r, f) for r, f in zip(rows, x)])
        self.cov = LedoitWolf().fit(z)
        self.threshold = float(self.cov.mahalanobis(z).max())

    def z(self, row: dict, feats=None) -> np.ndarray:
        med, scale = self.base[(row["cell_id"], int(row["ts"][11:13]))]
        v = (np.asarray(feats if feats is not None else features(row)) - med) / scale
        return np.sign(v) * np.log1p(np.abs(v))

    def score(self, row: dict) -> tuple[float, list[dict]]:
        z = self.z(row)
        d = float(self.cov.mahalanobis(z[None])[0])
        order = np.argsort(-np.abs(z))[:3]
        contrib = [{"feature": FEATURES[i], "z_vs_usual": round(float(np.sign(z[i]) * np.expm1(abs(z[i]))), 1),
                    "value": row[FEATURES[i]]} for i in order]
        return round(d / self.threshold, 3), contrib


class Detector:
    def __init__(self, train: np.ndarray, seed: int = 0, rows: list[dict] | None = None):
        self.model = IsolationForest(n_estimators=200, contamination="auto", random_state=seed)
        self.model.fit(train)
        raw = -self.model.score_samples(train)
        self.p50 = float(np.percentile(raw, 50))
        self.p999 = float(np.percentile(raw, 99.9))
        self.mean = train.mean(axis=0)
        self.std = train.std(axis=0) + 1e-6
        self.streak: dict[str, int] = {}
        self.dq_streak: dict[str, int] = {}
        self.baseline = Baseline(rows, train) if rows else None

    def score(self, row: dict) -> tuple[float, list[dict]]:
        x = np.array([features(row)])
        raw = float(-self.model.score_samples(x)[0])
        s = (raw - self.p50) / max(1e-6, self.p999 - self.p50) * ALERT_THRESHOLD
        s = float(min(1.0, max(0.0, s)))
        z = (x[0] - self.mean) / self.std
        order = np.argsort(-np.abs(z))[:3]
        contrib = [{"feature": FEATURES[i], "z": round(float(z[i]), 2), "value": row[FEATURES[i]]} for i in order]
        return round(s, 3), contrib

    def evaluate(self, row: dict | None, cell_id: str) -> dict:
        issues = check_quality(row)
        if issues:
            self.dq_streak[cell_id] = self.dq_streak.get(cell_id, 0) + 1
            self.streak[cell_id] = 0
            return {"cell_id": cell_id, "quality_ok": False, "issues": issues,
                    "data_quality_alert": self.dq_streak[cell_id] >= CONSECUTIVE, "alert": False}
        self.dq_streak[cell_id] = 0
        s, contrib = self.score(row)
        breaches = threshold_breaches(row)
        b, b_contrib = self.baseline.score(row) if self.baseline else (None, [])
        hit = s >= ALERT_THRESHOLD or bool(breaches) or (b is not None and b >= 1.0)
        self.streak[cell_id] = self.streak.get(cell_id, 0) + 1 if hit else 0
        return {
            "cell_id": cell_id, "quality_ok": True, "issues": [], "score": s, "threshold": ALERT_THRESHOLD,
            "breaches": breaches, "contributors": contrib, "consecutive": self.streak[cell_id],
            "alert": self.streak[cell_id] >= CONSECUTIVE, "data_quality_alert": False,
            "detector_version": DETECTOR_VERSION, "baseline_score": b, "baseline_contributors": b_contrib,
            "triggered_by": [n for n, on in (("rules", bool(breaches)), ("isolation_forest", s >= ALERT_THRESHOLD),
                                             ("cell_baseline", b is not None and b >= 1.0)) if on],
        }
