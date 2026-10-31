from __future__ import annotations

import copy
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

KPI_NAMES = [
    "active_users", "prb_util", "dl_thpt_mbps", "cqi", "sinr_db",
    "ul_rssi_dbm", "drop_rate", "ho_success", "far_user_share", "availability",
]
KPI_UNITS = {
    "active_users": "users", "prb_util": "%", "dl_thpt_mbps": "Mbps", "cqi": "index",
    "sinr_db": "dB", "ul_rssi_dbm": "dBm", "drop_rate": "%", "ho_success": "%",
    "far_user_share": "ratio", "availability": "%",
}
FAULT_TYPES = ["capacity_surge", "interference", "overshoot", "hardware", "data_dropout"]

SITES = [
    ("Downtown", 0.0, 0.0, "98101"), ("Belltown", -1.2, 1.1, "98121"), ("Pioneer Square", 0.3, -1.4, "98104"),
    ("South Lake Union", 0.4, 2.3, "98109"), ("Capitol Hill", 1.9, 1.2, "98102"), ("First Hill", 1.4, -0.5, "98122"),
    ("Queen Anne", -1.8, 3.2, "98119"), ("SoDo", 0.2, -3.0, "98134"), ("Fremont", -1.0, 5.0, "98103"),
    ("University District", 2.6, 5.4, "98105"), ("Ballard", -3.6, 5.6, "98107"), ("Interbay", -3.4, 2.6, "98199"),
]
MARKET = {"name": "Seattle, WA", "country": "US", "timezone": "America/Los_Angeles", "tz_label": "PT",
          "regulator": "FCC"}
BANDS = [("B66 AWS-3", 20, 66786), ("B2 PCS", 15, 900), ("B71 600 MHz", 10, 68661)]
AZIMUTHS = [0, 120, 240]
SIM_START = datetime(2026, 11, 3, 19, 30)
TICK = timedelta(minutes=15)
HISTORY_TICKS = 96

POWER_REF, TILT_REF = 43.0, 4.0


@dataclass
class CellConfig:
    tx_power_dbm: float = 43.0
    tilt_deg: float = 4.0
    bandwidth_mhz: int = 20
    earfcn: int = 66786


@dataclass
class Cell:
    cell_id: str
    site: str
    sector: int
    x: float
    y: float
    azimuth: int
    base_users: float
    zip_code: str = ""
    band: str = "B66 AWS-3"
    capacity_users: float = 150.0
    config: CellConfig = field(default_factory=CellConfig)
    planned: CellConfig = field(default_factory=CellConfig)
    neighbours: list[str] = field(default_factory=list)
    offload_to: str = ""


def diurnal(t: datetime) -> float:
    h = t.hour + t.minute / 60
    return 0.35 + 0.45 * math.exp(-((h - 9) / 3.0) ** 2) + 0.65 * math.exp(-((h - 19) / 2.5) ** 2)


class NetworkSimulator:
    def __init__(self, seed: int = 7, history: bool = True):
        self.rng = np.random.default_rng(seed)
        self.lock = threading.RLock()
        self.cells: dict[str, Cell] = {}
        self.faults: dict[str, dict] = {}
        self.tick = 0
        self.now = SIM_START - TICK * HISTORY_TICKS if history else SIM_START
        self.history: dict[str, list[dict]] = {}
        self.alarms: list[dict] = []
        self._alarm_seq = 0
        self._build()
        if history:
            for _ in range(HISTORY_TICKS):
                self.step()

    def _build(self) -> None:
        n = 1
        for si, (name, sx, sy, zip_code) in enumerate(SITES):
            band, bw, earfcn = BANDS[si % len(BANDS)]
            for sec, az in enumerate(AZIMUTHS):
                cid = f"SEA-RAN-{n:03d}"
                rad = math.radians(az)
                c = Cell(
                    cell_id=cid, site=name, sector=sec + 1,
                    x=sx + 0.35 * math.sin(rad), y=sy + 0.35 * math.cos(rad), azimuth=az,
                    base_users=float(self.rng.uniform(55, 85)), zip_code=zip_code, band=band,
                    config=CellConfig(bandwidth_mhz=bw, earfcn=earfcn),
                    planned=CellConfig(bandwidth_mhz=bw, earfcn=earfcn),
                )
                self.cells[cid] = c
                self.history[cid] = []
                n += 1
        ids = list(self.cells)
        for cid, c in self.cells.items():
            others = [o for o in ids if self.cells[o].site != c.site]
            others.sort(key=lambda o: (self.cells[o].x - c.x) ** 2 + (self.cells[o].y - c.y) ** 2)
            same_site = [o for o in ids if self.cells[o].site == c.site and o != c.cell_id]
            c.neighbours = others[:3] + same_site
            c.offload_to = others[0]

    def inject_fault(self, cell_id: str, fault_type: str, severity: int = 2) -> dict:
        if fault_type not in FAULT_TYPES:
            raise ValueError(f"unknown fault type {fault_type}")
        if cell_id not in self.cells:
            raise ValueError(f"unknown cell {cell_id}")
        severity = max(1, min(3, int(severity)))
        with self.lock:
            fault = {"type": fault_type, "severity": severity, "started": self.now.isoformat(), "tick": self.tick}
            self.faults[cell_id] = fault
            cell = self.cells[cell_id]
            if fault_type == "overshoot":
                cell.config.tilt_deg = {1: 2.0, 2: 1.0, 3: 0.0}[severity]
            if fault_type == "hardware":
                self._raise_alarm(cell_id, "VSWR_HIGH", "major", "Antenna port 1 VSWR above threshold (2.4:1)")
                self._raise_alarm(cell_id, "RU_TX_POWER_LOW", "major", "Radio unit output power 6 dB below configured")
            if fault_type == "data_dropout":
                self._raise_alarm(cell_id, "PM_FILE_MISSING", "warning", "Performance file not received from collector")
            return fault

    def clear_fault(self, cell_id: str) -> None:
        with self.lock:
            self.faults.pop(cell_id, None)
            for a in self.alarms:
                if a["cell_id"] == cell_id and a["cleared"] is None:
                    a["cleared"] = self.now.isoformat()

    def clear_all(self) -> None:
        with self.lock:
            for cid in list(self.faults):
                self.clear_fault(cid)
            for c in self.cells.values():
                c.config = copy.deepcopy(c.planned)

    def _raise_alarm(self, cell_id: str, code: str, severity: str, text: str) -> None:
        for a in self.alarms:
            if a["cell_id"] == cell_id and a["code"] == code and a["cleared"] is None:
                return
        self._alarm_seq += 1
        self.alarms.append({
            "alarm_id": f"ALM-{self._alarm_seq:05d}", "cell_id": cell_id, "code": code,
            "severity": severity, "description": text, "raised": self.now.isoformat(), "cleared": None,
        })

    def _footprint(self, c: Cell) -> float:
        f = self.faults.get(c.cell_id)
        power = c.config.tx_power_dbm - (6.0 if f and f["type"] == "hardware" else 0.0)
        val = 1 + 0.07 * (power - POWER_REF) - 0.06 * (c.config.tilt_deg - TILT_REF)
        return float(min(1.5, max(0.5, val)))

    def step(self) -> None:
        with self.lock:
            self.now += TICK
            self.tick += 1
            d = diurnal(self.now)
            demand, foot = {}, {}
            for cid, c in self.cells.items():
                f = self.faults.get(cid)
                normal = c.base_users * d
                if f and f["type"] == "capacity_surge":
                    normal = max(normal, {1: 135.0, 2: 150.0, 3: 170.0}[f["severity"]])
                demand[cid] = normal * float(self.rng.normal(1, 0.04))
                foot[cid] = self._footprint(c)
            served = {cid: demand[cid] * foot[cid] for cid in self.cells}
            for cid, c in self.cells.items():
                served[c.offload_to] += demand[cid] * (1 - foot[cid])
            for cid, c in self.cells.items():
                served[cid] = max(1.0, served[cid])

            rows = {}
            for cid, c in self.cells.items():
                f = self.faults.get(cid)
                ftype = f["type"] if f else None
                sev = f["severity"] if f else 0
                interf = {1: 6.0, 2: 9.0, 3: 12.0}[sev] if ftype == "interference" else 0.0
                leak = sum(max(0.0, foot[n] - 1.05) * 8 for n in c.neighbours if n in foot)
                sinr = 13.0 - interf - leak - (2.0 if foot[cid] > 1.1 else 0.0) + float(self.rng.normal(0, 0.5))
                cqi = float(np.clip(5.5 + 0.38 * sinr, 1, 15))
                eff_penalty = 1 + 0.05 * max(0.0, 13.0 - sinr)
                prb = float(min(100.0, served[cid] / c.capacity_users * 100 * eff_penalty))
                cap = 300.0 * (cqi / 15) * (0.6 if ftype == "hardware" else 1.0)
                thpt = cap / max(1.0, served[cid] * 0.35) * (min(1.0, 92 / prb) if prb > 92 else 1.0)
                neighbour_prb_guess = served[c.offload_to] / self.cells[c.offload_to].capacity_users * 100
                drop = (0.4 + 2.5 * max(0.0, (prb - 85) / 15) + 1.5 * max(0.0, (8 - sinr) / 8)
                        + (2.0 if ftype == "hardware" else 0.0) + float(self.rng.normal(0, 0.05)))
                ho = (99.3 - 4 * max(0.0, (neighbour_prb_guess - 88) / 12) - 6 * max(0.0, 0.82 - foot[cid])
                      - 3 * max(0.0, foot[cid] - 1.15) + float(self.rng.normal(0, 0.1)))
                far = 0.08 + 0.6 * max(0.0, foot[cid] - 1.0) + float(self.rng.normal(0, 0.005))
                rssi = -105 + interf * 1.2 + float(self.rng.normal(0, 0.4))
                row = {
                    "ts": self.now.isoformat(), "tick": self.tick, "cell_id": cid,
                    "active_users": round(served[cid], 1), "prb_util": round(prb, 1),
                    "dl_thpt_mbps": round(thpt, 2), "cqi": round(cqi, 2), "sinr_db": round(sinr, 2),
                    "ul_rssi_dbm": round(rssi, 1), "drop_rate": round(max(0.05, drop), 2),
                    "ho_success": round(min(100.0, ho), 2), "far_user_share": round(max(0.0, far), 3),
                    "availability": 99.2 if ftype == "hardware" else 100.0,
                }
                if ftype == "data_dropout":
                    row = {"ts": self.now.isoformat(), "tick": self.tick, "cell_id": cid, "missing": True}
                rows[cid] = row
                if prb > 90 and ftype != "data_dropout":
                    self._raise_alarm(cid, "HIGH_LOAD", "warning", "PRB utilisation above 90% for 15 min")
                if rssi > -96:
                    self._raise_alarm(cid, "UL_INTERFERENCE", "minor", "Uplink RSSI above -96 dBm")
            for cid, row in rows.items():
                h = self.history[cid]
                h.append(row)
                if len(h) > 400:
                    del h[: len(h) - 400]

    def latest(self, cell_id: str) -> dict | None:
        h = self.history.get(cell_id) or []
        return h[-1] if h else None

    def window(self, cell_id: str, ticks: int = 12) -> list[dict]:
        return list(self.history.get(cell_id, [])[-ticks:])

    def active_alarms(self, cell_id: str | None = None, include_cleared_ticks: int = 24) -> list[dict]:
        out = []
        for a in self.alarms:
            if cell_id and a["cell_id"] != cell_id:
                continue
            out.append(a)
        return out[-20:]

    def cell_info(self, cell_id: str) -> dict:
        c = self.cells[cell_id]
        return {
            "cell_id": c.cell_id, "site": c.site, "sector": c.sector, "azimuth": c.azimuth,
            "zip_code": c.zip_code, "band": c.band,
            "x": round(c.x, 3), "y": round(c.y, 3), "neighbours": c.neighbours,
            "offload_neighbour": c.offload_to,
        }


def training_rows(days: int = 7, seed: int = 11) -> list[dict]:
    sim = NetworkSimulator(seed=seed, history=False)
    rows = []
    for _ in range(days * 96):
        sim.step()
        for cid in sim.cells:
            rows.append(sim.latest(cid))
    return rows


def training_matrix(days: int = 7, seed: int = 11) -> np.ndarray:
    from .detection import features
    return np.array([features(r) for r in training_rows(days, seed)])
