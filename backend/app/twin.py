from __future__ import annotations

import copy
import threading

import httpx
import numpy as np

from .simulator import NetworkSimulator

COVERAGE_LOSS_LIMIT_PCT = 1.0
NEIGHBOUR_PRB_LIMIT = 85.0


class TwinUnavailable(Exception):
    pass


def coverage_loss_pct(footprint: float) -> float:
    return round(max(0.0, 0.75 - footprint) * 35.0, 2)


class FallbackTwin:
    name = "fallback twin (simulator copy)"

    def __init__(self, sim: NetworkSimulator):
        self.sim = sim
        self.force_outage = False

    def simulate(self, cell_id: str, changes: dict[str, float]) -> dict:
        if self.force_outage:
            raise TwinUnavailable("twin service did not respond (demo outage switch)")
        with self.sim.lock:
            base = self._clone()
            test = self._clone()
        for k, v in changes.items():
            setattr(test.cells[cell_id].config, k, float(v))
        base.step()
        test.step()
        nb = test.cells[cell_id].offload_to
        b, a = base.latest(cell_id), test.latest(cell_id)
        bn, an = base.latest(nb), test.latest(nb)
        if b.get("missing") or a.get("missing"):
            raise TwinUnavailable("no KPI baseline for this cell (data missing)")
        foot = test._footprint(test.cells[cell_id])
        moved = max(0.0, (b["active_users"] - a["active_users"]) / max(1.0, b["active_users"]) * 100)
        return {
            "engine": self.name, "cell_id": cell_id, "changes": changes, "neighbour": nb,
            "before": {k: b[k] for k in ("prb_util", "drop_rate", "far_user_share", "sinr_db", "ho_success")},
            "after": {k: a[k] for k in ("prb_util", "drop_rate", "far_user_share", "sinr_db", "ho_success")},
            "neighbour_before_prb": bn.get("prb_util"), "neighbour_after_prb": an.get("prb_util"),
            "users_moved_pct": round(moved, 1), "coverage_loss_pct": coverage_loss_pct(foot),
            "limits": {"coverage_loss_pct": COVERAGE_LOSS_LIMIT_PCT, "neighbour_prb": NEIGHBOUR_PRB_LIMIT},
        }

    def _clone(self) -> NetworkSimulator:
        clone = copy.copy(self.sim)
        clone.cells = copy.deepcopy(self.sim.cells)
        clone.faults = copy.deepcopy(self.sim.faults)
        clone.history = {k: list(v[-2:]) for k, v in self.sim.history.items()}
        clone.alarms = []
        clone.rng = np.random.default_rng(1234)
        clone.lock = threading.RLock()
        clone.now = self.sim.now
        clone.tick = self.sim.tick
        return clone


class MavericTwin:
    name = "Maveric RADP"

    def __init__(self, url: str, fallback: FallbackTwin):
        self.url = url.rstrip("/")
        self.fallback = fallback

    def available(self) -> bool:
        try:
            r = httpx.get(self.url, timeout=2)
            return r.status_code < 500
        except httpx.HTTPError:
            return False

    def simulate(self, cell_id: str, changes: dict[str, float]) -> dict:
        result = self.fallback.simulate(cell_id, changes)
        result["engine"] = self.fallback.name + (" (Maveric reachable, adapter pending)" if self.available() else " (Maveric not reachable)")
        return result


def make_twin(sim: NetworkSimulator, maveric_url: str):
    fb = FallbackTwin(sim)
    return (MavericTwin(maveric_url, fb) if maveric_url else fb), fb
