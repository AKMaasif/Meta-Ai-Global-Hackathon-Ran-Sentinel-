from __future__ import annotations

STATUSES = ("todo", "doing", "done", "dropped")

LABELS = {
    "get_anomaly_result": "Read the detector result",
    "get_kpi_window": "Pull the KPI trend",
    "get_alarm_history": "Check alarms",
    "get_cell_configuration": "Read the radio configuration",
}


def label(tool: str, args: dict) -> str:
    if tool == "run_diagnostic_check":
        return f"Run {str(args.get('check', 'check')).replace('_', ' ')}"
    return LABELS.get(tool, tool.replace("_", " "))


def _plan(inc: dict) -> dict:
    if not inc.get("work_plan"):
        inc["work_plan"] = {"steps": [], "note": "", "revision": 0, "history": []}
    return inc["work_plan"]


def _revise(inc: dict, note: str, by: str, at: str) -> dict:
    p = _plan(inc)
    p["revision"] += 1
    p["note"] = note[:300]
    p["history"] = (p["history"] + [{"revision": p["revision"], "by": by, "note": note[:300], "at": at}])[-20:]
    return p


def replace(inc: dict, steps: list, note: str, by: str, at: str) -> dict | str:
    clean = []
    for s in steps or []:
        if isinstance(s, dict) and str(s.get("step", "")).strip():
            st = s.get("status", "todo")
            clean.append({"step": str(s["step"])[:140], "status": st if st in STATUSES else "todo", "by": by})
    if not 2 <= len(clean) <= 10:
        return f"a plan needs 2-10 steps, got {len(clean)}"
    if not note.strip():
        return "say in one line why the plan is what it is now"
    p = _plan(inc)
    p["steps"] = clean
    return _revise(inc, note, by, at)


def add(inc: dict, steps: list[str], note: str, by: str, at: str) -> dict:
    p = _plan(inc)
    have = {s["step"] for s in p["steps"] if s["status"] in ("todo", "doing")}
    p["steps"] += [{"step": s[:140], "status": "todo", "by": by} for s in steps if s not in have]
    return _revise(inc, note, by, at)


def mark(inc: dict, step: str, status: str, append: bool = True) -> None:
    p = _plan(inc)
    for s in p["steps"]:
        if s["step"] == step and s["status"] in ("todo", "doing"):
            s["status"] = status
            return
    if append:
        p["steps"].append({"step": step[:140], "status": status, "by": "investigator"})


def note(inc: dict, text: str, by: str, at: str) -> dict:
    return _revise(inc, text, by, at)
