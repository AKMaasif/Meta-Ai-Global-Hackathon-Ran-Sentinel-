from __future__ import annotations

import copy
import csv
import dataclasses
import hashlib
import io
import json
import math
import time
import zipfile

import httpx
import numpy as np

from . import radio

TRAIN_TILTS = (0.0, 3.0, 6.0, 9.0, 12.0, 15.0)
NEARBY_KM = 3.0


class RadpError(Exception):
    pass


class RadpClient:
    def __init__(self, url: str, http: httpx.Client | None = None, timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.http = http or httpx.Client(timeout=timeout)

    def _json(self, r: httpx.Response) -> dict:
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            raise RadpError(f"RADP {r.request.url.path} returned {r.status_code}: {str(body)[:200]}")
        return body

    def reachable(self) -> bool:
        try:
            return self.http.get(self.url + "/model/ping", timeout=2).status_code < 500
        except httpx.HTTPError:
            return False

    def model(self, model_id: str) -> dict:
        r = self.http.get(f"{self.url}/model/{model_id}")
        if r.status_code == 404 or r.status_code == 400:
            return {"exists": False}
        return {"exists": True, **self._json(r)}

    def model_trained(self, model_id: str) -> bool:
        m = self.model(model_id)
        return m.get("exists") and m.get("status") == "trained"

    def train(self, model_id: str, training_csv: str, topology_csv: str, params: dict | None = None) -> dict:
        payload = json.dumps({"model_id": model_id, "model_update": False, "params": params or {}})
        files = [
            ("payload", ("data", payload, "application/json")),
            ("ue_training_data.csv", ("ue_training_data.csv", training_csv, "application/csv")),
            ("topology.csv", ("topology.csv", topology_csv, "application/csv")),
        ]
        return self._json(self.http.post(self.url + "/train", files=files))

    def simulate(self, event: dict, ue_csv: str, config_csv: str) -> str:
        files = [
            ("payload", ("payload", json.dumps(event), "application/json")),
            ("ue_data.csv", ("ue_data.csv", ue_csv, "application/csv")),
            ("config.csv", ("config.csv", config_csv, "application/csv")),
        ]
        return self._json(self.http.post(self.url + "/simulation", files=files))["simulation_id"]

    def wait(self, simulation_id: str, timeout: float, every: float = 1.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r = self.http.get(f"{self.url}/simulation/{simulation_id}")
            if r.status_code == 200 and self._json(r).get("simulation_status") == "finished":
                return
            time.sleep(every)
        raise RadpError(f"simulation {simulation_id} not finished after {timeout:.0f} s")

    def output(self, simulation_id: str) -> list[dict]:
        r = self.http.get(f"{self.url}/simulation/{simulation_id}/download")
        if r.status_code >= 400:
            raise RadpError(f"RADP download returned {r.status_code}")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = next(n for n in z.namelist() if not n.endswith("/"))
            text = z.read(name).decode()
        return list(csv.DictReader(io.StringIO(text)))


def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def topology_csv(cells: dict) -> str:
    rows = []
    for cid, c in cells.items():
        lat, lon = radio.to_latlon(*radio.site_xy(c))
        rows.append({"cell_id": cid, "cell_name": cid, "cell_lat": lat, "cell_lon": lon, "cell_az_deg": c.azimuth,
                     "cell_carrier_freq_mhz": int(radio.BAND_MHZ.get(radio.band_key(c.band), 2000.0))})
    return _csv(rows, ["cell_id", "cell_name", "cell_lat", "cell_lon", "cell_az_deg", "cell_carrier_freq_mhz"])


def _planned(cell, tilt: float):
    c = copy.copy(cell)
    c.config = dataclasses.replace(cell.planned, tilt_deg=tilt)
    return c


def training_csv(cells: dict, points_per_tilt: int = 60, seed: int = 7) -> str:
    rng = np.random.default_rng(seed)
    rows = []
    for cid, cell in cells.items():
        sx, sy = radio.site_xy(cell)
        reach = max(0.5, radio.coverage_km(cell)) * 1.3
        for t in TRAIN_TILTS:
            c = _planned(cell, t)
            for _ in range(points_per_tilt):
                d = reach * math.sqrt(rng.uniform(0.002, 1.0))
                a = rng.uniform(0, 2 * math.pi)
                px, py = sx + d * math.sin(a), sy + d * math.cos(a)
                rsrp, _ = radio._rsrp(c, None, px, py, indoor=False)
                lat, lon = radio.to_latlon(px, py)
                rows.append({"cell_id": cid, "avg_rsrp": round(rsrp, 2), "lon": lon, "lat": lat, "cell_el_deg": t})
    return _csv(rows, ["cell_id", "avg_rsrp", "lon", "lat", "cell_el_deg"])


def nearby(cells: dict, cell_id: str) -> list[str]:
    tx, ty = radio.site_xy(cells[cell_id])
    out = [cell_id]
    for cid, c in cells.items():
        x, y = radio.site_xy(c)
        if cid != cell_id and math.hypot(x - tx, y - ty) <= NEARBY_KM:
            out.append(cid)
    return out


def grid(cell, n: int = 21) -> list[tuple[float, float]]:
    sx, sy = radio.site_xy(cell)
    r = min(1.2, max(0.5, radio.coverage_km(cell)) * 1.2)
    pts = []
    for i in range(n):
        for j in range(n):
            px, py = sx - r + 2 * r * i / (n - 1), sy - r + 2 * r * j / (n - 1)
            if math.hypot(px - sx, py - sy) <= r:
                pts.append((px, py))
    return pts


def coverage_change(rows_before: list[dict], rows_after: list[dict], cell_id: str,
                    offset_before: float, offset_after: float) -> dict:
    def table(rows, offset):
        best: dict[tuple, tuple[float, str]] = {}
        own: dict[tuple, float] = {}
        for r in rows:
            key = (round(float(r["lat"]), 5), round(float(r["lon"]), 5))
            p = float(r["rxpower_dbm"]) + (offset if r["cell_id"] == cell_id else 0.0)
            if r["cell_id"] == cell_id:
                own[key] = p
            if key not in best or p > best[key][0]:
                best[key] = (p, r["cell_id"])
        return best, own

    b_best, b_own = table(rows_before, offset_before)
    a_best, a_own = table(rows_after, offset_after)
    served = [k for k, (p, c) in b_best.items() if c == cell_id and p >= radio.EDGE_RSRP_DBM]
    holes = [k for k in served if k in a_best and a_best[k][0] < radio.EDGE_RSRP_DBM]
    handed = [k for k in served if k in a_best and a_best[k][1] != cell_id and a_best[k][0] >= radio.EDGE_RSRP_DBM]
    med = lambda d: round(float(np.median([d[k] for k in served if k in d])), 1) if served else None
    return {
        "points": len(b_best), "served_before": len(served), "new_holes": len(holes), "handed_to_neighbours": len(handed),
        "coverage_loss_pct": round(100.0 * len(holes) / max(1, len(served)), 2),
        "median_rsrp_before": med(b_own), "median_rsrp_after": med(a_own),
    }


def what_if(client: RadpClient, model_id: str, cells: dict, cell_id: str, changes: dict, timeout: float) -> dict:
    cell = cells[cell_id]
    ids = nearby(cells, cell_id)
    pts = grid(cell)
    ue_csv = _csv([{"lon": radio.to_latlon(x, y)[1], "lat": radio.to_latlon(x, y)[0]} for x, y in pts], ["lon", "lat"])
    ue_id = "rs-" + hashlib.sha1(ue_csv.encode(), usedforsecurity=False).hexdigest()[:12]

    def run(tilt_of_target: float) -> list[dict]:
        cfg = [{"cell_id": c, "cell_el_deg": tilt_of_target if c == cell_id else cells[c].config.tilt_deg} for c in ids]
        cfg_csv = _csv(cfg, ["cell_id", "cell_el_deg"])
        event = {"simulation_time_interval_seconds": 1, "ue_tracks": {"ue_data_id": ue_id},
                 "rf_prediction": {"model_id": model_id,
                                   "config_id": "rs-" + hashlib.sha1(cfg_csv.encode(), usedforsecurity=False).hexdigest()[:12]}}
        sid = client.simulate(event, ue_csv, cfg_csv)
        client.wait(sid, timeout)
        return client.output(sid)

    tilt0 = cell.config.tilt_deg
    tilt1 = float(changes.get("tilt_deg", tilt0))
    p_ref = cell.planned.tx_power_dbm
    p0 = cell.config.tx_power_dbm
    p1 = float(changes.get("tx_power_dbm", p0))
    before = run(tilt0)
    after = before if tilt1 == tilt0 else run(tilt1)
    rf = coverage_change(before, after, cell_id, p0 - p_ref, p1 - p_ref)
    rf.update({"model_id": model_id, "cells_in_view": len(ids), "tilt": [tilt0, tilt1], "tx_power_dbm": [p0, p1]})
    return rf
