from __future__ import annotations

CAUSES = ["capacity_congestion", "overshooting_coverage", "external_interference", "hardware_fault"]

READ_ONLY_CHECKS = {
    "neighbour_load": "Load and spare capacity of the offload neighbour",
    "timing_advance_distribution": "Share of users far from the site (overshoot indicator)",
    "ul_interference_scan": "Uplink RSSI per PRB to locate external interference",
    "vswr_and_power_readback": "Radio unit VSWR and output-power readback",
    "config_vs_plan": "Running radio config compared with the planned values",
    "handover_stats": "Handover success towards the main neighbours",
}

ACTIONS = {
    "adjust_tx_power": {"param": "tx_power_dbm", "max_step": 3.0, "bounds": (37.0, 46.0)},
    "adjust_tilt": {"param": "tilt_deg", "max_step": 2.0, "bounds": (0.0, 12.0)},
    "no_config_change": {"param": None},
}

FITS = {
    "capacity_congestion": {"adjust_tx_power", "adjust_tilt", "no_config_change"},
    "overshooting_coverage": {"adjust_tilt", "adjust_tx_power", "no_config_change"},
    "external_interference": {"no_config_change"},
    "hardware_fault": {"no_config_change"},
}

DEPARTMENTS = {
    "config": "RAN Optimisation",
    "external_interference": "RF Engineering",
    "hardware_fault": "Field Operations",
    "data_quality": "NOC Data Platform",
    "escalation": "NOC Shift Lead",
    "regulatory": "Regulatory Compliance",
}

TARGETS = {
    "capacity_congestion": ("prb_util", 85.0),
    "overshooting_coverage": ("far_user_share", 0.15),
}


def department_for(cause: str, action_type: str) -> str:
    if action_type in ("adjust_tx_power", "adjust_tilt"):
        return DEPARTMENTS["config"]
    return DEPARTMENTS.get(cause, DEPARTMENTS["escalation"])


def _rule(name: str, ok: bool | None, reason: str) -> dict:
    status = "N/A" if ok is None else ("PASS" if ok else "FAIL")
    return {"rule": name, "status": status, "reason": reason}


def validate_plan(plan: dict, incident: dict, running: dict, evidence_ids: set[str], sandbox: dict | None,
                  sandbox_error: str | None = None) -> dict:
    rules = []
    action = plan.get("action") or {}
    atype = action.get("type")
    spec = ACTIONS.get(atype)
    cause = plan.get("cause")
    is_config = bool(spec and spec["param"])

    rules.append(_rule("Action in allow-list", spec is not None,
                       f"{atype} is allowed" if spec else f"'{atype}' is not in the action catalogue"))
    rules.append(_rule("Targets the incident cell", action.get("cell_id") == incident["cell_id"] or not is_config,
                       f"target {action.get('cell_id')}"))
    rules.append(_rule("Fits the diagnosis", cause in FITS and atype in FITS.get(cause, set()),
                       f"{atype} for {cause}" if cause in FITS else f"unknown cause '{cause}'"))

    if is_config:
        try:
            delta = float(action.get("delta"))
        except (TypeError, ValueError):
            delta = None
        param = spec["param"]
        cur = float(running.get(param, 0))
        if delta is None:
            rules.append(_rule("Step within limit", False, "no numeric delta given"))
            rules.append(_rule("Result within bounds", False, "no numeric delta given"))
        else:
            rules.append(_rule("Step within limit", 0 < abs(delta) <= spec["max_step"],
                               f"{delta:+.1f} vs limit ±{spec['max_step']:.0f} per step"))
            new = cur + delta
            lo, hi = spec["bounds"]
            rules.append(_rule("Result within bounds", lo <= new <= hi, f"{cur:.1f} → {new:.1f} (allowed {lo:.0f}–{hi:.0f})"))
        rb = plan.get("rollback") or {}
        try:
            rb_ok = abs(float(rb.get("restore_value")) - cur) < 1e-6 and bool(rb.get("trigger"))
        except (TypeError, ValueError):
            rb_ok = False
        rules.append(_rule("Rollback restores current value", rb_ok,
                           f"restore {rb.get('restore_value')} (running {cur:.1f}), trigger: {rb.get('trigger') or 'missing'}"))
    else:
        for n in ("Step within limit", "Result within bounds", "Rollback restores current value"):
            rules.append(_rule(n, None, "no configuration change"))

    checks = [c for c in plan.get("prerequisite_checks") or [] if c in READ_ONLY_CHECKS]
    rules.append(_rule("Read-only checks first", len(checks) >= 1,
                       ", ".join(checks) if checks else "no recognised read-only checks"))
    cited = set(plan.get("evidence_ids") or [])
    unknown = cited - evidence_ids
    rules.append(_rule("Evidence cited", bool(cited) and not unknown,
                       f"cites {', '.join(sorted(cited)) or 'nothing'}" + (f"; unknown {', '.join(sorted(unknown))}" if unknown else "")))

    simulated = True
    if is_config:
        if sandbox_error:
            simulated = False
            rules.append({"rule": "Sandbox impact", "status": "NOT_RUN", "reason": sandbox_error})
        elif sandbox:
            reasons, ok = [], True
            if sandbox["coverage_loss_pct"] > sandbox["limits"]["coverage_loss_pct"]:
                ok = False
                reasons.append(f"coverage loss {sandbox['coverage_loss_pct']}% > {sandbox['limits']['coverage_loss_pct']}%")
            if (sandbox.get("neighbour_after_prb") or 0) > sandbox["limits"]["neighbour_prb"]:
                ok = False
                reasons.append(f"neighbour load {sandbox['neighbour_after_prb']}% > {sandbox['limits']['neighbour_prb']}%")
            tgt = TARGETS.get(cause)
            if tgt:
                k, lim = tgt
                after = sandbox["after"][k]
                if after > lim:
                    ok = False
                    reasons.append(f"{k} still {after} after change (target ≤ {lim})")
            rules.append(_rule("Sandbox impact", ok, "; ".join(reasons) or
                               f"coverage loss {sandbox['coverage_loss_pct']}%, neighbour {sandbox.get('neighbour_after_prb')}%"))
    else:
        rules.append(_rule("Sandbox impact", None, "no configuration change"))

    failed = [r for r in rules if r["status"] == "FAIL"]
    return {
        "passed": not failed and simulated,
        "simulated": simulated,
        "failed": [r["rule"] for r in failed],
        "rules": rules,
        "summary": (f"PASSED {sum(r['status'] == 'PASS' for r in rules)} of "
                    f"{sum(r['status'] in ('PASS', 'FAIL') for r in rules)}") if not failed else f"{len(failed)} rule(s) failed",
    }
