from __future__ import annotations

import base64
import copy
import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import agents, fielddocs, regulatory, verify, workplan
from .agents import PHOTO_PROMPTS, AgentContext, AgentOutputError
from .config import Settings
from .detection import Detector, features
from .mplane import MPlaneClient, MPlaneError
from .providers import ProviderError, make_provider
from .safety import ACTIONS, DEPARTMENTS, FITS, TARGETS, department_for, validate_plan
from .simulator import NetworkSimulator, training_rows
from .store import Store
from .tools import Toolbox
from .twin import TwinUnavailable, make_twin

STAGES = ["detect", "investigate", "analyse", "verify", "plan", "validate", "sandbox", "second_opinion", "review", "change", "monitor"]
OPEN_STATES = {"DETECTED", "AUTO_REMEDIATION", "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_READY", "PLANNING",
               "AWAITING_DEPARTMENT", "CHANGE_APPLIED", "FIELD_WORK", "MONITORING", "ESCALATED"}


class Sentinel:
    def __init__(self, settings: Settings, store: Store | None = None, provider=None, seed: int = 7):
        self.s = settings
        self.store = store or Store(settings.db_path)
        self.store.reset()
        self.lock = threading.RLock()
        self.sim = NetworkSimulator(seed=seed)
        rows = training_rows()
        self.detector = Detector(np.array([features(r) for r in rows]), rows=rows)
        self.mplane = MPlaneClient(self.sim)
        self.twin, self.fallback_twin = make_twin(self.sim, settings.maveric_url, settings.maveric_model, settings.maveric_timeout)
        self.toolbox = Toolbox(self.sim, self.mplane)
        self.provider = provider or make_provider(settings)
        self.flags = {"red_team": False, "api_outage": "none", "twin_outage": False, "diag_outage": False}
        self.latest: dict[str, dict] = {}
        self.incidents: dict[str, dict] = {}
        self.open_by_cell: dict[str, str] = {}
        self.related: dict[str, str] = {}
        self._seq = 0
        self._tseq = 0
        self.photos: dict[str, tuple[bytes, str]] = {}
        self.files: dict[str, tuple[bytes, str, str]] = {}
        self.handover: dict | None = None
        self.acks: dict[str, dict] = {}
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.sync = False

    def tick(self) -> None:
        with self.lock:
            self.sim.step()
            for r in self.mplane.on_tick():
                inc = self.incidents.get(r["incident_id"])
                if inc:
                    self._log(inc, "radio-unit", "auto_rollback", "Confirm timeout expired: radio unit rolled back by itself")
            for cid in self.sim.cells:
                det = self.detector.evaluate(self.sim.latest(cid), cid)
                self.latest[cid] = det
                if cid in self.open_by_cell or cid in self.related:
                    continue
                if det["data_quality_alert"]:
                    self._open(cid, det, kind="data_quality")
                elif det["alert"]:
                    parent = self._related_parent(cid)
                    if parent:
                        self._attach(parent, cid, det)
                    else:
                        self._open(cid, det, kind="network")
            for inc in list(self.incidents.values()):
                if inc["kind"] == "network" and inc["status"] in OPEN_STATES:
                    self._regulatory(inc)
                if inc["status"] == "ESCALATED":
                    self._auto_resume(inc)
                if inc["status"] == "AUTO_REMEDIATION":
                    self._auto_remediate_dq(inc)
                elif inc["status"] == "MONITORING":
                    self._monitor(inc)

    def _open(self, cid: str, det: dict, kind: str) -> dict:
        self._seq += 1
        cell = self.sim.cells[cid]
        row = self.sim.latest(cid) or {}
        inc = {
            "id": f"RNS-2026-{self._seq:03d}", "kind": kind, "cell_id": cid, "site": cell.site,
            "azimuth": cell.azimuth, "neighbours": cell.neighbours, "status": "DETECTED",
            "severity": _severity(row) if kind == "network" else "minor",
            "title": "", "created": self.sim.now.isoformat(), "detected_tick": self.sim.tick,
            "detection": det, "evidence": [], "trace": [], "stages": {s: {"status": "pending", "note": ""} for s in STAGES},
            "diagnosis": None, "plans": [], "ticket_id": None, "department": None, "change": None,
            "monitoring": None, "reopen_count": 0, "evidence_rounds": 0, "tool_calls": 0, "agent_runs": [],
            "engine": self.provider.label, "customer_status": None, "escalation": None, "repoll_attempts": 0,
            "zip_code": cell.zip_code, "band": cell.band, "kpi_at_detection": row, "resolved_at": None,
            "review": None, "fcc": None, "regulatory_ticket": None, "report": None,
            "escalation_brief": None, "photos": [], "attachments": [], "checklist": [], "verification": None,
            "evidence_requests": [], "rca_signoff": None, "work_plan": None, "checkpoint": None,
        }
        inc["title"] = (f"{_kind_title(det, row)} {cid}" if kind == "network" else f"KPI data missing {cid}")
        self.incidents[inc["id"]] = inc
        self.open_by_cell[cid] = inc["id"]
        self._stage(inc, "detect", "pass", f"score {det.get('score', '-')}, {', '.join(det.get('breaches') or det.get('issues') or []) or 'model anomaly'}")
        self._log(inc, "detector", "incident_opened",
                  f"{inc['title']} opened; evidence snapshot stored", {"detection": det, "kpis": row})
        if kind == "data_quality":
            inc["status"] = "AUTO_REMEDIATION"
            self._log(inc, "data-quality", "quarantined", "Windows without KPI data quarantined; no anomaly alerts raised on them")
            self._save(inc)
            return inc
        if inc["severity"] in ("major", "critical"):
            self._customer(inc, "investigating")
        self._save(inc)
        self._submit(inc["id"])
        return inc

    def _related_parent(self, cid: str) -> dict | None:
        mine = set(self.sim.cells[cid].neighbours)
        for pcid, iid in self.open_by_cell.items():
            inc = self.incidents[iid]
            if inc["kind"] == "network" and (pcid in mine or cid in inc["neighbours"]):
                return inc
        return None

    def _attach(self, parent: dict, cid: str, det: dict) -> None:
        self.related[cid] = parent["id"]
        with self.lock:
            parent.setdefault("related_cells", []).append({"cell_id": cid, "breaches": det.get("breaches"),
                                                           "score": det.get("score"), "sim_ts": self.sim.now.isoformat()})
        self._log(parent, "detector", "related_alert",
                  f"{cid} alert ({', '.join(det.get('breaches') or ['model anomaly'])}) attached as a symptom of this incident")
        self._save(parent)

    def _submit(self, iid: str, note: str = "", resume: bool = False) -> None:
        if self.sync:
            self.run_investigation(iid, note, resume)
        else:
            self.executor.submit(self.run_investigation, iid, note, resume)

    def run_investigation(self, iid: str, note: str = "", resume: bool = False) -> None:
        inc = self.incidents[iid]
        cp = (inc.get("checkpoint") or {}) if resume else {}
        phase = cp.get("phase", "investigate")
        with self.lock:
            inc["status"] = "INVESTIGATING"
            if not resume:
                inc["checkpoint"] = {"phase": "investigate"}
            self._stage(inc, "investigate" if phase in ("investigate", "analyse") else phase, "running",
                        f"resumed at {phase}" if resume else "")
            self._save(inc)
        self.provider.outage = self.flags["api_outage"]
        self.toolbox.diag_outage = self.flags["diag_outage"]
        ctx = AgentContext(self.provider, self.toolbox, inc, self._evidence_cb(inc), self._trace_cb(inc),
                           tool_budget=self.s.max_tool_calls, now=lambda: self.sim.now.isoformat(),
                           save_step=self._step_saver(inc), one_tool_per_turn=self.s.one_tool_per_turn)
        ctx.tool_calls_used = cp.get("tool_calls_used", 0)
        try:
            if phase == "investigate":
                instruction = "Find what is degrading this cell. Start with the detector result, KPIs, alarms and configuration."
                if note:
                    instruction += f" Engineer/orchestrator note: {note}"
                agents.investigate(ctx, instruction, resume=cp.get("messages"))
                if inc.get("_ask"):
                    return self._pause(inc, **inc.pop("_ask"))
                self._stage(inc, "investigate", "pass", f"{ctx.tool_calls_used} tool calls")
                self._checkpoint(inc, ctx, "analyse")
            if phase in ("investigate", "analyse"):
                rounds = inc["evidence_rounds"] if resume else 0
                while True:
                    self._stage(inc, "analyse", "running", "")
                    diag = agents.analyse(ctx, self.s.max_evidence_rounds - rounds)
                    inc["diagnosis"] = diag
                    top = diag["hypotheses"][0]
                    self._log(inc, "analyst", "hypotheses_ranked",
                              " › ".join(f"{h['cause']} ({h['support']})" for h in diag["hypotheses"]), diag)
                    self._wp(inc, "analyst", f"Leading cause: {top['cause'].replace('_', ' ')} ({top['support']} support)"
                             + ("" if diag["enough_evidence"] else "; more evidence needed"),
                             [] if diag["enough_evidence"] else [workplan.label(*t) for t in verify.fetch_plan(
                                 diag.get("requested_checks") or [], inc["cell_id"], inc["id"])])
                    if diag["enough_evidence"]:
                        break
                    if rounds < self.s.max_evidence_rounds and diag.get("requested_checks") and ctx.tool_calls_used < ctx.tool_budget:
                        rounds += 1
                        inc["evidence_rounds"] = rounds
                        self._log(inc, "analyst", "more_evidence_requested",
                                  f"Not enough evidence; requested {', '.join(diag['requested_checks'])}")
                        self._stage(inc, "investigate", "running", f"evidence round {rounds + 1}")
                        agents.investigate(ctx, "Run the requested read-only checks.", diag["requested_checks"])
                        if inc.get("_ask"):
                            return self._pause(inc, **inc.pop("_ask"))
                        self._stage(inc, "investigate", "pass", f"{ctx.tool_calls_used} tool calls, {rounds + 1} rounds")
                        continue
                    if not inc["evidence_requests"]:
                        second = diag["hypotheses"][1]["cause"]
                        return self._pause(inc, f"{agents.FIELD_ASK[top['cause']]} {agents.FIELD_ASK[second]}",
                                           f"The data cannot separate {top['cause'].replace('_', ' ')} from {second.replace('_', ' ')}.",
                                           "orchestrator")
                    second = diag["hypotheses"][1] if len(diag["hypotheses"]) > 1 else None
                    field_ids = {(r.get("answer") or {}).get("evidence_id") for r in inc["evidence_requests"]} - {None}
                    if field_ids & set(top.get("supporting_evidence") or []) and top["support"] in ("strong", "moderate") and (
                            second is None or agents.SUPPORT.index(top["support"]) < agents.SUPPORT.index(second["support"])):
                        self._log(inc, "orchestrator", "field_report_weighed",
                                  f"Field report received; {top['cause']} leads with {top['support']} support. "
                                  "Passing it to the verifier instead of escalating.")
                        diag["enough_evidence"] = True
                        break
                    self._stage(inc, "analyse", "fail", "not enough evidence")
                    return self.escalate(inc, f"Not enough evidence after {rounds + 1} rounds; top candidate {top['cause']}")
                self._stage(inc, "analyse", "pass", f"{top['cause']} ({top['support']}), uncertainty {diag.get('uncertainty')}")
                self._checkpoint(inc, ctx, "verify", diag)
            else:
                diag = cp["diag"]

            if phase != "plan":
                diag = self._verify(inc, ctx, diag)
                if diag is None:
                    return
                self._checkpoint(inc, ctx, "plan", diag)
            top = diag["hypotheses"][0]
            inc["status"] = "DIAGNOSIS_READY"
            self._wp(inc, "planner", f"Diagnosis verified ({top['cause'].replace('_', ' ')}); drafting a safe plan",
                     ["Draft a plan that passes the safety rules", "Send it to the owning department"])

            inc["status"] = "PLANNING"
            feedback, chosen = None, None
            attempts = 1 + self.s.max_plan_retries
            for attempt in range(1, attempts + 1):
                self._stage(inc, "plan", "running", f"attempt {attempt}")
                running = self.mplane.get_config(inc["cell_id"])["running"]
                p = agents.plan(ctx, diag, running, feedback)
                if self.flags["red_team"] and attempt == 1:
                    p = _red_team(p, running)
                    self._log(inc, "demo", "red_team", "Red-team switch replaced the first draft with an aggressive plan")
                self._stage(inc, "plan", "pass", f"attempt {attempt}: {p['action'].get('type')}")
                sandbox, sb_err = self._sandbox(inc, p, running)
                ids = {e["id"] for e in inc["evidence"] if e["result"] is not None}
                val = validate_plan(p, inc, running, ids, sandbox, sb_err)
                rec = {"attempt": attempt, "plan": p, "running": running, "sandbox": sandbox,
                       "sandbox_error": sb_err, "validation": val}
                with self.lock:
                    inc["plans"].append(rec)
                self._stage(inc, "validate", "pass" if val["passed"] or (not val["failed"]) else "fail", val["summary"])
                self._log(inc, "validator", "plan_validated" if val["passed"] else "plan_rejected",
                          f"Plan v{attempt}: {val['summary']}" + (f" ({', '.join(val['failed'])})" if val["failed"] else ""),
                          {"rules": val["rules"]})
                if val["passed"] or (not val["failed"] and not val["simulated"]):
                    chosen = rec
                    break
                feedback = [r for r in val["rules"] if r["status"] == "FAIL"]
                hint = self._twin_hint(inc, diag, p, running, val) if attempt < attempts else None
                if hint:
                    feedback.append(hint)
                if attempt == attempts:
                    return self.escalate(inc, f"Plan rejected {attempts} times; last failures: {', '.join(val['failed'])}")
                self._log(inc, "orchestrator", "plan_retry", f"Retry {attempt} of {self.s.max_plan_retries}: sending reasons back to the planner")
            workplan.mark(inc, "Draft a plan that passes the safety rules", "done")
            self._second_opinion(inc, diag, chosen, ctx)
            self._route(inc, chosen, ctx)
            workplan.mark(inc, "Send it to the owning department", "done")
            if inc["status"] != "ESCALATED":
                self._wp(inc, "orchestrator", f"Plan with {inc.get('department') or 'the department'} for a decision")
            inc["checkpoint"] = None
        except ProviderError as e:
            self._interrupted(inc, ctx)
            self.escalate(inc, f"Meta Model API unavailable after retries and fallback model ({e}). ML alert remains active. "
                          f"Progress is saved at the {inc['checkpoint']['phase']} step and resumes when the API is back.")
        except AgentOutputError as e:
            self._interrupted(inc, ctx)
            self.escalate(inc, f"Agent output failed validation after repair: {e}")
        except Exception as e:
            self._log(inc, "orchestrator", "error", f"Unexpected error: {e}", {"traceback": traceback.format_exc()[-2000:]})
            self.escalate(inc, f"Unexpected error: {e}")
        finally:
            with self.lock:
                inc["tool_calls"] = ctx.tool_calls_used
                inc["agent_runs"].extend(ctx.runs)
                self._save(inc)

    def _pause(self, inc: dict, ask: str, why: str, by: str) -> None:
        req = {"id": f"ER-{inc['id'][-3:]}-{len(inc['evidence_requests']) + 1}", "ask": ask, "why": why, "by": by,
               "requested_at": self.sim.now.isoformat(), "status": "open", "answer": None}
        with self.lock:
            inc["evidence_requests"].append(req)
            inc["status"] = "AWAITING_EVIDENCE"
            self._stage(inc, "investigate", "waiting", "waiting for field evidence")
            self._save(inc)
        self._log(inc, by, "evidence_requested", f"{req['id']}: {ask} ({why})", req)
        self._wp(inc, by, "The data cannot settle it; asked a field engineer", [_field_step(ask)])

    def provide_evidence(self, iid: str, user: str, note: str) -> dict:
        inc = self.incidents[iid]
        req = next((r for r in inc["evidence_requests"] if r["status"] == "open"), None)
        if not req or inc["status"] != "AWAITING_EVIDENCE":
            raise ValueError("this incident is not waiting for evidence")
        if not note.strip():
            raise ValueError("write what you found on site")
        since = req["requested_at"]
        photos = [p for p in inc["photos"] if p["uploaded"] >= since]
        docs = [d for d in inc.get("attachments", []) if d["uploaded"] >= since]
        eid = self._evidence_cb(inc)("field_report", {"request": req["id"], "by": user}, {
            "source": f"field engineer {user}", "note": note[:1000], "photos": [p["id"] for p in photos],
            "photo_findings": [p["findings"]["summary"] for p in photos if p.get("findings")],
            "documents": [d["id"] for d in docs],
            "document_findings": [f"{d['name']}: {d['findings']['summary']}" for d in docs if d.get("findings")]}, None)
        with self.lock:
            req.update(status="answered", answer={"by": user, "note": note[:1000], "evidence_id": eid,
                                                  "photos": [p["id"] for p in photos], "documents": [d["id"] for d in docs],
                                                  "at": self.sim.now.isoformat()})
        self._log(inc, user, "evidence_provided", f"{req['id']} answered by {user} ({eid}): {note[:200]}")
        workplan.mark(inc, _field_step(req["ask"]), "done")
        self._wp(inc, user, "Field report received; re-running the investigation with it")
        self._reset_after_detect(inc)
        self._submit(iid, f"Field engineer {user} answered the evidence request ({eid}): {note[:500]}")
        return req

    def sign_off_rca(self, iid: str, user: str, decision: str, note: str = "") -> dict:
        inc = self.incidents[iid]
        ver = inc.get("verification") or {}
        if not ver.get("passed"):
            raise ValueError("only a verified diagnosis can be signed off")
        if decision not in ("confirm", "dispute"):
            raise ValueError("decision must be confirm or dispute")
        cause = inc["diagnosis"]["hypotheses"][0]["cause"]
        rec = {"decision": decision, "by": user, "note": note[:500], "cause": cause, "at": self.sim.now.isoformat()}
        if decision == "confirm":
            inc["rca_signoff"] = rec
            self._log(inc, user, "root_cause_signed_off", f"{user} signed off the root cause: {cause}" + (f" ({note})" if note else ""))
            self._save(inc)
            return rec
        if not note.strip():
            raise ValueError("say why you dispute the root cause")
        if inc["status"] not in ("AWAITING_DEPARTMENT", "ESCALATED"):
            raise ValueError(f"cannot reopen the diagnosis while the incident is {inc['status']}")
        t = self.store.get_ticket(inc["ticket_id"]) if inc.get("ticket_id") else None
        if t and t["status"] == "pending":
            t.update(status="returned", decided_by=user, decision_note=f"root cause disputed: {note}")
            self.store.save_ticket(t)
        inc["rca_signoff"] = rec
        self._log(inc, user, "root_cause_disputed", f"{user} disputed {cause}: {note}")
        self._reset_after_detect(inc)
        self._submit(iid, f"Engineer {user} disputed the root cause {cause}: {note}")
        return rec

    def _checkpoint(self, inc: dict, ctx, phase: str, diag: dict | None = None) -> None:
        with self.lock:
            inc["checkpoint"] = {"phase": phase, "diag": diag, "tool_calls_used": ctx.tool_calls_used,
                                 "saved_at": self.sim.now.isoformat()}
            self._save(inc)

    def _step_saver(self, inc: dict):
        def save(state: dict) -> None:
            with self.lock:
                cp = inc.get("checkpoint") or {}
                if cp.get("phase") == "investigate":
                    cp.update(messages=state["messages"], tool_calls_used=state["tool_calls_used"],
                              saved_at=self.sim.now.isoformat())
                    inc["checkpoint"] = cp
                self._save(inc)
        return save

    def _interrupted(self, inc: dict, ctx) -> None:
        with self.lock:
            cp = inc.get("checkpoint") or {"phase": "investigate"}
            cp.update(resumable=True, at_tick=self.sim.tick)
            cp.setdefault("auto_tries", 0)
            cp.setdefault("tool_calls_used", ctx.tool_calls_used)
            inc["checkpoint"] = cp
        self._log(inc, "orchestrator", "checkpoint_saved",
                  f"Interrupted at the {cp['phase']} step; {len(inc['evidence'])} evidence items and the plan are kept")
        self._wp(inc, "orchestrator", f"Interrupted at the {cp['phase']} step (model API); waiting to resume")

    def resume_investigation(self, iid: str, user: str = "orchestrator") -> dict:
        inc = self.incidents[iid]
        cp = inc.get("checkpoint") or {}
        if inc["status"] != "ESCALATED" or not cp.get("resumable"):
            raise ValueError("this investigation has nothing to resume")
        t = self.store.get_ticket(inc["ticket_id"]) if inc.get("ticket_id") else None
        if t and t["status"] == "pending":
            t.update(status="returned", decided_by=user, decision_note="investigation resumed from its checkpoint")
            self.store.save_ticket(t)
        with self.lock:
            cp["resumable"] = False
            inc.update(escalation=None, ticket_id=None, department=None, escalation_brief=None)
            self._stage(inc, "review", "pending", "")
        self._log(inc, user, "investigation_resumed", f"Resumed at the {cp['phase']} step, keeping {len(inc['evidence'])} evidence items")
        self._wp(inc, user, f"Resumed at the {cp['phase']} step")
        self._submit(iid, resume=True)
        return {"resumed_at": cp["phase"]}

    def _auto_resume(self, inc: dict) -> None:
        cp = inc.get("checkpoint") or {}
        if not cp.get("resumable") or self.flags["api_outage"] != "none" or cp.get("auto_tries", 0) >= 2:
            return
        if self.sim.tick - cp.get("at_tick", self.sim.tick) >= 2:
            cp["auto_tries"] = cp.get("auto_tries", 0) + 1
            self.resume_investigation(inc["id"], "orchestrator")

    def _wp(self, inc: dict, by: str, text: str, steps: list[str] | None = None) -> None:
        with self.lock:
            if steps:
                workplan.add(inc, steps, text, by, self.sim.now.isoformat())
            else:
                workplan.note(inc, text, by, self.sim.now.isoformat())

    def _verify(self, inc, ctx, diag):
        models = [self.s.reviewer_model, self.s.primary_model]
        refusals = 0
        while True:
            self._stage(inc, "verify", "running", f"attempt {refusals + 1}")
            ver = verify.check(ctx, diag, models)
            ver["attempt"] = refusals + 1
            with self.lock:
                inc["verification"] = ver
                if inc["checklist"] and inc["checklist"][0].get("auto"):
                    inc["checklist"] = verify.mark_checklist(inc["checklist"], inc["evidence"], diag)
            cov = ver["coverage"]
            if ver["passed"]:
                self._stage(inc, "verify", "pass", f"playbook {cov['covered']}/{cov['total']}, "
                            f"{sum(f['verified'] for f in ver['facts'])} facts checked")
                self._log(inc, "verifier", "diagnosis_verified", f"Diagnosis {diag['hypotheses'][0]['cause']} passed "
                          f"{len(ver['rules'])} checks (playbook {cov['covered']}/{cov['total']})", {"rules": ver["rules"]})
                return diag
            refusals += 1
            self._log(inc, "verifier", "diagnosis_refused", f"Refusal {refusals}: {', '.join(ver['failed'])}",
                      {"rules": ver["rules"], "feedback": ver["feedback"]})
            self._wp(inc, "verifier", f"Verifier refused the diagnosis ({', '.join(ver['failed'])})",
                     [workplan.label(*t) for t in verify.fetch_plan(ver["fetch"], inc["cell_id"], inc["id"])] or ["Re-analyse with the verifier's reasons"])
            if refusals >= self.s.max_verify_refusals:
                self._stage(inc, "verify", "fail", f"refused {refusals}×: {', '.join(ver['failed'])}")
                self.escalate(inc, f"Diagnosis refused by the verifier {refusals} times; last failures: {', '.join(ver['failed'])}")
                return None
            if ver["fetch"] and ctx.tool_calls_used < ctx.tool_budget:
                self._stage(inc, "investigate", "running", "verifier asked for more evidence")
                agents.investigate(ctx, "The verifier refused the diagnosis. " + " ".join(ver["feedback"]), ver["fetch"])
                self._stage(inc, "investigate", "pass", f"{ctx.tool_calls_used} tool calls")
            diag = agents.analyse(ctx, 0, ver["feedback"])
            inc["diagnosis"] = diag
            self._log(inc, "analyst", "hypotheses_ranked",
                      " › ".join(f"{h['cause']} ({h['support']})" for h in diag["hypotheses"]), diag)

    def _sandbox(self, inc, p, running):
        a = p.get("action") or {}
        spec = ACTIONS.get(a.get("type"))
        if not spec or not spec["param"] or not isinstance(a.get("delta"), (int, float)):
            self._stage(inc, "sandbox", "skipped", "no configuration change")
            return None, None
        self.fallback_twin.force_outage = self.flags["twin_outage"]
        try:
            res = self.twin.simulate(inc["cell_id"], {spec["param"]: running[spec["param"]] + float(a["delta"])})
            self._stage(inc, "sandbox", "pass", f"{res['engine']}: coverage loss {res['coverage_loss_pct']}%")
            self._log(inc, "twin", "what_if", f"{res['engine']}: target PRB {res['before']['prb_util']}→{res['after']['prb_util']}%, "
                      f"neighbour {res['neighbour_before_prb']}→{res['neighbour_after_prb']}%, coverage loss {res['coverage_loss_pct']}%", res)
            return res, None
        except TwinUnavailable as e:
            self._stage(inc, "sandbox", "fail", "not simulated")
            self._log(inc, "twin", "twin_unavailable", f"What-if not run: {e}. Plan flagged 'not simulated' for engineer review")
            return None, str(e)

    def _twin_hint(self, inc, diag, p, running, val):
        if val["failed"] != ["Sandbox impact"]:
            return None
        cause = diag["hypotheses"][0]["cause"]
        target = TARGETS.get(cause)
        cur = (p.get("action") or {}).get("type")
        if not target:
            return None
        k, lim = target
        tried = []
        for alt in sorted(FITS.get(cause, set())):
            spec = ACTIONS.get(alt) or {}
            if alt == cur or not spec.get("param"):
                continue
            delta = spec["max_step"] if alt == "adjust_tilt" else -spec["max_step"]
            new = running[spec["param"]] + delta
            lo, hi = spec["bounds"]
            if not lo <= new <= hi:
                continue
            try:
                res = self.twin.simulate(inc["cell_id"], {spec["param"]: new})
            except TwinUnavailable:
                continue
            ok = (res["after"][k] <= lim and res["coverage_loss_pct"] <= res["limits"]["coverage_loss_pct"]
                  and (res.get("neighbour_after_prb") or 0) <= res["limits"]["neighbour_prb"])
            tried.append(f"{alt} {delta:+g} gives {k} {res['before'][k]}→{res['after'][k]}, neighbour "
                         f"{res.get('neighbour_after_prb')}%, coverage loss {res['coverage_loss_pct']}%"
                         + (" (meets every limit)" if ok else ""))
        if not tried:
            return None
        self._log(inc, "twin", "twin_hint", "Twin tried the other allowed actions for the planner: " + "; ".join(tried))
        return {"rule": "Twin what-if of other allowed actions", "status": "INFO",
                "reason": "A single step of your action cannot reach the target. " + "; ".join(tried)}

    def _second_opinion(self, inc, diag, rec, ctx):
        self._stage(inc, "second_opinion", "running", "")
        models = [self.s.reviewer_model, self.s.primary_model]
        rv = agents.review(ctx, diag, rec, models)
        inc["review"] = rv
        n = len(rv["concerns"])
        self._stage(inc, "second_opinion", "pass", f"{'agrees' if rv['verdict'] == 'agree' else f'{n} concern(s)'} ({rv['by']})")
        self._log(inc, "reviewer", "second_opinion",
                  f"{rv['by']}: " + ("agrees with the plan" if rv["verdict"] == "agree" else "; ".join(rv["concerns"])), rv)

    def _regulatory(self, inc):
        a = regulatory.assess(inc, self.sim.now, self.s.fcc_users_per_site)
        prev = (inc.get("fcc") or {}).get("status")
        inc["fcc"] = a
        if a["status"] != prev and a["status"] != "not_an_outage":
            self._log(inc, "compliance", "fcc_part4", a["summary"], a)
        if a["status"] == "reportable" and not inc.get("regulatory_ticket"):
            self._tseq += 1
            t = {"id": f"TCK-{self._tseq:04d}", "incident_id": inc["id"], "department": DEPARTMENTS["regulatory"],
                 "status": "pending", "created": self.sim.now.isoformat(), "kind": "regulatory", "cell_id": inc["cell_id"],
                 "site": inc["site"], "cause": "fcc_part4",
                 "recommendation": f"{a['summary']} Deadlines: notification {a['deadlines']['notification'][11:16]} PT, "
                                   f"initial report within 72 h, final report within 30 days ({a['rule']}).",
                 "plan": None, "validation": None, "sandbox": None, "not_simulated": False,
                 "decided_by": None, "decision_note": None}
            self.store.save_ticket(t)
            inc["regulatory_ticket"] = t["id"]
            self._log(inc, "compliance", "routed", f"Sent to {t['department']} ({t['id']}) for NORS filing")
        self._save(inc)

    def write_report(self, iid: str) -> dict:
        inc = self.incidents[iid]
        t = self.store.get_ticket(inc["ticket_id"]) if inc.get("ticket_id") else None
        facts = {"id": inc["id"], "title": inc["title"], "area": inc["site"], "zip_code": inc.get("zip_code"),
                 "band": inc.get("band"), "cell_id": inc["cell_id"], "detected": inc["created"], "tz": "PT",
                 "status": inc["status"], "severity": inc["severity"],
                 "diagnosis": ((inc.get("diagnosis") or {}).get("hypotheses") or [])[:2],
                 "plan": (inc["plans"][-1]["plan"] if inc["plans"] else None), "reviewer": inc.get("review"),
                 "department": inc.get("department"),
                 "verification": {k: (inc.get("verification") or {}).get(k) for k in ("passed", "attempt", "failed")},
                 "root_cause_signoff": inc.get("rca_signoff"),
                 "field_evidence": [{"ask": r["ask"], "answer": (r["answer"] or {}).get("note")} for r in inc.get("evidence_requests") or []],
                 "decision": (f"{t['status']} by {t['decided_by']}" if t and t.get("decided_by") else (t or {}).get("status")),
                 "fcc": inc.get("fcc"), "customer_updates": inc.get("customer_status"),
                 "timeline": [{"time": l["sim_ts"][11:16], "actor": l["actor"], "summary": l["summary"][:160]}
                              for l in self.store.ledger(iid) if l["event"] not in ("tool_call", "report_written")]}
        ctx = AgentContext(self.provider, self.toolbox, inc, lambda *a: "", lambda *a: None, 0)
        rep = agents.incident_report(ctx, facts)
        rep["generated_at"] = self.sim.now.isoformat()
        with self.lock:
            inc["report"] = rep
            inc["agent_runs"].extend(ctx.runs)
        self._log(inc, "reporter", "report_written", f"Incident report written ({rep['by']})")
        self._save(inc)
        return rep

    def _route(self, inc: dict, rec: dict, ctx: AgentContext) -> None:
        p, val = rec["plan"], rec["validation"]
        dept = department_for(p["cause"], p["action"]["type"])
        is_config = bool(ACTIONS.get(p["action"]["type"], {}).get("param"))
        self._tseq += 1
        t = {
            "id": f"TCK-{self._tseq:04d}", "incident_id": inc["id"], "department": dept, "status": "pending",
            "created": self.sim.now.isoformat(), "kind": "config_change" if is_config else "field_action",
            "cell_id": inc["cell_id"], "site": inc["site"], "cause": p["cause"],
            "recommendation": p["summary"], "plan": p, "validation": val, "sandbox": rec["sandbox"],
            "not_simulated": not val["simulated"], "decided_by": None, "decision_note": None,
            "review": inc.get("review"),
        }
        self.store.save_ticket(t)
        with self.lock:
            inc.update(status="AWAITING_DEPARTMENT", ticket_id=t["id"], department=dept)
            self._stage(inc, "review", "waiting", f"sent to {dept}" + (" (NOT SIMULATED)" if t["not_simulated"] else ""))
        self._log(inc, "orchestrator", "routed", f"Recommendation sent to {dept} ({t['id']}): {p['summary']}", {"ticket": t["id"]})
        if p["cause"] == "hardware_fault":
            self._customer(inc, "field_team", ctx)

    def escalate(self, inc: dict, reason: str) -> None:
        self._tseq += 1
        t = {"id": f"TCK-{self._tseq:04d}", "incident_id": inc["id"], "department": DEPARTMENTS["escalation"],
             "status": "pending", "created": self.sim.now.isoformat(), "kind": "escalation", "cell_id": inc["cell_id"],
             "site": inc["site"], "cause": (inc.get("diagnosis") or {}).get("hypotheses", [{}])[0].get("cause"),
             "recommendation": reason, "plan": None, "validation": None, "sandbox": None, "not_simulated": False,
             "decided_by": None, "decision_note": None}
        self.store.save_ticket(t)
        with self.lock:
            inc.update(status="ESCALATED", escalation=reason, ticket_id=t["id"], department=t["department"])
            self._stage(inc, "review", "waiting", "escalated to NOC Shift Lead")
            self._save(inc)
        self._log(inc, "orchestrator", "escalated", reason, {"ticket": t["id"]})
        self._wp(inc, "orchestrator", "Handed to the NOC Shift Lead: " + reason[:200])
        if self.sync:
            self._brief(inc, t, reason)
        else:
            self.executor.submit(self._brief, inc, t, reason)

    def _brief(self, inc: dict, t: dict, reason: str) -> None:
        facts = {"incident": inc["id"], "title": inc["title"], "reason": reason, "cell": self.sim.cell_info(inc["cell_id"]),
                 "detection": inc.get("detection"), "hypotheses": ((inc.get("diagnosis") or {}).get("hypotheses") or [])[:4],
                 "plans": [{"attempt": p["attempt"], "plan": p["plan"], "failed_rules": p["validation"]["failed"],
                            "sandbox_error": p["sandbox_error"]} for p in inc["plans"]],
                 "evidence": [{"id": e["id"], "tool": e["tool"], "result": e["result"], "error": e["error"]} for e in inc["evidence"]]}
        ctx = AgentContext(self.provider, self.toolbox, inc, lambda *a: "", lambda *a: None, 0)
        try:
            b = agents.escalation_brief(ctx, facts, [self.s.wonder_model, self.s.primary_model])
        except Exception as e:
            b = {"what_we_know": reason, "what_is_unclear": "", "next_checks": [], "suggested_owner": "NOC Shift Lead",
                 "by": f"not written: {e}"}
        with self.lock:
            inc["escalation_brief"] = b
            inc["agent_runs"].extend(ctx.runs)
            t["brief"] = b
            cur = self.store.get_ticket(t["id"])
            if cur:
                cur["brief"] = b
                self.store.save_ticket(cur)
            self._save(inc)
        self._log(inc, "briefer", "escalation_brief", f"Brief for the Shift Lead ({b['by']}): next checks "
                  + (", ".join(b["next_checks"]) or "none suggested"))

    def add_photo(self, iid: str, image: bytes, mime: str, user: str, note: str = "") -> dict:
        inc = self.incidents[iid]
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            raise ValueError("send a JPEG, PNG or WebP photo")
        if not 0 < len(image) <= 6_000_000:
            raise ValueError("photo must be under 6 MB")
        fielddocs.check_image(image, mime)
        pid = f"PH-{len(self.photos) + 1:03d}"
        self.photos[pid] = (image, mime)
        cause = ((inc.get("diagnosis") or {}).get("hypotheses") or [{}])[0].get("cause")
        rec = {"id": pid, "uploaded": self.sim.now.isoformat(), "by": user, "note": note[:300], "detections": [],
               "findings": None, "errors": [], "width": None, "height": None}
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        for prompt in PHOTO_PROMPTS.get(cause, ["antenna", "cable"]):
            try:
                seg = self.provider.segment(image, mime, prompt)
                rec["detections"] += [{**b, "label": prompt} for b in seg["boxes"]]
                if seg["boxes"]:
                    rec["width"], rec["height"] = seg["boxes"][0]["w"], seg["boxes"][0]["h"]
            except ProviderError as e:
                rec["errors"].append(f"SAM '{prompt}': {e}")
                if self.provider.offline:
                    break
        if not self.provider.offline:
            ctx = AgentContext(self.provider, self.toolbox, inc, lambda *a: "", lambda *a: None, 0)
            facts = {"cell": inc["cell_id"], "area": inc["site"], "band": inc.get("band"), "diagnosis": cause,
                     "alarms": [a["code"] + " " + a["description"] for a in self.sim.active_alarms(inc["cell_id"])],
                     "technician_note": note[:300]}
            try:
                rec["findings"] = agents.photo_findings(ctx, url, rec["detections"][:30], facts,
                                                        [self.s.vision_model, self.s.fallback_model])
            except (ProviderError, AgentOutputError) as e:
                rec["errors"].append(f"vision: {e}")
            inc["agent_runs"].extend(ctx.runs)
        eid = self._evidence_cb(inc)("site_photo", {"photo": pid, "by": user},
                                     {"detections": len(rec["detections"]), "findings": rec["findings"], "note": note[:300]},
                                     None if (rec["findings"] or self.provider.offline) else "; ".join(rec["errors"])[:300])
        rec["evidence_id"] = eid
        with self.lock:
            inc["photos"].append(rec)
            self._save(inc)
        f = rec["findings"]
        self._log(inc, "field-photo", "photo_analysed",
                  f"{pid} from {user}: " + (f"{len(rec['detections'])} object{'s' if len(rec['detections']) != 1 else ''} found (SAM 3.1); {f['summary'][:160]} "
                                            f"Consistent with diagnosis: {f['consistent_with_diagnosis']}." if f
                                            else "stored without analysis (" + ("; ".join(rec["errors"])[:160] or "no Meta key") + ")"))
        return rec

    def add_attachment(self, iid: str, data: bytes, mime: str, name: str, user: str, note: str = "") -> dict:
        name = fielddocs.safe_name(name)
        if mime in fielddocs.IMAGE_TYPES:
            return {"type": "photo", **self.add_photo(iid, data, mime, user, note)}
        inc = self.incidents[iid]
        doc = fielddocs.extract(data, mime, name)
        did = f"DOC-{len(self.files) + 1:03d}"
        self.files[did] = (data, fielddocs.SERVE_AS[doc["kind"]], name)
        cause = ((inc.get("diagnosis") or {}).get("hypotheses") or [{}])[0].get("cause")
        rec = {"id": did, "type": "document", "name": name[:120], "kind": doc["kind"], "size": len(data),
               "uploaded": self.sim.now.isoformat(), "by": user, "note": note[:300], "findings": None, "errors": [],
               "facts": {k: v for k, v in doc.items() if k not in ("text", "kind")}, "excerpt": doc["text"][:600]}
        if self.provider.offline:
            rec["findings"] = agents.document_rules(doc, cause)
        else:
            ctx = AgentContext(self.provider, self.toolbox, inc, lambda *a: "", lambda *a: None, 0)
            facts = {"cell": inc["cell_id"], "area": inc["site"], "diagnosis": cause,
                     "open_request": next((r["ask"] for r in inc["evidence_requests"] if r["status"] == "open"), None),
                     "engineer_note": note[:300]}
            try:
                rec["findings"] = agents.document_findings(ctx, name, doc, facts, [self.s.primary_model, self.s.fallback_model])
            except (ProviderError, AgentOutputError) as e:
                rec["errors"].append(f"analysis: {e}")
                rec["findings"] = agents.document_rules(doc, cause)
            inc["agent_runs"].extend(ctx.runs)
        eid = self._evidence_cb(inc)("field_document", {"file": did, "name": name[:120], "by": user},
                                     {"kind": doc["kind"], "facts": rec["facts"], "findings": rec["findings"], "note": note[:300]}, None)
        rec["evidence_id"] = eid
        with self.lock:
            inc.setdefault("attachments", []).append(rec)
            self._save(inc)
        f = rec["findings"]
        self._log(inc, "field-document", "document_analysed",
                  f"{did} {name[:60]} from {user} ({doc['kind'].upper()}, {f['by']}): {f['summary'][:200]} "
                  f"Consistent with diagnosis: {f['consistent_with_diagnosis']}.")
        return rec

    def write_handover(self) -> dict:
        from .simulator import MARKET
        incs = []
        for i in sorted(self.incidents.values(), key=lambda x: x["id"]):
            incs.append({"id": i["id"], "title": i["title"], "area": i["site"], "zip": i.get("zip_code"), "status": i["status"],
                         "open": i["status"] in OPEN_STATES, "department": i.get("department"), "severity": i["severity"],
                         "top_cause": ((i.get("diagnosis") or {}).get("hypotheses") or [{}])[0].get("cause"),
                         "fcc": (i.get("fcc") or {}).get("summary") if (i.get("fcc") or {}).get("status") != "not_an_outage" else None,
                         "escalation": i.get("escalation"), "photos": len(i.get("photos") or []),
                         "ledger": [{"t": l["sim_ts"][11:16], "actor": l["actor"], "event": l["event"], "summary": l["summary"][:300]}
                                    for l in self.store.ledger(i["id"]) if l["event"] != "tool_call"]})
        calls = self.provider.calls[-200:]
        facts = {"market": MARKET["name"], "tz": MARKET["tz_label"], "generated": self.sim.now.isoformat(), "incidents": incs,
                 "model_health": {"calls": len(calls), "failed": sum(not c["ok"] for c in calls),
                                  "models_used": sorted({c["model"] for c in calls if c["ok"]})},
                 "tickets_pending": [{"id": t["id"], "department": t["department"], "kind": t["kind"], "incident": t["incident_id"]}
                                     for t in self.store.list_tickets() if t["status"] == "pending"]}
        ctx = AgentContext(self.provider, self.toolbox, {}, lambda *a: "", lambda *a: None, 0)
        h = agents.shift_handover(ctx, facts, [self.s.wonder_model, self.s.primary_model])
        h.update(generated_at=self.sim.now.isoformat(), incidents=len(incs), input_chars=len(json.dumps(facts, default=str)))
        self.handover = h
        return h

    def decide(self, ticket_id: str, decision: str, user: str, note: str = "") -> dict:
        t = self.store.get_ticket(ticket_id)
        if not t:
            raise KeyError("ticket not found")
        if t["status"] not in ("pending", "in_progress"):
            raise ValueError(f"ticket is already {t['status']}")
        inc = self.incidents[t["incident_id"]]
        t.update(decided_by=user, decision_note=note)
        if decision == "reject":
            if not note.strip():
                raise ValueError("a reason is required to reject")
            t["status"] = "rejected"
            with self.lock:
                inc["status"] = "REJECTED"
                self._stage(inc, "review", "fail", f"rejected by {user}")
                self._close_cell(inc)
            self._log(inc, user, "rejected", f"{t['department']} rejected: {note}")
        elif decision == "more_info":
            t["status"] = "returned"
            self._log(inc, user, "more_info_requested", f"{t['department']} asked for more information: {note}")
            self._reset_after_detect(inc)
            self._submit(inc["id"], note or "Engineer requested more information.")
        elif decision == "approve":
            if t["kind"] == "escalation":
                raise ValueError("escalations are closed or sent back, not approved")
            t["status"] = "approved" if t["kind"] == "config_change" else "in_progress"
            self._log(inc, user, "approved", f"{t['department']} approved: {note or 'no comment'}")
            self._stage(inc, "review", "pass", f"approved by {user}")
            if t["kind"] == "config_change":
                self._apply_change(inc, t)
            else:
                with self.lock:
                    inc["status"] = "FIELD_WORK"
                    self._stage(inc, "change", "waiting", f"{t['department']} working on site")
                    self._save(inc)
        elif decision == "resolved":
            if t["kind"] not in ("field_action", "data_quality"):
                raise ValueError("only field or data tickets are marked resolved")
            t["status"] = "done"
            self.sim.clear_fault(inc["cell_id"])
            self._log(inc, user, "field_fix_reported", f"{t['department']}: {note or 'fix completed'}")
            self._stage(inc, "change", "pass", "fixed on site")
            self._start_monitoring(inc, config_change=False)
        elif decision == "filed":
            if t["kind"] != "regulatory":
                raise ValueError("only regulatory tickets are marked filed")
            t["status"] = "done"
            self._log(inc, user, "nors_filed", f"{t['department']}: {note or 'NORS notification filed'}")
            self.store.save_ticket(t)
            return t
        elif decision == "close":
            t["status"] = "closed"
            with self.lock:
                inc["status"] = "CLOSED"
                self._close_cell(inc)
            self._log(inc, user, "closed", note or "Closed by engineer")
        else:
            raise ValueError("unknown decision")
        self.store.save_ticket(t)
        self._save(inc)
        return t

    def _apply_change(self, inc: dict, t: dict) -> None:
        a = t["plan"]["action"]
        param = ACTIONS[a["type"]]["param"]
        running = self.mplane.get_config(inc["cell_id"])["running"]
        pkg = self.mplane.build_change_package(inc["cell_id"], {param: running[param] + float(a["delta"])}, inc["id"])
        dry = self.mplane.dry_run(pkg)
        inc["change"] = {"package": pkg, "dry_run": dry}
        if not dry["ok"]:
            self._stage(inc, "change", "fail", "dry run failed")
            return self.escalate(inc, "M-Plane dry run failed: " + "; ".join(dry["errors"]))
        try:
            res = self.mplane.apply(pkg)
        except MPlaneError as e:
            self._stage(inc, "change", "fail", str(e))
            return self.escalate(inc, f"M-Plane apply failed: {e}")
        inc["change"]["applied"] = res
        self._stage(inc, "change", "pass", f"{param} → {pkg['changes'][param]:.1f} (confirmed-commit pending)")
        self._log(inc, "m-plane", "change_applied",
                  f"edit-config + confirmed-commit on simulated radio unit: {param} {running[param]:.1f} → {pkg['changes'][param]:.1f}; "
                  f"auto-rollback in {pkg['confirm_timeout_s'] // 60} min unless confirmed", {"package": pkg})
        self._customer(inc, "fix_approved")
        self._start_monitoring(inc, config_change=True)

    def _start_monitoring(self, inc: dict, config_change: bool) -> None:
        with self.lock:
            inc["status"] = "MONITORING"
            inc["monitoring"] = {"start_tick": self.sim.tick, "ticks": 0, "ok_streak": 0, "config_change": config_change}
            self._stage(inc, "monitor", "running", "watching recovery criteria")
            self._save(inc)

    def _monitor(self, inc: dict) -> None:
        m = inc["monitoring"]
        m["ticks"] += 1
        cid = inc["cell_id"]
        row = self.sim.latest(cid) or {}
        if row.get("missing"):
            m["ok_streak"] = 0
            ok, reasons = False, ["data still missing"]
        elif inc["kind"] == "data_quality":
            ok, reasons = True, []
        else:
            ok, reasons = _recovered(row)
        if m["config_change"] and cid in self.mplane.pending and not row.get("missing"):
            nb = self.sim.latest(self.sim.cells[cid].offload_to) or {}
            if row["ho_success"] < 96.0 or (nb.get("prb_util") or 0) > 92.0:
                self.mplane.cancel(cid, "guard tripped")
                self._log(inc, "monitor", "rollback", f"Guard tripped (handover {row['ho_success']}%, neighbour PRB {nb.get('prb_util')}%): change rolled back")
                return self._reopen(inc, "The change was rolled back because a guard tripped.")
        if ok:
            m["ok_streak"] += 1
            if m["ok_streak"] >= 2:
                if cid in self.mplane.pending:
                    self.mplane.confirm(cid)
                    self._log(inc, "m-plane", "commit_confirmed", "Recovery held for 2 windows: confirmed-commit sent, change kept")
                    self._stage(inc, "change", "pass", inc["stages"]["change"]["note"].replace("confirmed-commit pending", "confirmed"))
                with self.lock:
                    inc["status"] = "RESOLVED"
                    inc["resolved_at"] = self.sim.now.isoformat()
                    self._stage(inc, "monitor", "pass", f"recovered after {m['ticks']} windows")
                    self._close_cell(inc)
                self._log(inc, "monitor", "resolved", "Recovery criteria met for 2 consecutive windows")
                t = self.store.get_ticket(inc["ticket_id"]) if inc.get("ticket_id") else None
                if t and t["status"] in ("pending", "approved", "in_progress", "done"):
                    t["status"] = "closed"
                    self.store.save_ticket(t)
                if inc.get("customer_status"):
                    self._customer(inc, "resolved")
                self._save(inc)
            return
        m["ok_streak"] = 0
        self._stage(inc, "monitor", "running", "; ".join(reasons))
        if m["ticks"] >= self.s.monitor_ticks:
            if cid in self.mplane.pending:
                self.mplane.cancel(cid, "recovery not reached")
                self._log(inc, "monitor", "rollback", "Recovery not reached in time: change rolled back")
            self._reopen(inc, "Previous fix did not recover the cell: " + "; ".join(reasons))
        self._save(inc)

    def _reopen(self, inc: dict, why: str) -> None:
        if inc["reopen_count"] >= self.s.max_reopen:
            self._stage(inc, "monitor", "fail", "not recovered")
            return self.escalate(inc, f"Not recovered after {inc['reopen_count'] + 1} attempts. {why}")
        inc["reopen_count"] += 1
        self._log(inc, "orchestrator", "reopened", f"Investigation reopened ({inc['reopen_count']}/{self.s.max_reopen}): {why}")
        self._reset_after_detect(inc)
        self._submit(inc["id"], why)

    def _reset_after_detect(self, inc: dict) -> None:
        with self.lock:
            for s in STAGES[1:]:
                inc["stages"][s] = {"status": "pending", "note": ""}
            inc["status"] = "INVESTIGATING"

    def _auto_remediate_dq(self, inc: dict) -> None:
        cid = inc["cell_id"]
        if not (self.sim.latest(cid) or {}).get("missing"):
            self._log(inc, "data-quality", "auto_fixed", "KPI data flowing again")
            self._stage(inc, "change", "pass", "data restored")
            return self._start_monitoring(inc, config_change=False)
        if inc["repoll_attempts"] < 2:
            inc["repoll_attempts"] += 1
            fault = self.sim.faults.get(cid) or {}
            transient = fault.get("type") == "data_dropout" and fault.get("severity") == 1
            if transient:
                self.sim.clear_fault(cid)
            self._log(inc, "data-quality", "repoll", f"Automatic re-poll of the PM collector ({inc['repoll_attempts']}/2): "
                      + ("file received" if transient else "still no file"))
            self._stage(inc, "investigate", "running", f"auto re-poll {inc['repoll_attempts']}/2")
            self._save(inc)
            return
        self._tseq += 1
        t = {"id": f"TCK-{self._tseq:04d}", "incident_id": inc["id"], "department": DEPARTMENTS["data_quality"],
             "status": "pending", "created": self.sim.now.isoformat(), "kind": "data_quality", "cell_id": cid,
             "site": inc["site"], "cause": "data_quality",
             "recommendation": f"Automatic re-polls failed. Restart the PM collector for {inc['site']} and check the OSS link "
                               f"for {cid}. Anomaly detection is paused on this cell's missing windows.",
             "plan": None, "validation": None, "sandbox": None, "not_simulated": False, "decided_by": None, "decision_note": None}
        self.store.save_ticket(t)
        inc.update(status="AWAITING_DEPARTMENT", ticket_id=t["id"], department=t["department"])
        self._stage(inc, "investigate", "pass", "2 automatic re-polls failed")
        self._stage(inc, "review", "waiting", f"sent to {t['department']}")
        self._log(inc, "orchestrator", "routed", f"Sent to {t['department']} ({t['id']})")
        self._save(inc)

    def inject(self, cell_id: str, fault_type: str, severity: int) -> dict:
        with self.lock:
            f = self.sim.inject_fault(cell_id, fault_type, severity)
        return f

    def clear_faults(self) -> None:
        with self.lock:
            self.sim.clear_all()
            for cid in list(self.mplane.pending):
                self.mplane.pending.pop(cid, None)

    def _evidence_cb(self, inc):
        def cb(tool, args, result, error):
            with self.lock:
                eid = f"E{len(inc['evidence']) + 1}"
                inc["evidence"].append({"id": eid, "tool": tool, "args": args, "result": result, "error": error,
                                        "observed_at": self.sim.now.isoformat()})
                self._save(inc)
            summary = f"{eid}: {tool}({json.dumps(args)})" + (f" failed: {error}" if error else "")
            self._log(inc, "investigator", "tool_call" if not error else "tool_error", summary)
            return eid
        return cb

    def _trace_cb(self, inc):
        def cb(agent, kind, data):
            with self.lock:
                inc["trace"].append({"agent": agent, "kind": kind, "data": data, "sim_ts": self.sim.now.isoformat()})
            if kind == "output_rejected":
                self._log(inc, agent, "output_repair", f"Output failed checks (attempt {data['attempt']}): {'; '.join(data['errors'])[:300]}")
            if kind == "field_request_refused":
                self._log(inc, agent, "field_request_refused", "Field visit not requested yet: data tools come first")
        return cb

    def _stage(self, inc, stage, status, note):
        with self.lock:
            inc["stages"][stage] = {"status": status, "note": note}

    def _log(self, inc, actor, event, summary, payload=None):
        self.store.log(inc["id"], self.sim.now.isoformat(), actor, event, summary, payload)

    def _save(self, inc):
        with self.lock:
            self.store.save_incident(copy.deepcopy(inc))

    def _close_cell(self, inc):
        if self.open_by_cell.get(inc["cell_id"]) == inc["id"]:
            self.open_by_cell.pop(inc["cell_id"], None)
        for c, pid in list(self.related.items()):
            if pid == inc["id"]:
                self.related.pop(c, None)

    def _customer(self, inc, status, ctx: AgentContext | None = None):
        if ctx is None:
            ctx = AgentContext(self.provider, self.toolbox, inc, lambda *a: "", lambda *a: None, 0)
        msg = agents.customer_update(ctx, inc["site"], status)
        inc["customer_status"] = status
        self.store.publish_update(inc["id"], inc["site"], status, f"{msg['headline']}. {msg['message']}", self.sim.now.isoformat())
        self._log(inc, "customer-comms", "customer_update", f"Published ({msg['by']}): {msg['headline']}")

    def snapshot(self, inc: dict) -> dict:
        with self.lock:
            snap = json.loads(json.dumps(inc, default=str))
        cp = snap.get("checkpoint")
        if cp:
            snap["checkpoint"] = {**{k: v for k, v in cp.items() if k not in ("messages", "diag")},
                                  "steps_saved": sum(m.get("role") == "tool" for m in cp.get("messages") or [])}
        return snap


def _field_step(ask: str) -> str:
    first = ask.split(". ")[0].rstrip(".")
    return "Wait for the field: " + (first if len(first) <= 110 else first[:107] + "...")


def _severity(row: dict) -> str:
    if row.get("availability", 100) < 99.9 or row.get("drop_rate", 0) > 2.0:
        return "critical"
    if row.get("prb_util", 0) > 90 or row.get("sinr_db", 20) < 6 or row.get("far_user_share", 0) > 0.18:
        return "major"
    return "minor"


def _kind_title(det: dict, row: dict) -> str:
    b = det.get("breaches") or []
    if any("PRB" in x for x in b):
        return "High load"
    if any("SINR" in x or "RSSI" in x for x in b):
        return "Radio quality degraded"
    if any("availability" in x or "Drop" in x for x in b):
        return "Dropped calls rising"
    if any("Far" in x for x in b):
        return "Coverage anomaly"
    return "KPI anomaly"


def _recovered(row: dict) -> tuple[bool, list[str]]:
    checks = [("prb_util", "<", 85.0), ("drop_rate", "<", 1.5), ("ho_success", ">=", 97.0), ("sinr_db", ">=", 6.0),
              ("far_user_share", "<", 0.15), ("availability", ">=", 99.9)]
    reasons = []
    for k, op, lim in checks:
        v = row[k]
        ok = v < lim if op == "<" else v >= lim
        if not ok:
            reasons.append(f"{k} {v} (needs {op} {lim})")
    return not reasons, reasons


def _red_team(p: dict, running: dict) -> dict:
    q = copy.deepcopy(p)
    if p["action"].get("type") == "adjust_tilt":
        q["action"] = {"type": "adjust_tilt", "cell_id": p["action"]["cell_id"], "delta": 5.0}
    else:
        q["action"] = {"type": "adjust_tx_power", "cell_id": p["action"]["cell_id"], "delta": -6.0}
    q["rollback"] = {}
    q["summary"] = "[red-team draft] " + q.get("summary", "")
    q["red_team"] = True
    return q
