from __future__ import annotations

from statistics import mean

from .detection import forecast
from .mplane import MPlaneClient
from .safety import READ_ONLY_CHECKS
from .simulator import KPI_NAMES, KPI_UNITS, NetworkSimulator

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_anomaly_result",
        "description": "Detector output that opened this incident: score, threshold, breached rules and top contributing KPIs.",
        "parameters": {"type": "object", "properties": {"incident_id": {"type": "string"}}, "required": ["incident_id"]}}},
    {"type": "function", "function": {
        "name": "get_kpi_window",
        "description": "Recent KPI values for a cell (15-minute windows) with a 1-hour trend forecast per metric.",
        "parameters": {"type": "object", "properties": {
            "cell_id": {"type": "string"},
            "metrics": {"type": "array", "items": {"type": "string", "enum": KPI_NAMES}},
            "windows": {"type": "integer", "minimum": 2, "maximum": 24}},
            "required": ["cell_id", "metrics"]}}},
    {"type": "function", "function": {
        "name": "get_alarm_history",
        "description": "Alarms raised on a cell, including cleared ones.",
        "parameters": {"type": "object", "properties": {"cell_id": {"type": "string"}}, "required": ["cell_id"]}}},
    {"type": "function", "function": {
        "name": "get_cell_configuration",
        "description": "Running radio configuration read over O-RAN M-Plane (get-config), compared with the planned values.",
        "parameters": {"type": "object", "properties": {"cell_id": {"type": "string"}}, "required": ["cell_id"]}}},
    {"type": "function", "function": {
        "name": "run_diagnostic_check",
        "description": "Run one approved read-only diagnostic check. Checks: " + "; ".join(f"{k}: {v}" for k, v in READ_ONLY_CHECKS.items()),
        "parameters": {"type": "object", "properties": {
            "check": {"type": "string", "enum": list(READ_ONLY_CHECKS)}, "cell_id": {"type": "string"}},
            "required": ["check", "cell_id"]}}},
]


class ToolError(Exception):
    pass


class Toolbox:
    def __init__(self, sim: NetworkSimulator, mplane: MPlaneClient):
        self.sim = sim
        self.mplane = mplane
        self.diag_outage = False

    def run(self, name: str, args: dict, incident: dict) -> dict:
        fn = getattr(self, "_" + name, None)
        if fn is None or name not in {t["function"]["name"] for t in TOOL_SPECS}:
            raise ToolError(f"unknown tool {name}")
        if "cell_id" in args:
            allowed = {incident["cell_id"], *self.sim.cells[incident["cell_id"]].neighbours}
            if args["cell_id"] not in allowed:
                raise ToolError(f"cell {args['cell_id']} is outside this incident's scope")
        result = fn(args, incident)
        result.setdefault("observed_at", self.sim.now.isoformat())
        return result

    def _get_anomaly_result(self, args, incident):
        if args.get("incident_id") not in (incident["id"], None):
            raise ToolError("incident_id does not match the current incident")
        return {"source": "ML detector", **incident["detection"]}

    def _get_kpi_window(self, args, incident):
        metrics = [m for m in args.get("metrics") or [] if m in KPI_NAMES] or ["prb_util", "drop_rate", "sinr_db"]
        n = max(2, min(24, int(args.get("windows") or 8)))
        rows = self.sim.window(args["cell_id"], n)
        valid = [r for r in rows if not r.get("missing")]
        series = {m: [r[m] for r in valid] for m in metrics}
        return {
            "source": "PM counters (simulated)", "cell_id": args["cell_id"], "windows": n,
            "missing_windows": len(rows) - len(valid),
            "timestamps": [r["ts"][11:16] for r in valid],
            "series": series, "units": {m: KPI_UNITS[m] for m in metrics},
            "forecast_1h": {m: (round(v, 2) if (v := forecast(series[m])) is not None else None) for m in metrics},
        }

    def _get_alarm_history(self, args, incident):
        alarms = self.sim.active_alarms(args["cell_id"])
        return {"source": "fault management (simulated)", "cell_id": args["cell_id"], "alarms": alarms,
                "active_count": sum(a["cleared"] is None for a in alarms)}

    def _get_cell_configuration(self, args, incident):
        cfg = self.mplane.get_config(args["cell_id"])
        cfg = {k: v for k, v in cfg.items() if k != "netconf_reply"}
        return {**cfg, "site": self.sim.cells[args["cell_id"]].site}

    def _run_diagnostic_check(self, args, incident):
        check, cid = args["check"], args["cell_id"]
        if self.diag_outage:
            raise ToolError("diagnostics service unavailable (timeout)")
        if check not in READ_ONLY_CHECKS:
            raise ToolError(f"check {check} is not approved")
        cell = self.sim.cells[cid]
        latest = self.sim.latest(cid) or {}
        recent = [r for r in self.sim.window(cid, 8) if not r.get("missing")]
        fault = self.sim.faults.get(cid, {})
        if check == "neighbour_load":
            out = []
            for n in cell.neighbours:
                r = self.sim.latest(n) or {}
                out.append({"cell_id": n, "prb_util": r.get("prb_util"), "active_users": r.get("active_users"),
                            "is_offload_target": n == cell.offload_to})
            res = {"neighbours": out}
        elif check == "timing_advance_distribution":
            nbr = [self.sim.latest(n) for n in cell.neighbours]
            res = {"far_user_share_now": latest.get("far_user_share"),
                   "far_user_share_8w_mean": round(mean(r["far_user_share"] for r in recent), 3) if recent else None,
                   "neighbour_mean_far_share": round(mean(r["far_user_share"] for r in nbr if r and not r.get("missing")), 3),
                   "reference": "typical 0.06-0.10"}
        elif check == "ul_interference_scan":
            rssi = latest.get("ul_rssi_dbm")
            elevated = rssi is not None and rssi > -101
            res = {"ul_rssi_dbm": rssi, "noise_floor_reference_dbm": -105,
                   "prb_profile": "elevated across PRBs 20-38 (narrowband, external-looking)" if elevated else "flat, at noise floor"}
        elif check == "vswr_and_power_readback":
            hw = fault.get("type") == "hardware"
            res = {"vswr": 2.4 if hw else 1.2, "vswr_limit": 1.5,
                   "output_power_vs_configured_db": -6.0 if hw else 0.0}
        elif check == "config_vs_plan":
            cfg = self.mplane.get_config(cid)
            res = {"deviations_from_plan": cfg["deviations_from_plan"], "running": cfg["running"], "planned": cfg["planned"]}
        else:
            res = {"ho_success_now": latest.get("ho_success"),
                   "ho_success_8w_mean": round(mean(r["ho_success"] for r in recent), 2) if recent else None,
                   "main_target": cell.offload_to}
        return {"source": f"diagnostic check: {check}", "check": check, "cell_id": cid, **res}
