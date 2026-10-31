from __future__ import annotations

import json

from .agents import CONFIRMING_CHECK, SUPPORT, UNTRUSTED, AgentContext, AgentOutputError, _evidence_brief, _llm_json
from .providers import ProviderError
from .safety import CAUSES, READ_ONLY_CHECKS

FAULT_TO_CAUSE = {"capacity_surge": "capacity_congestion", "interference": "external_interference",
                  "overshoot": "overshooting_coverage", "hardware": "hardware_fault"}


def _kpi(*metrics):
    def has(ev):
        return any(e["tool"] == "get_kpi_window" and any((e["result"]["series"].get(m) or []) for m in metrics) for e in ev)
    return has


def _tool(name):
    return lambda ev: any(e["tool"] == name for e in ev)


def _check(*names):
    return lambda ev: any(e["tool"] == "run_diagnostic_check" and e["args"].get("check") in names for e in ev)


def _any(*fns):
    return lambda ev: any(f(ev) for f in fns)


COMMON = [("detector", "Detector result read", _tool("get_anomaly_result"), "get_anomaly_result"),
          ("alarms", "Alarm history reviewed", _tool("get_alarm_history"), "get_alarm_history")]
# id, what to see, test, what to fetch
PLAYBOOK = {
    "capacity_congestion": [
        ("load", "Cell load measured (PRB utilisation)", _kpi("prb_util"), "get_kpi_window"),
        ("quality", "Radio quality measured, so interference can be ruled out", _kpi("sinr_db", "cqi"), "get_kpi_window"),
        ("neighbour", "Offload neighbour headroom checked", _check("neighbour_load"), "neighbour_load")],
    "overshooting_coverage": [
        ("far_users", "Share of far users measured", _any(_kpi("far_user_share"), _check("timing_advance_distribution")),
         "timing_advance_distribution"),
        ("plan", "Running tilt compared with the radio plan", _check("config_vs_plan"), "config_vs_plan")],
    "external_interference": [
        ("rssi", "Uplink noise (UL RSSI) measured", _kpi("ul_rssi_dbm"), "get_kpi_window"),
        ("quality", "SINR or CQI measured", _kpi("sinr_db", "cqi"), "get_kpi_window"),
        ("scan", "Uplink interference scan run", _check("ul_interference_scan"), "ul_interference_scan")],
    "hardware_fault": [
        ("vswr", "Radio unit VSWR and power read back", _check("vswr_and_power_readback"), "vswr_and_power_readback"),
        ("impact", "Service impact measured (drops or availability)", _kpi("drop_rate", "availability"), "get_kpi_window")],
}


def coverage(evidence: list[dict], cause: str, on_site: bool = False) -> dict:
    ok = [e for e in evidence if e["result"] is not None]
    items = [{"id": i, "item": text + (" (field report)" if on_site and fetch == CONFIRMING_CHECK.get(cause) and not test(ok) else ""),
              "covered": bool(test(ok)) or (on_site and fetch == CONFIRMING_CHECK.get(cause)), "fetch": fetch}
             for i, text, test, fetch in COMMON + PLAYBOOK.get(cause, [])]
    n = sum(i["covered"] for i in items)
    return {"cause": cause, "items": items, "covered": n, "total": len(items),
            "score": round(n / len(items), 2) if items else 1.0}


def _values(obj, metric):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == metric:
                out.extend(v if isinstance(v, list) else [v])
            elif isinstance(v, (dict, list)):
                out.extend(_values(v, metric))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_values(v, metric))
    return out


def check_fact(evidence: list[dict], fact: dict) -> str | None:
    eid, metric, value = fact.get("evidence_id"), str(fact.get("metric") or ""), fact.get("value")
    e = next((x for x in evidence if x["id"] == eid), None)
    if e is None or e["result"] is None:
        return f"{eid} is not a successful evidence item"
    found = _values(e["result"], metric)
    if not found:
        return f"{eid} has no '{metric}'"
    for v in found:
        if isinstance(value, bool) or isinstance(v, bool):
            if value == v:
                return None
        elif isinstance(value, (int, float)) and isinstance(v, (int, float)):
            if abs(v - value) <= max(abs(v) * 0.02, 0.05):
                return None
        elif str(value).strip().lower() in str(v).lower():
            return None
    shown = ", ".join(str(v) for v in found[-4:])
    return f"{eid} {metric} is {shown}, not {value}"


def _rule(name, ok, reason, status=None):
    return {"rule": name, "status": status or ("PASS" if ok else "FAIL"), "reason": reason}


def check(ctx: AgentContext, diag: dict, claims_models: list[str] | None = None) -> dict:
    evidence = ctx.evidence()
    hyps = diag["hypotheses"]
    top, second = hyps[0], (hyps[1] if len(hyps) > 1 else None)
    cause = top["cause"]
    ok_ids = {e["id"] for e in evidence if e["result"] is not None}
    rules, feedback = [], []
    field = {e["id"] for e in evidence if e["tool"] == "field_report" and e["result"] is not None}
    on_site = bool(field & set(top.get("supporting_evidence") or []))

    cov = coverage(evidence, cause, on_site)
    missing = [i for i in cov["items"] if not i["covered"]]
    rules.append(_rule("Playbook coverage", not missing, f"{cov['covered']} of {cov['total']} items" +
                       (f"; missing: {'; '.join(i['item'] for i in missing)}" if missing else "")))
    if missing:
        feedback.append("Evidence is incomplete. Still needed: " + "; ".join(i["item"] for i in missing) + ".")

    facts = diag.get("key_facts") or []
    bad = [(f, r) for f in facts if (r := check_fact(evidence, f))]
    rules.append(_rule("Facts match the evidence", facts and not bad,
                       f"{len(facts) - len(bad)} of {len(facts)} facts found in the evidence" +
                       (f"; refused: {'; '.join(r for _, r in bad)}" if bad else "") if facts else "no key facts stated"))
    if bad or not facts:
        feedback.append("State 1-5 key facts copied exactly from the evidence." +
                        (" These were not in the evidence: " + "; ".join(r for _, r in bad) + "." if bad else ""))

    rules.append(_rule("Known cause", cause in CAUSES, cause))
    cited = set(top.get("supporting_evidence") or []) & ok_ids
    rules.append(_rule("Top cause backed by evidence", top["support"] in ("strong", "moderate") and bool(cited),
                       f"{top['support']} support, cites {', '.join(sorted(cited)) or 'nothing'}"))
    confirm = CONFIRMING_CHECK.get(cause)
    ran = {e["args"].get("check") for e in evidence if e["tool"] == "run_diagnostic_check" and e["result"] is not None}
    rules.append(_rule("Confirming check run", confirm in ran or on_site,
                       (confirm or "-") + (" (stood in for by the field report)" if on_site and confirm not in ran else "")))
    if confirm and confirm not in ran and not on_site and not any(i["fetch"] == confirm for i in missing):
        missing.append({"item": f"Confirming check {confirm}", "fetch": confirm})
    margin = second is None or SUPPORT.index(top["support"]) < SUPPORT.index(second["support"])
    rules.append(_rule("Clear margin over the runner-up", margin,
                       f"{top['support']} vs {second['support']} ({second['cause']})" if second else "only one cause"))
    if not margin:
        feedback.append("The top two causes are equally supported. Find evidence that separates them.")
    weighed = [h["cause"] for h in hyps[1:] if set(h.get("contradicting_evidence") or []) & ok_ids]
    rules.append(_rule("Alternatives weighed against evidence", bool(weighed),
                       f"evidence cited against {', '.join(weighed)}" if weighed else "no alternative cause has counter-evidence"))
    if not weighed:
        feedback.append("Cite evidence against at least one alternative cause.")

    claims = _claims(ctx, diag, claims_models)
    rules.append(claims["rule"])
    if claims["unsupported"]:
        feedback.append("These claims are not backed by the evidence: " +
                        "; ".join(c.get("claim", "") for c in claims["unsupported"]) + ".")

    checklist = ctx.incident.get("checklist") or []
    counter = any(i.get("counter_evidence") for i in checklist)
    rules.append(_rule("Investigation checklist", True, f"{len(checklist)} items" + (", includes counter-evidence" if counter else ""),
                       status="PASS" if 4 <= len(checklist) <= 8 and counter else "WARN"))

    failed = [r["rule"] for r in rules if r["status"] == "FAIL"]
    return {"passed": not failed, "failed": failed, "rules": rules, "coverage": cov, "feedback": feedback,
            "fetch": sorted({i["fetch"] for i in missing}), "claims": claims["unsupported"], "claims_by": claims["by"],
            "facts": [{**f, "verified": check_fact(evidence, f) is None} for f in facts], "cause": cause}


def _claims(ctx: AgentContext, diag: dict, models: list[str] | None) -> dict:
    if ctx.offline or not models:
        return {"rule": _rule("Claims check", True, "offline mode: no claims model", status="NOT_RUN"), "unsupported": [], "by": None}

    def validate(d):
        u = d.get("unsupported_claims")
        if not isinstance(u, list) or any(not isinstance(c, dict) or not c.get("claim") for c in u):
            return ["'unsupported_claims' must be a list of {claim, why}"]
        return []

    system = ("You are the Claims Checker in RAN Sentinel. Read the analyst's diagnosis and the evidence. List every "
              "statement about the network that the evidence does not back: a number not in the evidence, a trend the data "
              "does not show, or an alarm that is not there. Do not judge which cause is right; only check claims against "
              "evidence. An empty list is the right answer when everything is backed. " + UNTRUSTED +
              '\nReply with only JSON: {"unsupported_claims": [{"claim": str, "why": str}]}')
    user = json.dumps({"hypotheses": [{k: h.get(k) for k in ("cause", "support", "reasoning", "supporting_evidence",
                                                             "contradicting_evidence")} for h in diag["hypotheses"][:3]],
                       "key_facts": diag.get("key_facts")}, default=str)
    try:
        d = _llm_json(ctx, "claims_checker", system, user + "\nEvidence:\n" + _evidence_brief(ctx, 1500), validate, models=models)
    except (AgentOutputError, ProviderError) as e:
        return {"rule": _rule("Claims check", True, f"claims model unavailable: {str(e)[:120]}", status="NOT_RUN"),
                "unsupported": [], "by": None}
    u = [{"claim": str(c["claim"])[:300], "why": str(c.get("why", ""))[:300]} for c in d["unsupported_claims"][:5]]
    by = (ctx.runs[-1] or {}).get("model", models[0]) if ctx.runs else models[0]
    return {"rule": _rule("Claims check", not u, f"{len(u)} unsupported claim(s)" if u else f"all claims backed ({by})"),
            "unsupported": u, "by": by}


def default_checklist() -> list[dict]:
    return [{"item": "Read the detector result and the KPI trend", "counter_evidence": False, "auto": True},
             {"item": "Review active and recent alarms", "counter_evidence": False},
             {"item": "Compare running radio config with the plan", "counter_evidence": False},
             {"item": "Run the confirming check for the leading cause", "counter_evidence": False},
             {"item": "Look for evidence against the leading cause", "counter_evidence": True}]


def mark_checklist(checklist: list[dict], evidence: list[dict], diag: dict | None) -> list[dict]:
    ok = [e for e in evidence if e["result"] is not None]
    tools = {e["tool"] for e in ok}
    checks = {e["args"].get("check") for e in ok if e["tool"] == "run_diagnostic_check"}
    top = (diag or {}).get("hypotheses", [{}])[0]
    field = {e["id"] for e in ok if e["tool"] == "field_report"} & set(top.get("supporting_evidence") or [])
    done = [{"get_anomaly_result", "get_kpi_window"} <= tools, "get_alarm_history" in tools,
            "get_cell_configuration" in tools or "config_vs_plan" in checks,
            CONFIRMING_CHECK.get(top.get("cause")) in checks or bool(field),
            any(h.get("contradicting_evidence") for h in (diag or {}).get("hypotheses", [])[1:])]
    return [{**i, "done": d} for i, d in zip(checklist, done)]


def truth_score(diag: dict, fault_type: str) -> dict:
    want = FAULT_TO_CAUSE.get(fault_type)
    got = diag["hypotheses"][0]["cause"] if diag else None
    return {"fault": fault_type, "expected": want, "diagnosed": got, "correct": got == want}


def fetch_plan(names: list[str], cell_id: str, incident_id: str) -> list[tuple[str, dict]]:
    out = []
    for n in names:
        if n in READ_ONLY_CHECKS:
            out.append(("run_diagnostic_check", {"check": n, "cell_id": cell_id}))
        elif n == "get_kpi_window":
            out.append((n, {"cell_id": cell_id, "windows": 8, "metrics": [
                "prb_util", "sinr_db", "cqi", "ul_rssi_dbm", "drop_rate", "availability", "far_user_share"]}))
        elif n == "get_anomaly_result":
            out.append((n, {"incident_id": incident_id}))
        else:
            out.append((n, {"cell_id": cell_id}))
    return out

