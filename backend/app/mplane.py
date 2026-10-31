from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from dataclasses import asdict

from .simulator import NetworkSimulator

NS = "urn:ran-sentinel:sim:o-ran-style:1.0"
# name: (xml element, allowed range)
PARAMS = {
    "tx_power_dbm": ("max-tx-power", (30.0, 46.0)),
    "tilt_deg": ("electrical-tilt", (0.0, 15.0)),
}
CONFIRM_TIMEOUT_TICKS = 6


class MPlaneError(Exception):
    pass


class MPlaneClient:
    def __init__(self, sim: NetworkSimulator):
        self.sim = sim
        self.pending: dict[str, dict] = {}
        self.log: list[dict] = []
        self.locked: set[str] = set()

    def get_config(self, cell_id: str) -> dict:
        if cell_id not in self.sim.cells:
            raise MPlaneError(f"unknown radio unit for {cell_id}")
        c = self.sim.cells[cell_id]
        running = asdict(c.config)
        planned = asdict(c.planned)
        xml = self._config_xml(cell_id, running)
        deviations = {k: {"running": running[k], "planned": planned[k]}
                      for k in running if abs(float(running[k]) - float(planned[k])) > 1e-6}
        return {
            "cell_id": cell_id, "datastore": "running", "running": running, "planned": planned,
            "deviations_from_plan": deviations, "pending_confirmed_commit": cell_id in self.pending,
            "netconf_reply": xml, "source": "M-Plane get-config (simulated radio unit)",
        }

    def _config_xml(self, cell_id: str, values: dict) -> str:
        root = ET.Element("data", {"xmlns": NS})
        ru = ET.SubElement(root, "radio-unit")
        ET.SubElement(ru, "name").text = cell_id
        tx = ET.SubElement(ru, "tx-array-carrier")
        ET.SubElement(tx, "max-tx-power").text = f"{values['tx_power_dbm']:.1f}"
        ET.SubElement(tx, "channel-bandwidth").text = str(int(values["bandwidth_mhz"]) * 1000000)
        ET.SubElement(tx, "absolute-frequency-center").text = str(values["earfcn"])
        ant = ET.SubElement(ru, "antenna")
        ET.SubElement(ant, "electrical-tilt").text = f"{values['tilt_deg']:.1f}"
        return ET.tostring(root, encoding="unicode")

    def build_change_package(self, cell_id: str, changes: dict[str, float], incident_id: str) -> dict:
        if cell_id not in self.sim.cells:
            raise MPlaneError(f"unknown radio unit for {cell_id}")
        current = asdict(self.sim.cells[cell_id].config)
        for k in changes:
            if k not in PARAMS:
                raise MPlaneError(f"parameter {k} is not managed over M-Plane")
        rpc = ET.Element("rpc", {"message-id": f"{incident_id}-1", "xmlns": "urn:ietf:params:xml:ns:netconf:base:1.0"})
        edit = ET.SubElement(rpc, "edit-config")
        tgt = ET.SubElement(edit, "target")
        ET.SubElement(tgt, "candidate")
        cfg = ET.SubElement(edit, "config")
        ru = ET.SubElement(cfg, "radio-unit", {"xmlns": NS})
        ET.SubElement(ru, "name").text = cell_id
        for k, v in changes.items():
            el = ET.SubElement(ru, PARAMS[k][0], {"operation": "merge"})
            el.text = f"{float(v):.1f}"
        commit = (f'<rpc message-id="{incident_id}-2"><validate><source><candidate/></source></validate></rpc>\n'
                  f'<rpc message-id="{incident_id}-3"><commit><confirmed/>'
                  f'<confirm-timeout>{CONFIRM_TIMEOUT_TICKS * 900}</confirm-timeout></commit></rpc>')
        rollback = {k: current[k] for k in changes}
        return {
            "cell_id": cell_id, "incident_id": incident_id, "changes": changes, "rollback_values": rollback,
            "edit_config": ET.tostring(rpc, encoding="unicode"), "commit": commit,
            "confirm_timeout_s": CONFIRM_TIMEOUT_TICKS * 900,
            "note": "Simplified O-RAN-style payload for a simulated radio unit.",
        }

    def dry_run(self, package: dict) -> dict:
        errors = []
        try:
            ET.fromstring(package["edit_config"])
        except ET.ParseError as e:
            errors.append(f"edit-config is not well-formed XML: {e}")
        cell_id = package["cell_id"]
        if cell_id in self.locked:
            errors.append("candidate datastore is locked by another session")
        if cell_id in self.pending:
            errors.append("a confirmed-commit is already pending on this radio unit")
        for k, v in package["changes"].items():
            lo, hi = PARAMS[k][1]
            if not (lo <= float(v) <= hi):
                errors.append(f"{k}={v} is outside the radio unit capability {lo}..{hi}")
        return {"ok": not errors, "errors": errors}

    def apply(self, package: dict) -> dict:
        check = self.dry_run(package)
        if not check["ok"]:
            raise MPlaneError("; ".join(check["errors"]))
        cell = self.sim.cells[package["cell_id"]]
        with self.sim.lock:
            before = copy.deepcopy(cell.config)
            for k, v in package["changes"].items():
                setattr(cell.config, k, float(v))
            self.pending[cell.cell_id] = {
                "before": before, "deadline_tick": self.sim.tick + CONFIRM_TIMEOUT_TICKS,
                "incident_id": package["incident_id"],
            }
        self._log(cell.cell_id, "commit-confirmed-started", package["changes"])
        return {"applied": package["changes"], "confirm_by_tick": self.pending[cell.cell_id]["deadline_tick"]}

    def confirm(self, cell_id: str) -> bool:
        if self.pending.pop(cell_id, None) is None:
            return False
        self._log(cell_id, "commit-confirmed", {})
        return True

    def cancel(self, cell_id: str, reason: str) -> bool:
        p = self.pending.pop(cell_id, None)
        if p is None:
            return False
        with self.sim.lock:
            self.sim.cells[cell_id].config = p["before"]
        self._log(cell_id, "cancel-commit (rolled back)", {"reason": reason})
        return True

    def on_tick(self) -> list[dict]:
        reverted = []
        for cell_id, p in list(self.pending.items()):
            if self.sim.tick >= p["deadline_tick"]:
                self.cancel(cell_id, "confirm timeout expired")
                reverted.append({"cell_id": cell_id, "incident_id": p["incident_id"]})
        return reverted

    def _log(self, cell_id: str, op: str, detail: dict) -> None:
        self.log.append({"tick": self.sim.tick, "ts": self.sim.now.isoformat(), "cell_id": cell_id, "op": op, "detail": detail})
