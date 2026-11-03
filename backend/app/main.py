from __future__ import annotations

import base64
import json
import secrets
import statistics
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import Literal

from pydantic import BaseModel

from . import agents, radio, support
from .support import Support, SupportError
from .care import CREDIT_AMOUNT, CREDIT_MIN_MINUTES, SETTINGS, SUBSCRIBER, SYMPTOMS, Care
from .voice_memory import VoiceConversation
from .config import ROOT, settings
from .detection import DETECTOR_VERSION
from .orchestrator import OPEN_STATES, Sentinel
from .providers import GeminiSpeech, ProviderError
from .safety import ACTIONS, READ_ONLY_CHECKS
from .simulator import FAULT_TYPES, KPI_NAMES, KPI_UNITS, MARKET

sentinel: Sentinel | None = None
sessions: dict[str, dict] = {}
speech = GeminiSpeech(settings)
_runner = {"paused": False, "stop": False}


def _loop():
    while not _runner["stop"]:
        time.sleep(settings.tick_seconds)
        if not _runner["paused"] and sentinel:
            try:
                sentinel.tick()
            except Exception as e:
                print("tick error:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sentinel
    sentinel = Sentinel(settings)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"RAN Sentinel ready. AI engine: {sentinel.provider.label}. Open http://127.0.0.1:8000/ops/")
    yield
    _runner["stop"] = True


app = FastAPI(title="RAN Sentinel", lifespan=lifespan)
FRONT = ROOT / "frontend"
@app.middleware("http")
async def no_stale_pages(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith(("/ops", "/connect", "/shared")) and "/vendor/" not in request.url.path:
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/ops", StaticFiles(directory=FRONT / "ops", html=True), name="ops")
app.mount("/connect", StaticFiles(directory=FRONT / "connect", html=True), name="connect")
app.mount("/shared", StaticFiles(directory=FRONT / "shared"), name="shared")


@app.get("/")
def root():
    return RedirectResponse("/ops/")


class Login(BaseModel):
    email: str
    password: str
    portal: Literal["ops", "connect"]


MAX_FAILED, LOCK_SECONDS = 5, 300
_failed: dict[str, list[float]] = {}


def _matches(body: Login, portal: str) -> bool:
    email, pw = (settings.ops_email, settings.ops_password) if portal == "ops" else (settings.customer_email, settings.customer_password)
    return secrets.compare_digest(body.email.lower(), email.lower()) and secrets.compare_digest(body.password, pw)


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.monotonic()
    recent = [t for t in _failed.get(ip, []) if now - t < LOCK_SECONDS]
    _failed[ip] = recent
    if len(recent) >= MAX_FAILED:
        raise HTTPException(429, f"Too many failed sign-ins. Try again in {int(LOCK_SECONDS - (now - recent[0])) + 1} s.")
    if not _matches(body, body.portal):
        other = "connect" if body.portal == "ops" else "ops"
        if _matches(body, other):
            raise HTTPException(403, {"portal": other, "message": (
                "This is a Northstar Connect customer account. Customers sign in on the customer app."
                if other == "connect" else "This is an engineer account. Engineers sign in to RAN Sentinel Operations.")})
        _failed[ip].append(now)
        raise HTTPException(401, "Email or password is incorrect.")
    token = secrets.token_urlsafe(24)
    sessions[token] = {"email": body.email, "portal": body.portal}
    response.set_cookie(f"rs_{body.portal}", token, httponly=True, samesite="lax")
    return {"ok": True, "name": "Sarah Chen" if body.portal == "ops" else "Northstar customer"}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    for p in ("ops", "connect"):
        sessions.pop(request.cookies.get(f"rs_{p}", ""), None)
        response.delete_cookie(f"rs_{p}")
    return {"ok": True}


def ops_user(request: Request) -> dict:
    s = sessions.get(request.cookies.get("rs_ops", ""))
    if not s or s.get("portal") != "ops":
        raise HTTPException(401, "Sign in to Operations first.")
    return s


def customer_user(request: Request) -> dict:
    s = sessions.get(request.cookies.get("rs_connect", ""))
    if not s or s.get("portal") != "connect":
        raise HTTPException(401, "Sign in first.")
    return s


def _cell_status(cid: str) -> str:
    sen = sentinel
    if cid in sen.open_by_cell:
        inc = sen.incidents[sen.open_by_cell[cid]]
        return "critical" if inc["severity"] == "critical" else "incident"
    if cid in sen.related:
        return "symptom"
    det = sen.latest.get(cid) or {}
    if not det.get("quality_ok", True):
        return "no-data"
    if det.get("breaches") or (det.get("score") or 0) >= det.get("threshold", 1):
        return "watch"
    return "ok"


def _geo(c, row: dict) -> dict:
    sx, sy = radio.site_xy(c)
    slat, slon = radio.to_latlon(sx, sy)
    lat, lon = radio.to_latlon(c.x, c.y)
    return {"lat": lat, "lon": lon, "site_lat": slat, "site_lon": slon, "coverage_km": radio.coverage_km(c, row),
            "tx_power_dbm": c.config.tx_power_dbm, "tilt_deg": c.config.tilt_deg}


@app.get("/api/state")
def state(_: dict = Depends(ops_user)):
    sen = sentinel
    with sen.lock:
        cells = []
        for cid, c in sen.sim.cells.items():
            row = sen.sim.latest(cid) or {}
            det = sen.latest.get(cid) or {}
            cells.append({"cell_id": cid, "site": c.site, "sector": c.sector, "x": c.x, "y": c.y, "azimuth": c.azimuth,
                          "zip_code": c.zip_code, "band": c.band,
                          "status": _cell_status(cid), "score": det.get("score"), "prb_util": row.get("prb_util"),
                          "drop_rate": row.get("drop_rate"), "sinr_db": row.get("sinr_db"), "dl_thpt_mbps": row.get("dl_thpt_mbps"),
                          "availability": row.get("availability"), "active_users": row.get("active_users"),
                          "triggered_by": det.get("triggered_by") or [], "fault": (sen.sim.faults.get(cid) or {}).get("type"),
                          **_geo(c, row)})
        hist = []
        ticks = list(zip(*[sen.sim.history[cid][-48:] for cid in sen.sim.cells]))
        for rows in ticks:
            valid = [r for r in rows if not r.get("missing")]
            hist.append({"ts": rows[0]["ts"][11:16],
                         "prb_util": round(statistics.mean(r["prb_util"] for r in valid), 1) if valid else None,
                         "drop_rate": round(statistics.mean(r["drop_rate"] for r in valid), 2) if valid else None,
                         "dl_thpt_mbps": round(statistics.mean(r["dl_thpt_mbps"] for r in valid), 1) if valid else None,
                         "availability": round(statistics.mean(r["availability"] for r in valid), 3) if valid else None,
                         "sinr_db": round(statistics.mean(r["sinr_db"] for r in valid), 1) if valid else None})
        incs = [_inc_summary(i) for i in sorted(sen.incidents.values(), key=lambda i: i["id"], reverse=True)]
        open_incs = [i for i in incs if i["status"] in OPEN_STATES]
        activity = {"investigating": 0, "awaiting": 0, "monitoring": 0, "escalated": 0}
        for i in open_incs:
            st = i["status"]
            key = ("investigating" if st in ("DETECTED", "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_READY", "PLANNING", "AUTO_REMEDIATION")
                   else "awaiting" if st in ("AWAITING_DEPARTMENT", "FIELD_WORK") else "monitoring" if st in ("MONITORING", "CHANGE_APPLIED")
                   else "escalated")
            activity[key] += 1
        tickets = sen.store.list_tickets()
        active = [a for a in sen.sim.alarms if a["cleared"] is None]
        calls = sen.provider.calls[-200:]
        ok_calls = [c for c in calls if c["ok"]]
        return {
            "alarm_counts": {sev: sum(a["severity"] == sev for a in active) for sev in ("critical", "major", "minor", "warning")},
            "unacked_alarms": sum(a["alarm_id"] not in sen.acks for a in active),
            "model_stats": {"calls": len(calls), "failed": len(calls) - len(ok_calls),
                            "avg_latency_s": round(sum(c["latency_s"] for c in ok_calls) / len(ok_calls), 1) if ok_calls else None},
            "sim_time": sen.sim.now.isoformat(), "tick": sen.sim.tick, "paused": _runner["paused"], "market": MARKET,
            "engine": sen.provider.label, "offline": sen.provider.offline,
            "models": {"primary": settings.primary_model, "fallback": settings.fallback_model,
                       "reviewer": settings.reviewer_model, "last_resort": settings.last_resort_model,
                       "wonder": settings.wonder_model, "vision": settings.vision_model, "sam": settings.sam_model,
                       "voice": settings.voice_model, "assistant": settings.assistant_model,
                       "effort": {"default": settings.reasoning_effort or None, **settings.agent_effort,
                                  "accepted": getattr(sen.provider, "effort_ok", {}).get("meta")},
                       "fireworks": settings.fireworks_model.rsplit("/", 1)[-1] if settings.fireworks_api_key else None},
            "twin": sen.twin.name if hasattr(sen.twin, "name") else "twin",
            "flags": sen.flags,
            "summary": {"cells": len(cells), "watch": sum(c["status"] in ("watch", "symptom") for c in cells),
                        "open_incidents": len(open_incs),
                        "critical": sum(1 for i in open_incs if i["severity"] == "critical"),
                        "pending_tickets": sum(t["status"] == "pending" for t in tickets),
                        "support_unread": sum(1 for t in sen.store.list_support_tickets() if t["unread_staff"] and t["status"] != "closed"),
                        "network_status": "Degraded" if any(i["severity"] in ("major", "critical") for i in open_incs) else
                                          ("Watching" if open_incs else "Healthy")},
            "cells": cells, "health": hist, "incidents": incs[:30], "activity": activity,
            "agent_calls": sen.provider.calls[-12:],
        }


def _inc_summary(i: dict) -> dict:
    top = ((i.get("diagnosis") or {}).get("hypotheses") or [{}])[0]
    return {"id": i["id"], "title": i["title"], "cell_id": i["cell_id"], "site": i["site"], "kind": i["kind"],
            "status": i["status"], "severity": i["severity"], "created": i["created"], "department": i.get("department"),
            "top_cause": top.get("cause"), "support": top.get("support"), "related": len(i.get("related_cells") or []),
            "zip_code": i.get("zip_code"), "fcc_status": (i.get("fcc") or {}).get("status"),
            "stages": [v["status"] for v in i["stages"].values()], "ticket_id": i.get("ticket_id")}


@app.get("/api/cells/{cell_id}")
def cell(cell_id: str, _: dict = Depends(ops_user)):
    sen = sentinel
    if cell_id not in sen.sim.cells:
        raise HTTPException(404, "Unknown cell")
    with sen.lock:
        return {**sen.sim.cell_info(cell_id), "history": sen.sim.window(cell_id, 48),
                "alarms": sen.sim.active_alarms(cell_id), "config": sen.mplane.get_config(cell_id),
                "detection": sen.latest.get(cell_id), "units": KPI_UNITS}


@app.get("/api/incidents/{iid}")
def incident(iid: str, _: dict = Depends(ops_user)):
    sen = sentinel
    inc = sen.incidents.get(iid)
    if not inc:
        raise HTTPException(404, "Incident not found")
    snap = sen.snapshot(inc)
    with sen.lock:
        snap["kpi_window"] = sen.sim.window(inc["cell_id"], 32)
        snap["alarms"] = sen.sim.active_alarms(inc["cell_id"])
        snap["config"] = {k: v for k, v in sen.mplane.get_config(inc["cell_id"]).items() if k != "netconf_reply"}
    snap["ledger"] = sen.store.ledger(iid)
    snap["ticket"] = sen.store.get_ticket(inc["ticket_id"]) if inc.get("ticket_id") else None
    snap["regulatory_ticket_data"] = sen.store.get_ticket(inc["regulatory_ticket"]) if inc.get("regulatory_ticket") else None
    return snap


@app.post("/api/incidents/{iid}/report")
def report(iid: str, _: dict = Depends(ops_user)):
    if iid not in sentinel.incidents:
        raise HTTPException(404, "Incident not found")
    return sentinel.write_report(iid)


class EvidenceReply(BaseModel):
    note: str


@app.post("/api/incidents/{iid}/evidence")
def evidence_reply(iid: str, body: EvidenceReply, user: dict = Depends(ops_user)):
    if iid not in sentinel.incidents:
        raise HTTPException(404, "Incident not found")
    try:
        return sentinel.provide_evidence(iid, "Sarah Chen", body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/incidents/{iid}/resume")
def resume(iid: str, _: dict = Depends(ops_user)):
    if iid not in sentinel.incidents:
        raise HTTPException(404, "Incident not found")
    try:
        return sentinel.resume_investigation(iid, "Sarah Chen")
    except ValueError as e:
        raise HTTPException(400, str(e))


class Signoff(BaseModel):
    decision: str
    note: str = ""


@app.post("/api/incidents/{iid}/rca")
def rca_signoff(iid: str, body: Signoff, _: dict = Depends(ops_user)):
    if iid not in sentinel.incidents:
        raise HTTPException(404, "Incident not found")
    try:
        return sentinel.sign_off_rca(iid, "Sarah Chen", body.decision, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/incidents/{iid}/photo")
async def photo(iid: str, request: Request, note: str = "", user: dict = Depends(ops_user)):
    if iid not in sentinel.incidents:
        raise HTTPException(404, "Incident not found")
    body = await request.body()
    mime = (request.headers.get("content-type") or "").split(";")[0].strip()
    try:
        return await run_in_threadpool(sentinel.add_photo, iid, body, mime, "Sarah Chen", note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/incidents/{iid}/attachments")
async def attachment(iid: str, request: Request, name: str = "", note: str = "", user: dict = Depends(ops_user)):
    if iid not in sentinel.incidents:
        raise HTTPException(404, "Incident not found")
    body = await request.body()
    mime = (request.headers.get("content-type") or "").split(";")[0].strip()
    try:
        return await run_in_threadpool(sentinel.add_attachment, iid, body, mime, name, "Sarah Chen", note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/files/{did}")
def field_file(did: str, _: dict = Depends(ops_user)):
    if did not in sentinel.files:
        raise HTTPException(404, "File not found")
    data, mime, name = sentinel.files[did]
    ascii_name = name.encode("ascii", "ignore").decode() or did
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{ascii_name}"'})


@app.get("/api/photos/{pid}")
def photo_file(pid: str, _: dict = Depends(ops_user)):
    if pid not in sentinel.photos:
        raise HTTPException(404, "Photo not found")
    data, mime = sentinel.photos[pid]
    return Response(data, media_type=mime)


@app.post("/api/handover")
def handover(_: dict = Depends(ops_user)):
    return sentinel.write_handover()


@app.get("/api/handover")
def handover_get(_: dict = Depends(ops_user)):
    return sentinel.handover or {}


def _keywords() -> list[str]:
    sen = sentinel
    words = ["PRB", "SINR", "VSWR", "tilt", "NORS", "FCC", "M-Plane", "approve", "reject", "dispatch"]
    words += sorted({c.site for c in sen.sim.cells.values()})
    words += [sen.incidents[i]["cell_id"] for i in sen.open_by_cell.values()][:20]
    return words


async def _transcribe(request: Request, keywords: list[str]) -> dict:
    wav = await request.body()
    if len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise HTTPException(400, "Send a WAV recording (mono 16-bit PCM, 16 kHz).")
    if len(wav) > 30_000_000:
        raise HTTPException(413, "Recording is too long.")
    try:
        return await run_in_threadpool(sentinel.provider.transcribe, wav, keywords)
    except ProviderError as e:
        raise HTTPException(503, f"Voice is unavailable, so please type instead. ({str(e)[:160]})")


@app.post("/api/voice")
async def voice(request: Request, _: dict = Depends(ops_user)):
    r = await _transcribe(request, _keywords())
    return {**r, "intent": agents.voice_intent(r["text"])}


@app.post("/api/public/voice")
async def public_voice(request: Request, _: dict = Depends(customer_user)):
    words = sorted({c.site for c in sentinel.sim.cells.values()}) + ["Northstar", "Wi-Fi Calling", "Data Saver", "credit", "bill"]
    r = await _transcribe(request, words)
    return {"text": r["text"], "model": r["model"]}


@app.get("/api/model-card")
def model_card(_: dict = Depends(ops_user)):
    out = {"detector": {"version": DETECTOR_VERSION,
                        "design": "Three detectors vote; any one opens an alert after 2 consecutive 15-minute windows. "
                                  "(1) 7 engineer-set threshold rules. (2) Isolation Forest (200 trees) on 8 cell KPIs. "
                                  "(3) Cell baseline: each KPI compared with what is normal for that cell at that hour, "
                                  "scored with Mahalanobis distance. All trained on 7 simulated normal days."},
           "benchmarks": {}}
    bdir = ROOT / "data" / "benchmarks"
    for name in ("simulator", "telecomts"):
        f = bdir / f"{name}.json"
        if f.exists():
            try:
                out["benchmarks"][name] = json.loads(f.read_text())
            except ValueError:
                out["benchmarks"][name] = {"error": f"{f.name} is not valid JSON"}
    return out


ALARM_INFO = {
    "VSWR_HIGH": ("Equipment", "Antenna or feeder problem"),
    "RU_TX_POWER_LOW": ("Equipment", "Transmitter failure"),
    "PM_FILE_MISSING": ("Processing error", "File transfer failure"),
    "HIGH_LOAD": ("Quality of service", "Threshold crossed"),
    "UL_INTERFERENCE": ("Communications", "Excessive interference"),
}


@app.get("/api/alarms")
def alarms(_: dict = Depends(ops_user)):
    sen = sentinel
    with sen.lock:
        out = []
        for a in reversed(sen.sim.alarms[-400:]):
            c = sen.sim.cells[a["cell_id"]]
            et, pc = ALARM_INFO.get(a["code"], ("Other", "Unknown"))
            out.append({**a, "site": c.site, "zip_code": c.zip_code, "band": c.band, "event_type": et, "probable_cause": pc,
                        "incident": sen.open_by_cell.get(a["cell_id"]) or sen.related.get(a["cell_id"]),
                        "ack": sen.acks.get(a["alarm_id"])})
        return out


@app.post("/api/alarms/{aid}/ack")
def ack_alarm(aid: str, _: dict = Depends(ops_user)):
    sen = sentinel
    if not any(a["alarm_id"] == aid for a in sen.sim.alarms):
        raise HTTPException(404, "Alarm not found")
    if aid in sen.acks:
        sen.acks.pop(aid)
        return {"alarm_id": aid, "ack": None}
    sen.acks[aid] = {"by": "Sarah Chen", "at": sen.sim.now.isoformat()}
    return {"alarm_id": aid, "ack": sen.acks[aid]}


@app.get("/api/tickets")
def tickets(_: dict = Depends(ops_user)):
    return sentinel.store.list_tickets()


class Decision(BaseModel):
    decision: str
    note: str = ""
    user: str = "Sarah Chen"


@app.post("/api/tickets/{tid}/decide")
def decide(tid: str, body: Decision, _: dict = Depends(ops_user)):
    try:
        return sentinel.decide(tid, body.decision, body.user, body.note)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/ledger")
def ledger(_: dict = Depends(ops_user)):
    return sentinel.store.ledger(limit=150)


@app.get("/api/catalogue")
def catalogue(_: dict = Depends(ops_user)):
    return {"faults": FAULT_TYPES, "actions": ACTIONS, "checks": READ_ONLY_CHECKS, "kpis": KPI_NAMES}


class Inject(BaseModel):
    cell_id: str
    fault_type: str
    severity: int = 2


@app.post("/api/demo/inject")
def inject(body: Inject, _: dict = Depends(ops_user)):
    try:
        return sentinel.inject(body.cell_id, body.fault_type, body.severity)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Flags(BaseModel):
    red_team: bool | None = None
    api_outage: str | None = None
    twin_outage: bool | None = None
    diag_outage: bool | None = None
    paused: bool | None = None


@app.post("/api/demo/flags")
def flags(body: Flags, _: dict = Depends(ops_user)):
    if body.red_team is not None:
        sentinel.flags["red_team"] = body.red_team
    if body.api_outage in ("none", "primary_down", "all_down"):
        sentinel.flags["api_outage"] = body.api_outage
    if body.twin_outage is not None:
        sentinel.flags["twin_outage"] = body.twin_outage
    if body.diag_outage is not None:
        sentinel.flags["diag_outage"] = body.diag_outage
    if body.paused is not None:
        _runner["paused"] = body.paused
    return {**sentinel.flags, "paused": _runner["paused"]}


@app.post("/api/demo/step")
def step(_: dict = Depends(ops_user)):
    sentinel.tick()
    return {"tick": sentinel.sim.tick}


@app.post("/api/demo/clear")
def clear(_: dict = Depends(ops_user)):
    sentinel.clear_faults()
    return {"ok": True}


@app.post("/api/demo/reset")
def reset(_: dict = Depends(ops_user)):
    global sentinel
    with sentinel.lock:
        sentinel = Sentinel(settings, store=sentinel.store, provider=sentinel.provider)
    return {"ok": True}


def _public_status() -> dict:
    sen = sentinel
    updates = sen.store.customer_updates()
    latest: dict[str, dict] = {}
    for u in updates:
        latest.setdefault(u["incident_id"], u)
    areas = {}
    for site in {c.site for c in sen.sim.cells.values()}:
        areas[site] = {"area": site, "status": "normal", "text": "No known issues.", "updated": None, "reference": None}
    for iid, u in latest.items():
        if u["status"] == "resolved":
            continue
        st = "outage" if u["status"] == "field_team" else "degraded"
        areas[u["area"]] = {"area": u["area"], "status": st, "text": u["text"], "updated": u["published"], "reference": iid}
    xy, zips = {}, {}
    for c in sen.sim.cells.values():
        xy.setdefault(c.site, (c.x, c.y))
        zips.setdefault(c.site, c.zip_code)
    for a in areas.values():
        a["x"], a["y"] = xy[a["area"]]
        a["zip"] = zips[a["area"]]
    return {"region": "Seattle, WA", "timezone": MARKET["tz_label"], "areas": sorted(areas.values(), key=lambda a: (a["status"] == "normal", a["area"])),
            "updates": updates[:20]}


@app.get("/api/public/status")
def public_status(_: dict = Depends(customer_user)):
    return _public_status()


class Question(BaseModel):
    question: str


@app.post("/api/public/assistant")
def assistant(body: Question, _: dict = Depends(customer_user)):
    if not body.question.strip():
        raise HTTPException(400, "Type a question first.")
    st = _public_status()
    return agents.answer_customer(sentinel.provider, body.question, st["updates"], st["areas"],
                                  [settings.assistant_model, settings.fallback_model])


def _care() -> Care:
    sen = sentinel
    if getattr(sen, "care", None) is None:
        sen.care = Care(sen)
    with sen.lock:
        sen.care.sync()
    return sen.care


def _account(c: Care) -> dict:
    s = SUBSCRIBER
    credits = sum(x["amount"] for x in c.credits)
    used = sum(l["data_used_gb"] for l in s["lines"])
    return {"name": s["name"], "first_name": s["first_name"], "account": s["account"], "member_since": s["member_since"],
            "plan": s["plan"], "lines": s["lines"], "cycle": s["cycle"], "data_used_gb": round(used, 1),
            "bill": {**s["bill"], "credits": credits, "balance_after_credits": round(s["bill"]["balance"] - credits, 2)}}


@app.get("/api/care/home")
def care_home(s: dict = Depends(customer_user)):
    c = _care()
    with sentinel.lock:
        places = [c.place_status(p) for p in c.places]
    return {"account": _account(c), "places": places, "notifications": c.notifications[:5],
            "unread": sum(not n["read"] for n in c.notifications), "credits": c.credit_status(),
            "support_unread": sum(t["unread_customer"] for t in _support().mine(s["email"])),
            "prefs": c.prefs, "now": sentinel.sim.now.isoformat(), "timezone": MARKET["tz_label"],
            "engine": "offline" if sentinel.provider.offline else "meta"}


@app.get("/api/care/network")
def care_network(_: dict = Depends(customer_user)):
    c = _care()
    with sentinel.lock:
        places = [c.place_status(p) for p in c.places]
        areas = []
        for z, a in sorted(c.areas().items(), key=lambda kv: kv[1]["area"]):
            st = c.place_status({"id": "area", "label": a["area"], "zip": z})
            areas.append({**a, "status": st["status"], "issue": st["issue"]})
    return {"places": places, "areas": areas, "reports": c.reports[:10], "now": sentinel.sim.now.isoformat(),
            "symptoms": SYMPTOMS}


@app.get("/api/care/notifications")
def care_notifications(_: dict = Depends(customer_user)):
    return {"items": _care().notifications}


@app.post("/api/care/notifications/read")
def care_read(_: dict = Depends(customer_user)):
    for n in _care().notifications:
        n["read"] = True
    return {"ok": True}


@app.get("/api/care/account")
def care_account(_: dict = Depends(customer_user)):
    c = _care()
    return {"account": _account(c), "prefs": c.prefs, "settings": SETTINGS, "places": c.places,
            "areas": sorted(({"zip": z, "area": a["area"]} for z, a in c.areas().items()), key=lambda a: a["area"]),
            "credits": c.credit_status(), "applied": c.credits,
            "credit_policy": {"minutes": CREDIT_MIN_MINUTES, "amount": CREDIT_AMOUNT}}


class Pref(BaseModel):
    key: str
    value: bool


@app.post("/api/care/prefs")
def care_pref(body: Pref, _: dict = Depends(customer_user)):
    try:
        return _care().set_pref(body.key, body.value)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Place(BaseModel):
    place: str
    zip: str


@app.post("/api/care/places")
def care_place(body: Place, _: dict = Depends(customer_user)):
    try:
        return _care().set_place(body.place, body.zip)
    except ValueError as e:
        raise HTTPException(400, str(e))


class CreditReq(BaseModel):
    reference: str


@app.post("/api/care/credit")
def care_credit(body: CreditReq, _: dict = Depends(customer_user)):
    try:
        return _care().apply_credit(body.reference)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Report(BaseModel):
    place: str
    symptom: str
    details: str = ""


@app.post("/api/care/report")
def care_report(body: Report, _: dict = Depends(customer_user)):
    try:
        return _care().report(body.place, body.symptom, body.details)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Ask(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/care/concierge")
async def care_concierge(body: Ask, _: dict = Depends(customer_user)):
    if not body.question.strip():
        raise HTTPException(400, "Type a question first.")
    c = _care()
    return await run_in_threadpool(c.concierge, body.question, body.history)


class VoiceTurn(BaseModel):
    text: str
    action_id: str | None = None
    request_id: str | None = None
    history: list[dict] = []
    page: str = ""
    speak: bool = True


def _voice_memory(user: dict) -> VoiceConversation:
    return user.setdefault("voice_memory", VoiceConversation())


@app.get("/api/care/voice/memory")
def voice_memory_get(user: dict = Depends(customer_user)):
    return _voice_memory(user).restore(_care())


@app.delete("/api/care/voice/memory")
def voice_memory_clear(user: dict = Depends(customer_user)):
    return _voice_memory(user).reset(_care())


@app.get("/api/care/voice/status")
def voice_status(_: dict = Depends(customer_user)):
    return {"listen": None if sentinel.provider.offline else settings.voice_model,
            "think": "rules" if sentinel.provider.offline else settings.primary_model,
            "speak": settings.tts_model if speech.enabled else "browser", "voice": settings.tts_voice}


@app.post("/api/care/voice/turn")
async def voice_turn(body: VoiceTurn, _: dict = Depends(customer_user)):
    if not body.text.strip():
        raise HTTPException(400, "I didn't catch that.")
    c = _care()
    try:
        r = await run_in_threadpool(_voice_memory(_).turn, c, body.text, body.action_id, body.page, body.request_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    r["audio"], r["voice_by"] = None, "browser"
    if body.speak and speech.enabled:
        try:
            sp = await run_in_threadpool(speech.speak, r["answer"])
            r["audio"], r["voice_by"] = "data:audio/wav;base64," + base64.b64encode(sp["wav"]).decode(), sp["model"]
        except ProviderError as e:
            r["voice_note"] = str(e)[:160]
    return r


class SpeakReq(BaseModel):
    text: str


@app.post("/api/care/voice/speak")
async def voice_speak(body: SpeakReq, _: dict = Depends(customer_user)):
    text = body.text.strip()[:1200]
    if not text or not speech.enabled:
        raise HTTPException(503, "Gemini voice is not set up; the browser voice is used instead.")
    try:
        sp = await run_in_threadpool(speech.speak, text)
    except ProviderError as e:
        raise HTTPException(503, f"Voice unavailable: {str(e)[:160]}")
    return Response(sp["wav"], media_type="audio/wav", headers={"X-Voice-Model": sp["model"], "Cache-Control": "no-store"})


class Confirm(BaseModel):
    action_id: str


@app.post("/api/care/confirm")
def care_confirm(body: Confirm, _: dict = Depends(customer_user)):
    try:
        c = _care()
        memory = _voice_memory(_)
        if memory.owns(c, body.action_id):
            return memory.action(c, body.action_id)
        return c.confirm(body.action_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/care/voice/cancel")
def voice_cancel(body: Confirm, _: dict = Depends(customer_user)):
    try:
        return _voice_memory(_).action(_care(), body.action_id, cancel=True)
    except ValueError as e:
        raise HTTPException(400, str(e))



@app.get("/api/care/map")
def care_map(place: str = "home", _: dict = Depends(customer_user)):
    c = _care()
    try:
        with sentinel.lock:
            return c.map(place)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/care/signal")
def care_signal(place: str = "home", _: dict = Depends(customer_user)):
    c = _care()
    try:
        with sentinel.lock:
            return c.signal(place)
    except ValueError as e:
        raise HTTPException(400, str(e))


class PlaceOnly(BaseModel):
    place: str


@app.post("/api/care/signal/explain")
async def care_signal_explain(body: PlaceOnly, _: dict = Depends(customer_user)):
    c = _care()
    try:
        return await run_in_threadpool(c.explain_signal, body.place)
    except ValueError as e:
        raise HTTPException(400, str(e))


class PhonePos(BaseModel):
    place: str
    lat: float
    lon: float


@app.post("/api/care/phone")
def care_phone(body: PhonePos, _: dict = Depends(customer_user)):
    try:
        return _care().move_phone(body.place, body.lat, body.lon)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _support() -> Support:
    sen = sentinel
    if getattr(sen, "support", None) is None or sen.support.store is not sen.store:
        sen.support = Support(sen.store)
    return sen.support


def _sup(fn, *a, **k):
    try:
        return fn(*a, **k)
    except SupportError as e:
        raise HTTPException(e.status, {"message": e.message, "fields": e.fields})


@app.get("/api/care/help")
def care_help(q: str = "", category: str = "", _: dict = Depends(customer_user)):
    if category and category not in support.CATEGORIES:
        raise HTTPException(400, "Unknown category.")
    return {"categories": [{"id": k, "label": v, "count": sum(a["category"] == k for a in support.ARTICLES)} for k, v in support.CATEGORIES.items()],
            "articles": support.search(q, category or None), "popular": support.POPULAR, "q": q}


@app.get("/api/care/help/{aid}")
def care_article(aid: str, _: dict = Depends(customer_user)):
    a = support.BY_ID.get(aid)
    if not a:
        raise HTTPException(404, "We couldn't find that help article.")
    related = [x for x in support.ARTICLES if x["category"] == a["category"] and x["id"] != aid][:3]
    return {**a, "category_label": support.CATEGORIES[a["category"]], "related": related}


@app.get("/api/care/support")
def care_support_list(s: dict = Depends(customer_user)):
    items = _support().mine(s["email"])
    return {"tickets": items, "unread": sum(t["unread_customer"] for t in items),
            "contact": {"name": SUBSCRIBER["name"], "email": s["email"]},
            "categories": support.CATEGORIES, "statuses": support.STATUSES}


class NewTicket(BaseModel):
    name: str = ""
    email: str = ""
    subject: str = ""
    category: str = ""
    description: str = ""


@app.post("/api/care/support")
def care_support_create(body: NewTicket, s: dict = Depends(customer_user)):
    return _sup(_support().create, s["email"], body.model_dump())


@app.get("/api/care/support/{tid}")
def care_support_get(tid: str, s: dict = Depends(customer_user)):
    return _sup(_support().view_customer, tid, s["email"])


class TicketReply(BaseModel):
    body: str = ""


@app.post("/api/care/support/{tid}/reply")
def care_support_reply(tid: str, body: TicketReply, s: dict = Depends(customer_user)):
    return _sup(_support().customer_reply, tid, s["email"], SUBSCRIBER["name"], body.body)


@app.post("/api/care/support/{tid}/close")
def care_support_close(tid: str, s: dict = Depends(customer_user)):
    return _sup(_support().customer_close, tid, s["email"])


STAFF_NAME = "Sarah Chen"


@app.get("/api/support/tickets")
def support_list(status: str = "active", category: str = "all", q: str = "", _: dict = Depends(ops_user)):
    out = _sup(_support().all, status, category, q)
    return {**out, "statuses": support.STAFF_STATUSES, "categories": support.CATEGORIES, "priorities": support.PRIORITIES}


@app.get("/api/support/tickets/{tid}")
def support_get(tid: str, _: dict = Depends(ops_user)):
    t = _sup(_support().view_staff, tid)
    history = [x for x in _support().store.list_support_tickets(t["owner"]) if x["id"] != t["id"]]
    return {**t, "history": [support.public(x, staff=True) for x in history[:10]], "statuses": support.STAFF_STATUSES,
            "priorities": support.PRIORITIES, "categories": support.CATEGORIES}


class StaffReply(BaseModel):
    body: str = ""
    status: str | None = "waiting_customer"


@app.post("/api/support/tickets/{tid}/reply")
def support_reply(tid: str, body: StaffReply, _: dict = Depends(ops_user)):
    return _sup(_support().staff_reply, tid, STAFF_NAME, body.body, body.status)


class StaffUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None


@app.post("/api/support/tickets/{tid}/update")
def support_update(tid: str, body: StaffUpdate, _: dict = Depends(ops_user)):
    return _sup(_support().staff_update, tid, STAFF_NAME, body.status, body.priority)
