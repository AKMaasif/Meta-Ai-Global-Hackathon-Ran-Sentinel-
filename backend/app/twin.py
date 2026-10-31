from __future__ import annotations

import copy
import threading

import httpx
import numpy as np

from . import maveric
from .maveric import RadpClient, RadpError
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

    def __init__(self, url: str, fallback: FallbackTwin, model_id: str = "ran-sentinel-seattle",
                 timeout: float = 90.0, client: RadpClient | None = None):
        self.url = url.rstrip("/")
        self.fallback = fallback
        self.model_id = model_id
        self.timeout = timeout
        self.client = client or RadpClient(self.url)
        self.last_error = ""

    def available(self) -> bool:
        return self.client.reachable()

    def status(self) -> dict:
        if not self.available():
            return {"reachable": False, "trained": False}
        try:
            return {"reachable": True, "trained": bool(self.client.model_trained(self.model_id)), "model_id": self.model_id}
        except (RadpError, httpx.HTTPError):
            return {"reachable": True, "trained": False, "model_id": self.model_id}

    def simulate(self, cell_id: str, changes: dict[str, float]) -> dict:
        result = self.fallback.simulate(cell_id, changes)
        st = self.status()
        if not st["reachable"]:
            result["engine"] = self.fallback.name + " (Maveric not reachable)"
            return result
        if not st["trained"]:
            result["engine"] = self.fallback.name + " (Maveric model not trained: run scripts/maveric_setup.py)"
            return result
        try:
            with self.fallback.sim.lock:
                cells = copy.deepcopy(self.fallback.sim.cells)
            rf = maveric.what_if(self.client, self.model_id, cells, cell_id, changes, self.timeout)
        except (RadpError, httpx.HTTPError, KeyError, ValueError, StopIteration) as e:
            self.last_error = str(e)[:200]
            result["engine"] = self.fallback.name + f" (Maveric failed: {self.last_error})"
            return result
        result["engine"] = "Maveric RF twin (coverage) + simulator copy (load)"
        # stricter of the two, so maveric never loosens the gate
        result["coverage_loss_pct"] = max(rf["coverage_loss_pct"], result["coverage_loss_pct"])
        result["rf"] = rf
        return result


def make_twin(sim: NetworkSimulator, maveric_url: str, model_id: str = "ran-sentinel-seattle", timeout: float = 90.0):
    fb = FallbackTwin(sim)
    return (MavericTwin(maveric_url, fb, model_id, timeout) if maveric_url else fb), fb
