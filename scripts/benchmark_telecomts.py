# py scripts/benchmark_telecomts.py
# py scripts/benchmark_telecomts.py --data PATH
# py scripts/benchmark_telecomts.py --limit 5000
# py scripts/benchmark_telecomts.py --export-features data/telecomts_features.csv.gz
# py scripts/benchmark_telecomts.py --features data/telecomts_features.csv.gz
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "AliMaatouk/TelecomTS"
CATEGORICAL = {"UL_Protocol", "DL_Protocol"}
STATS = ["mean", "std", "min", "max", "p95", "med", "zero", "maxdiff", "halfdiff"] + [f"s{i}" for i in range(8)]
SEED = 42

SENTINEL_CAUSE = {
    "Antenna Failure": "hardware_fault",
    "Faulty RF Filters (Temporal)": "hardware_fault",
    "Co-Channel Interference (Mild)": "external_interference",
    "Co-Channel Interference (Severe)": "external_interference",
    "Jamming": "external_interference",
    "High Network Congestion (Gradual Buildup)": "capacity_congestion",
    "High Network Congestion (Sudden Spike)": "capacity_congestion",
    "Doppler Shift (Severe)": None,
    "Faulty Handover Algorithm (Too Frequent)": None,
    "Buffer Overflow (Gradual Buildup)": None,
    "Resource Allocation Bugs": None,
}
CONTEXT = ("zone", "application", "mobility", "congestion")


def find_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("chunked.jsonl"))


def download(dest: Path) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("Install the downloader first:  py -m pip install huggingface_hub\n"
                 "or download the dataset yourself and pass --data PATH.")
    print(f"Downloading {REPO_ID} (chunked.jsonl files) to {dest} ...")
    snapshot_download(repo_id=REPO_ID, repo_type="dataset", local_dir=str(dest),
                      allow_patterns=["**/chunked.jsonl", "README.md"])
    return dest


def _stats(x: list[float]) -> list[float]:
    n = len(x)
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / n)
    s = sorted(x)
    d = max((abs(x[i + 1] - x[i]) for i in range(n - 1)), default=0.0)
    h = n // 2
    seg_len = max(1, n // 8)
    seg = [sum(x[i * seg_len:(i + 1) * seg_len]) / len(x[i * seg_len:(i + 1) * seg_len]) if x[i * seg_len:(i + 1) * seg_len] else m
           for i in range(8)]
    return [m, sd, s[0], s[-1], s[min(n - 1, int(0.95 * n))], s[n // 2], sum(1 for v in x if v == 0) / n, d,
            sum(x[h:]) / max(1, n - h) - sum(x[:h]) / max(1, h)] + seg


def featurise(kpis: dict, channels: list[str]) -> list[float]:
    out: list[float] = []
    for ch in channels:
        vals = kpis.get(ch) or []
        if ch in CATEGORICAL:
            n = max(1, len(vals))
            out += [sum(v == "TCP" for v in vals) / n, sum(v == "UDP" for v in vals) / n,
                    sum(v in (None, "None") for v in vals) / n]
            continue
        x = [float(v) if v is not None else float("nan") for v in vals]
        good = [v for v in x if v == v]
        if not good:
            out += [0.0] * len(STATS)
            continue
        mu = sum(good) / len(good)
        out += _stats([v if v == v else mu for v in x])
    return out


def feature_names(channels: list[str]) -> list[str]:
    names = []
    for ch in channels:
        names += [f"{ch}_tcp", f"{ch}_udp", f"{ch}_none"] if ch in CATEGORICAL else [f"{ch}__{s}" for s in STATS]
    return names


def load(files: list[Path], limit: int | None = None) -> dict:
    X, meta, channels = [], [], None
    for f in files:
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                item = json.loads(line)
                channels = channels or list(item["KPIs"])
                an, lb = item.get("anomalies") or {}, item.get("labels") or {}
                X.append(featurise(item["KPIs"], channels))
                meta.append({"anomaly": int(bool(an.get("exists"))), "type": (an.get("type") or "") if an.get("exists") else "",
                             **{k: str(lb.get(k)) for k in CONTEXT}})
                if limit and len(X) >= limit:
                    return _pack(X, meta, channels)
    return _pack(X, meta, channels)


def _pack(X, meta, channels) -> dict:
    return {"X": np.nan_to_num(np.array(X, dtype=float)), "meta": meta, "features": feature_names(channels), "channels": channels}


def export_features(d: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as g:
        w = csv.writer(g)
        w.writerow([*CONTEXT, "anomaly", "type", *d["features"]])
        for m, x in zip(d["meta"], d["X"]):
            w.writerow([*(m[k] for k in CONTEXT), m["anomaly"], m["type"], *(round(float(v), 6) for v in x)])


def load_features(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as g:
        r = csv.reader(g)
        head = next(r)
        idx = {h: i for i, h in enumerate(head)}
        feats = [h for h in head if "__" in h or h.endswith(("_tcp", "_udp", "_none"))]
        fi = [idx[h] for h in feats]
        X, meta = [], []
        for row in r:
            X.append([float(row[i]) for i in fi])
            meta.append({"anomaly": int(row[idx["anomaly"]]), "type": row[idx["type"]] if row[idx["type"]] != "nan" else "",
                         **{k: row[idx[k]] for k in CONTEXT}})
    channels = sorted({f.split("__")[0] for f in feats if "__" in f})
    return {"X": np.nan_to_num(np.array(X)), "meta": meta, "features": feats, "channels": channels}


class ContextBaseline:

    def fit(self, X, ctx, normal_idx):
        sd_floor = 0.1 * X[normal_idx].std(axis=0)
        self.glob = self._stats(X[normal_idx], sd_floor)
        self.by = {}
        for c in set(ctx[normal_idx]):
            m = normal_idx[ctx[normal_idx] == c]
            if len(m) >= 20:
                self.by[c] = self._stats(X[m], sd_floor)
        return self

    @staticmethod
    def _stats(A, floor):
        med = np.median(A, axis=0)
        return med, np.maximum(np.median(np.abs(A - med), axis=0) * 1.4826, floor) + 1e-6

    def transform(self, X, ctx):
        Z = np.empty_like(X)
        for c in set(ctx):
            i = np.where(ctx == c)[0]
            med, sc = self.by.get(c, self.glob)
            Z[i] = (X[i] - med) / sc
        Z = np.clip(Z, -1e3, 1e3)
        return np.sign(Z) * np.log1p(np.abs(Z))


def detectors(X, ctx, fit_idx):
    from sklearn.covariance import LedoitWolf
    from sklearn.decomposition import PCA
    from sklearn.ensemble import IsolationForest

    cb = ContextBaseline().fit(X, ctx, fit_idx)
    Z = cb.transform(X, ctx)
    iso_raw = IsolationForest(n_estimators=200, random_state=SEED).fit(X[fit_idx])
    iso_ctx = IsolationForest(n_estimators=200, random_state=SEED).fit(Z[fit_idx])
    pca = PCA(n_components=0.99, random_state=SEED).fit(Z[fit_idx])
    lw = LedoitWolf().fit(Z[fit_idx])
    return {
        "isolation_forest_raw": lambda i: -iso_raw.score_samples(X[i]),
        "isolation_forest_context": lambda i: -iso_ctx.score_samples(Z[i]),
        "pca_reconstruction_context": lambda i: ((Z[i] - pca.inverse_transform(pca.transform(Z[i]))) ** 2).sum(axis=1),
        "mahalanobis_context": lambda i: lw.mahalanobis(Z[i]),
    }


def evaluate(d: dict) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import (accuracy_score, average_precision_score, f1_score, precision_score,
                                 recall_score, roc_auc_score)
    from sklearn.model_selection import train_test_split

    X, meta = d["X"], d["meta"]
    y = np.array([m["anomaly"] for m in meta])
    types = np.array([m["type"] for m in meta])
    ctx = np.array(["|".join(m[k] for k in CONTEXT) for m in meta])
    idx = np.arange(len(y))
    strat = y if 0 < y.sum() < len(y) and min(Counter(y).values()) >= 4 else None
    tr, te = train_test_split(idx, test_size=0.2, random_state=SEED, stratify=strat)
    fit, val = train_test_split(tr, test_size=0.25, random_state=SEED, stratify=y[tr] if strat is not None else None)
    fit_normal = fit[y[fit] == 0]

    def binary(rows, pred, score) -> dict:
        yt = y[rows]
        m = {"precision": precision_score(yt, pred, zero_division=0), "recall": recall_score(yt, pred, zero_division=0),
             "f1": f1_score(yt, pred, zero_division=0),
             "false_alarm_rate": float(np.mean(pred[yt == 0])) if (yt == 0).any() else None}
        if len(set(yt)) == 2:
            m["roc_auc"] = roc_auc_score(yt, score)
            m["pr_auc"] = average_precision_score(yt, score)
        return {k: (round(float(v), 4) if v is not None else None) for k, v in m.items()}

    unsup = {}
    for name, score in detectors(X, ctx, fit_normal).items():
        thr = float(np.percentile(score(fit_normal), 99))
        s_val, s_te = score(val), score(te)
        unsup[name] = {"validation_pr_auc": round(float(average_precision_score(y[val], s_val)), 4) if len(set(y[val])) == 2 else 0.0,
                       "test": binary(te, (s_te >= thr).astype(int), s_te),
                       "_pred": (s_te >= thr).astype(int)}
    best = max(unsup, key=lambda k: unsup[k]["validation_pr_auc"])
    pred = unsup[best].pop("_pred")
    for v in unsup.values():
        v.pop("_pred", None)
    per_type = {t: round(float(pred[(types[te] == t)].mean()), 3) for t in sorted(set(types[te])) if t}

    clf = HistGradientBoostingClassifier(random_state=SEED).fit(X[tr], y[tr])
    p = clf.predict_proba(X[te])[:, 1] if len(clf.classes_) == 2 else np.zeros(len(te))
    sup = binary(te, (p >= 0.5).astype(int), p)

    rca: dict = {"note": "10 synthetic types; Jamming excluded as in the TelecomTS paper"}
    rca_tr = [i for i in tr if y[i] and types[i] != "Jamming"]
    rca_te = [i for i in te if y[i] and types[i] != "Jamming"]
    if len(set(types[rca_tr])) >= 2 and rca_te:
        rc = HistGradientBoostingClassifier(random_state=SEED).fit(X[rca_tr], types[rca_tr])
        pr = rc.predict(X[rca_te])
        labels = sorted(set(types[rca_te]))
        per = f1_score(types[rca_te], pr, labels=labels, average=None, zero_division=0)
        rca |= {"accuracy": round(float(accuracy_score(types[rca_te], pr)), 4),
                "macro_f1": round(float(f1_score(types[rca_te], pr, average="macro", zero_division=0)), 4),
                "per_type_f1": {lab: round(float(v), 4) for lab, v in zip(labels, per)},
                "train_windows": len(rca_tr), "test_windows": len(rca_te)}
        cause = np.array([SENTINEL_CAUSE.get(t) or "" for t in types])
        map_tr = [i for i in tr if cause[i]]
        map_te = [i for i in te if cause[i]]
        if map_tr and map_te and len(set(cause[map_tr])) >= 2:
            mc = HistGradientBoostingClassifier(random_state=SEED).fit(X[map_tr], cause[map_tr])
            mp = mc.predict(X[map_te])
            rca["sentinel_causes"] = {
                "accuracy": round(float(accuracy_score(cause[map_te], mp)), 4),
                "macro_f1": round(float(f1_score(cause[map_te], mp, average="macro", zero_division=0)), 4),
                "test_windows": len(map_te), "mapping": {k: v for k, v in SENTINEL_CAUSE.items() if v}}

    return {"windows": len(y), "train": len(tr), "test": len(te), "validation": len(val),
            "anomaly_share": round(float(y.mean()), 4), "channels": d["channels"], "features_per_window": int(X.shape[1]),
            "anomaly_types": dict(Counter(t for t in types if t)),
            "unsupervised": {"selected": best, "selected_by": "best PR-AUC on the validation split (not test)",
                             "threshold": "99th percentile of normal fitting windows (1% false-alarm target)",
                             "detectors": unsup, "selected_recall_by_type": per_type},
            "supervised_gbt": sup, "root_cause": rca}


def main() -> None:
    ap = argparse.ArgumentParser(description="TelecomTS detection benchmark")
    ap.add_argument("--data", type=Path, help="folder with chunked.jsonl files, or one .jsonl file")
    ap.add_argument("--features", type=Path, help="precomputed feature table (.csv or .csv.gz) from --export-features")
    ap.add_argument("--export-features", type=Path, help="also write the feature table here")
    ap.add_argument("--limit", type=int, help="use only the first N windows (quick run)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "benchmarks" / "telecomts.json")
    a = ap.parse_args()
    t0 = time.time()
    if a.features:
        d = load_features(a.features)
        src = f"feature table {a.features.name}"
    else:
        src_dir = a.data or (ROOT / "data" / "telecomts")
        files = find_files(src_dir) if src_dir.exists() else []
        if not files and not a.data:
            files = find_files(download(src_dir))
        if not files:
            sys.exit(f"No chunked.jsonl found under {src_dir}")
        d = load(files, a.limit)
        src = f"{len(files)} chunked.jsonl file(s)"
        if a.export_features:
            export_features(d, a.export_features)
    print(f"Loaded {len(d['meta'])} windows from {src}")
    res = evaluate(d)
    res |= {"dataset": f"TelecomTS ({REPO_ID}), MIT licence", "citation": "Feng et al., TelecomTS, ICML 2026, arXiv:2510.06063",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "limit": a.limit,
            "runtime_s": round(time.time() - t0, 1)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=2))
    u = res["unsupervised"]
    print(f"Unsupervised (selected on validation): {u['selected']}")
    for k, v in u["detectors"].items():
        t = v["test"]
        print(f"  {k:28s} val PR-AUC {v['validation_pr_auc']:.3f} | test F1 {t['f1']:.3f} recall {t['recall']:.3f} "
              f"ROC-AUC {t.get('roc_auc', 0):.3f} false alarms {t['false_alarm_rate']:.3%}")
    print("Supervised detection:", res["supervised_gbt"])
    print("Root cause:", {k: v for k, v in res["root_cause"].items() if k not in ("per_type_f1", "note")})
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
