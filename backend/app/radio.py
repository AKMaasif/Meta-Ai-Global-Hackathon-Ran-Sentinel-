from __future__ import annotations

import math

ANCHOR = (47.6062, -122.3321)
KM_PER_DEG_LAT = 110.574
ANTENNA_H_M = 25.0
INDOOR_LOSS_DB = 12.0
NOISE_RE_DBM = -174 + 10 * math.log10(15_000) + 7.0
BAND_MHZ = {"B66": 2110.0, "B2": 1930.0, "B71": 617.0}
NRB = {20: 100, 15: 75, 10: 50, 5: 25}
EDGE_RSRP_DBM = -110.0


def to_latlon(x_km: float, y_km: float) -> tuple[float, float]:
    lat = ANCHOR[0] + y_km / KM_PER_DEG_LAT
    lon = ANCHOR[1] + x_km / (111.320 * math.cos(math.radians(ANCHOR[0])))
    return round(lat, 5), round(lon, 5)


def band_key(band: str) -> str:
    return band.split(" ")[0]


def path_loss_db(d_km: float, f_mhz: float) -> float:
    d = max(0.02, d_km)
    dhb = ANTENNA_H_M
    return 40 * (1 - 4e-3 * dhb) * math.log10(d) - 18 * math.log10(dhb) + 21 * math.log10(f_mhz) + 80


def antenna_gain_db(bearing_deg: float, azimuth_deg: float, d_km: float, tilt_deg: float) -> float:
    dphi = (bearing_deg - azimuth_deg + 180) % 360 - 180
    theta = math.degrees(math.atan2(ANTENNA_H_M / 1000.0, max(0.02, d_km)))
    att = 12 * (dphi / 65) ** 2 + 12 * ((theta - tilt_deg) / 10) ** 2
    return 15.0 - min(att, 25.0)


def effective_power(cell, row: dict | None) -> float:
    p = cell.config.tx_power_dbm
    if row and row.get("availability", 100.0) < 100.0:
        p -= 6.0
    return p


def coverage_km(cell, row: dict | None = None) -> float:
    per_re = effective_power(cell, row) - 10 * math.log10(12 * NRB.get(cell.config.bandwidth_mhz, 100)) + 15.0
    f = BAND_MHZ.get(band_key(cell.band), 2000.0)
    budget = per_re - EDGE_RSRP_DBM
    const = -18 * math.log10(ANTENNA_H_M) + 21 * math.log10(f) + 80
    return round(10 ** ((budget - const) / (40 * (1 - 4e-3 * ANTENNA_H_M))), 2)


SECTOR_OFFSET_KM = 0.35


def site_xy(cell) -> tuple[float, float]:
    a = math.radians(cell.azimuth)
    return cell.x - SECTOR_OFFSET_KM * math.sin(a), cell.y - SECTOR_OFFSET_KM * math.cos(a)


def _rsrp(cell, row, px, py, indoor=True) -> tuple[float, float]:
    sx, sy = site_xy(cell)
    dx, dy = px - sx, py - sy
    d = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dx, dy)) % 360
    per_re = effective_power(cell, row) - 10 * math.log10(12 * NRB.get(cell.config.bandwidth_mhz, 100))
    r = per_re + antenna_gain_db(bearing, cell.azimuth, d, cell.config.tilt_deg) \
        - path_loss_db(d, BAND_MHZ.get(band_key(cell.band), 2000.0)) - (INDOOR_LOSS_DB if indoor else 0.0)
    return r, d


def measure(cells: dict, rows: dict, px: float, py: float) -> dict:
    cand = []
    for cid, c in cells.items():
        row = rows.get(cid)
        rsrp, d = _rsrp(c, row, px, py)
        if d <= 8.0:
            cand.append((rsrp, cid, d))
    cand.sort(reverse=True)
    if not cand or cand[0][0] < -124.0:
        return {"connected": False}
    rsrp, sid, dist = cand[0]
    s = cells[sid]
    srow = rows.get(sid) or {}
    band = band_key(s.band)
    s_mw = 10 ** (rsrp / 10)
    i_mw = sum(10 ** (r / 10) * min(1.0, max(0.1, (rows.get(cid) or {}).get("prb_util", 50.0) / 100))
               for r, cid, _ in cand[1:] if band_key(cells[cid].band) == band)
    geo_sinr = 10 * math.log10(s_mw / (i_mw + 10 ** (NOISE_RE_DBM / 10)))
    sinr = geo_sinr + ((srow.get("sinr_db") - 13.0) if srow.get("sinr_db") is not None else 0.0)
    sinr = max(-10.0, min(30.0, sinr))
    load = min(0.97, max(0.05, (srow.get("prb_util") or 50.0) / 100))
    rsrq = 10 * math.log10(1 / (12 * (load + 1 / 10 ** (sinr / 10))))
    rsrq = max(-20.0, min(-3.0, rsrq))
    latency = 22 + 6 * load / (1 - load) + 4 * max(0.0, 5 - sinr)
    loss = None if srow.get("drop_rate") is None else min(15.0, srow["drop_rate"] * 0.5 + 0.3 * max(0.0, 3 - sinr))
    alts = []
    seen = {s.site}
    for r, cid, d in cand[1:]:
        if r < -115 or cells[cid].site in seen:
            continue
        seen.add(cells[cid].site)
        alts.append({"cell_id": cid, "site": cells[cid].site, "rsrp_dbm": round(r, 1), "distance_km": round(d, 2)})
        if len(alts) == 2:
            break
    return {"connected": True, "serving_cell": sid, "serving_site": s.site, "band": s.band, "distance_km": round(dist, 2),
            "rsrp_dbm": round(rsrp, 1), "rsrq_db": round(rsrq, 1), "sinr_db": round(sinr, 1),
            "latency_ms": round(latency, 0), "packet_loss_pct": None if loss is None else round(loss, 2),
            "kpi_missing": not srow or srow.get("missing", False), "alternatives": alts}


BANDS = {
    "rsrp_dbm": [(-80, "excellent"), (-90, "good"), (-100, "fair"), (-124, "poor")],
    "rsrq_db": [(-10, "excellent"), (-15, "good"), (-20, "fair")],
    "sinr_db": [(20, "excellent"), (13, "good"), (0, "fair")],
    "latency_ms": [(50, "excellent"), (100, "good"), (200, "fair")],
    "packet_loss_pct": [(0.5, "excellent"), (1.0, "good"), (2.5, "fair")],
}
LOWER_IS_BETTER = {"latency_ms", "packet_loss_pct"}
ORDER = ["excellent", "good", "fair", "poor"]


def rate(metric: str, v: float | None) -> str:
    if v is None:
        return "unknown"
    for lim, label in BANDS[metric]:
        if (v <= lim) if metric in LOWER_IS_BETTER else (v >= lim):
            return label
    return "poor"


def overall(m: dict) -> tuple[str, list[str]]:
    if not m.get("connected"):
        return "disconnected", []
    rated = {k: rate(k, m.get(k)) for k in BANDS if m.get(k) is not None}
    if not rated:
        return "unknown", []
    worst = max(rated.values(), key=ORDER.index)
    return worst, [k for k, v in rated.items() if v == worst]
