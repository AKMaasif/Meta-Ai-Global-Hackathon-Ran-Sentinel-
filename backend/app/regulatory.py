from __future__ import annotations

from datetime import datetime, timedelta

USER_MINUTES_THRESHOLD = 900_000
MIN_DURATION_MIN = 30
NOTIFY_WITHIN = timedelta(minutes=120)
INITIAL_WITHIN = timedelta(hours=72)
FINAL_WITHIN = timedelta(days=30)
RULE = "47 CFR 4.9(e)"


def assess(inc: dict, now: datetime, users_per_site: int) -> dict:
    cause = ((inc.get("diagnosis") or {}).get("hypotheses") or [{}])[0].get("cause")
    snap = inc.get("kpi_at_detection") or {}
    outage = cause == "hardware_fault" or (snap.get("availability", 100.0) < 99.9 and inc.get("kind") == "network")
    found = datetime.fromisoformat(inc["created"])
    end = datetime.fromisoformat(inc["resolved_at"]) if inc.get("resolved_at") else now
    minutes = max(0, int((end - found).total_seconds() // 60))
    users = users_per_site // 3 if outage else 0
    user_minutes = users * minutes
    base = {"rule": RULE, "threshold_user_minutes": USER_MINUTES_THRESHOLD, "duration_min": minutes,
            "users_potentially_affected": users, "user_minutes": user_minutes,
            "basis": f"{users_per_site:,} average users per macro site (set FCC_USERS_PER_SITE in .env)",
            "note": "Decision support only, not legal advice."}
    if not outage:
        return {**base, "status": "not_an_outage",
                "summary": "Service degraded, not lost: not a Part 4 outage. Keep monitoring."}
    reportable = minutes >= MIN_DURATION_MIN and user_minutes >= USER_MINUTES_THRESHOLD
    pct = round(100 * user_minutes / USER_MINUTES_THRESHOLD, 1)
    if reportable:
        return {**base, "status": "reportable", "progress_pct": 100.0,
                "deadlines": {"notification": (found + NOTIFY_WITHIN).isoformat(),
                              "initial_report": (found + INITIAL_WITHIN).isoformat(),
                              "final_report": (found + FINAL_WITHIN).isoformat()},
                "summary": f"Reportable in NORS: {user_minutes:,} user-minutes over {minutes} min. "
                           "Notify the FCC within 120 minutes of discovery."}
    return {**base, "status": "below_threshold", "progress_pct": min(pct, 99.9),
            "summary": f"Outage below the NORS threshold: {user_minutes:,} of {USER_MINUTES_THRESHOLD:,} user-minutes ({pct}%)."}
