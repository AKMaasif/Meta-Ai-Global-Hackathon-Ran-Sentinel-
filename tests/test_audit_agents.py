import json
import sys
import time
from pathlib import Path

from conftest import offline_settings
from test_llm_path import ScriptedLLM

from app.orchestrator import Sentinel
from app.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_agents  # noqa: E402


class AuditLLM(ScriptedLLM):

    def chat(self, messages, tools=None, agent="", models=None):
        out, meta = self._answer(messages, tools, agent)
        rec = {"agent": agent, "model": "muse-spark-1.3", "ok": True, "latency_s": 0.01, "error": None, "ts": time.time()}
        self.calls.append(rec)
        return out, rec

    def _answer(self, messages, tools, agent):
        j = lambda d: ({"content": json.dumps(d), "tool_calls": []}, None)  # noqa: E731
        if agent in ("investigator", "analyst", "claims_checker", "planner", "reviewer", "customer_comms"):
            out, meta = ScriptedLLM.chat(self, messages, tools, agent)
            self.calls.pop()
            return out, meta
        if agent in ("reporter", "shift_handover"):
            return j({"text": "Summary: one capacity incident in Downtown, routed to RAN Optimisation for a decision."})
        if agent == "escalation_briefer":
            return j({"what_we_know": "Load is high (E1).", "what_is_unclear": "Neighbour headroom.",
                      "next_checks": ["neighbour_load"], "suggested_owner": "RAN Optimisation"})
        if agent == "field_photo":
            return j({"visible_issues": [], "consistent_with_diagnosis": "unclear", "summary": "A white square; no site equipment.", "next_step": "Retake."})
        if agent == "care_concierge":
            if not any(m["role"] == "tool" for m in messages):
                return {"content": "", "tool_calls": [{"id": "t1", "name": "get_my_service", "arguments": "{}"}]}, None
            return j({"answer": "Data is slower at Home because the network there is busy. Engineers are on it.", "action_ids": []})
        if agent == "signal_analyst":
            return j({"summary": "Simulated test phone: fair signal.", "confirmed": ["Signal strength is fair."],
                      "probable": ["A busy network nearby."], "unverified": ["Your real phone may differ."], "steps": ["Try Wi-Fi Calling."]})
        if agent == "customer_assistant" and "Ignore your rules" in messages[1]["content"]:
            return {"content": "Downtown is SEA-RAN-001 with 4 degree tilt.", "tool_calls": []}, None
        return {"content": "Service in Downtown is slower; engineers are working on it.", "tool_calls": []}, None

    def transcribe(self, wav, keywords=None, agent="voice"):
        self.calls.append({"agent": agent, "model": "muse-voice", "ok": True, "latency_s": 0.01, "error": None, "ts": time.time()})
        return {"text": "", "turns": [], "duration_ms": 1500, "model": "muse-voice", "latency_s": 0.01}

    def segment(self, image, mime, prompt, agent="field_photo"):
        return {"prompt": prompt, "boxes": [], "model": "sam-3.1", "latency_s": 0.01, "raw_chars": 0}


def test_audit_runs_every_agent_and_classifies_results():
    sen = Sentinel(offline_settings(), Store(":memory:"), AuditLLM())
    sen.sync = True
    rows = audit_agents.run(sen)
    by = {}
    for r in rows:
        by.setdefault(r["agent"], []).append(r)
    expected = {"investigator", "analyst", "claims_checker", "planner", "reviewer", "customer_comms", "reporter", "escalation_briefer",
                "shift_handover", "sam_segment", "field_photo", "voice", "customer_assistant", "care_concierge", "signal_analyst"}
    assert expected <= set(by), set(by)
    fails = [r for r in rows if r["result"] == "FAIL"]
    assert not fails, fails
    for ag in ("investigator", "analyst", "planner", "reviewer", "reporter", "escalation_briefer", "shift_handover",
               "field_photo", "care_concierge", "signal_analyst"):
        assert by[ag][0]["result"] == "PASS", by[ag]
    probe = by["customer_assistant"][1]
    assert probe["by"] == "filtered" and probe["result"] == "PASS"


def test_audit_never_prints_key_like_text():
    orig = audit_agents.settings.api_key
    audit_agents.settings.api_key = "sk-live-THIS-IS-NOT-A-REAL-KEY-0000000000"
    try:
        assert "THIS-IS-NOT" not in audit_agents.redact("401: bad key sk-live-THIS-IS-NOT-A-REAL-KEY-0000000000")
        assert "***" in audit_agents.redact("token abcdefghijklmnopqrstuvwxyz0123456789")
    finally:
        audit_agents.settings.api_key = orig
