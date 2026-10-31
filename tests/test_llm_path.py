import json
import re
import types

from conftest import offline_settings, run_until

from app.config import Settings
from app.orchestrator import Sentinel
from app.providers import MetaProvider, ProviderError
from app.safety import READ_ONLY_CHECKS
from app.store import Store


class ScriptedLLM:
    offline = False
    label = "Meta Model API (scripted test double)"

    def __init__(self):
        self.outage = "none"
        self.calls = []
        self.analyst_calls = 0
        self.comms_calls = 0
        self.fail = False
        self.fact_error = 0
        self.claims = []
        self.fail_investigator_at = None

    def chat(self, messages, tools=None, agent="", models=None):
        self.calls.append(agent)
        meta = {"agent": agent, "model": "muse-spark-1.3", "ok": True}
        if self.fail:
            raise ProviderError("muse-spark-1.2: APIConnectionError")
        if agent == "investigator":
            user = json.loads(messages[1]["content"])
            done = sum(m["role"] == "assistant" and bool(m.get("tool_calls")) for m in messages)
            if user["requested_checks"]:
                calls = [("run_diagnostic_check", {"check": c, "cell_id": user["cell_id"]}) if c in READ_ONLY_CHECKS
                         else (c, {"cell_id": user["cell_id"], "metrics": ["prb_util", "sinr_db"]} if c == "get_kpi_window"
                               else {"incident_id": user["incident_id"]} if c == "get_anomaly_result" else {"cell_id": user["cell_id"]})
                         for c in user["requested_checks"]]
            else:
                calls = [("update_plan", {"steps": [{"step": "Read the detector result"}, {"step": "Pull the KPI trend"},
                                                    {"step": "Read the radio configuration"}], "note": "Start broad"}),
                         ("get_anomaly_result", {"incident_id": user["incident_id"]}),
                         ("get_kpi_window", {"cell_id": user["cell_id"], "metrics": ["prb_util", "sinr_db"]}),
                         ("get_cell_configuration", {"cell_id": "SEA-RAN-999"})]
            if done < len(calls):
                n, a = calls[done]
                if self.fail_investigator_at == done:
                    raise ProviderError("muse-spark-1.3: APIConnectionError")
                return {"content": "", "tool_calls": [{"id": f"c{done}", "name": n, "arguments": json.dumps(a)}]}, meta
            return {"content": '{"summary": "done", "evidence_ids": [], "missing": []}', "tool_calls": []}, meta
        if agent == "analyst":
            self.analyst_calls += 1
            if self.analyst_calls == 1:
                return {"content": "I think it is capacity.", "tool_calls": []}, meta
            ids = sorted(set(re.findall(r"^(E\d+) \[", messages[1]["content"], re.M)))
            ran_check = "neighbour_load" in messages[1]["content"]
            kpi = re.search(r"^(E\d+) \[get_kpi_window.*?\]: (.*)$", messages[1]["content"], re.M)
            facts = [{"evidence_id": kpi.group(1), "metric": "prb_util",
                      "value": json.loads(kpi.group(2))["series"]["prb_util"][-1] + self.fact_error}] if kpi else []
            return {"content": json.dumps({"hypotheses": [
                {"cause": "capacity_congestion", "rank": 1, "support": "strong", "supporting_evidence": ids[:2], "contradicting_evidence": [], "reasoning": "load"},
                {"cause": "external_interference", "rank": 2, "support": "none", "supporting_evidence": [], "contradicting_evidence": ids[:1], "reasoning": "sinr ok"}],
                "key_facts": facts, "enough_evidence": ran_check, "requested_checks": [] if ran_check else ["neighbour_load"], "uncertainty": "low"}), "tool_calls": []}, meta
        if agent == "planner":
            u = messages[1]["content"]
            run = json.loads(u.split("\nEvidence:")[0])["running_config"]
            ids = re.findall(r"^(E\d+) \[", u, re.M)
            return {"content": "```json\n" + json.dumps({"cause": "capacity_congestion", "summary": "Reduce power 3 dB",
                    "prerequisite_checks": ["neighbour_load"], "action": {"type": "adjust_tx_power", "cell_id": "SEA-RAN-001", "delta": -3},
                    "expected_effect": "load down", "risks": [], "rollback": {"restore_value": run["tx_power_dbm"], "trigger": "ho < 97%"},
                    "monitoring": "4 windows", "evidence_ids": ids[:1]}) + "\n```", "tool_calls": []}, meta
        if agent == "claims_checker":
            return {"content": json.dumps({"unsupported_claims": self.claims}), "tool_calls": []}, meta
        if agent == "reviewer":
            return {"content": json.dumps({"verdict": "concerns", "concerns": ["Neighbour headroom is small."],
                                           "questions_for_department": ["Is a second neighbour available?"]}), "tool_calls": []}, meta
        if agent == "customer_comms":
            self.comms_calls += 1
            text = "Fix on SEA-RAN-001 tilt" if self.comms_calls == 1 else "Slower service downtown"
            return {"content": json.dumps({"headline": text, "message": "Engineers are on it."}), "tool_calls": []}, meta
        return {"content": "Service is being restored.", "tool_calls": []}, meta


def make(llm):
    sen = Sentinel(offline_settings(), Store(":memory:"), llm)
    sen.sync = True
    return sen


def test_llm_agents_with_tools_repair_and_evidence_loop():
    llm = ScriptedLLM()
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "AWAITING_DEPARTMENT", inc.get("escalation")
    assert any(e["error"] for e in inc["evidence"])
    assert inc["evidence_rounds"] == 1
    assert any(l["event"] == "output_repair" for l in sen.store.ledger(inc["id"]))
    assert inc["plans"][-1]["validation"]["passed"]
    ups = [u["text"] for u in sen.store.customer_updates()]
    assert ups and not any("SEA-RAN" in u for u in ups)


def test_api_down_escalates_but_keeps_alert():
    llm = ScriptedLLM()
    llm.fail = True
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "ESCALATED" and "Meta Model API unavailable" in inc["escalation"]
    assert inc["department"] == "NOC Shift Lead"


def test_meta_provider_falls_back_to_second_model(monkeypatch):
    s = Settings()
    s.api_key = "test-not-a-real-key"
    p = MetaProvider(s)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    used = []

    def create(**kw):
        used.append(kw["model"])
        if kw["model"] == s.primary_model:
            raise TimeoutError("primary timed out")
        msg = types.SimpleNamespace(content="ok", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")], usage=None, model=kw["model"])

    p.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    out, meta = p.chat([{"role": "user", "content": "hi"}], agent="t")
    assert out["content"] == "ok" and meta["model"] == s.fallback_model
    assert used == [s.primary_model, s.primary_model, s.fallback_model]


def test_meta_provider_all_down_raises(monkeypatch):
    s = Settings()
    s.api_key = "test-not-a-real-key"
    p = MetaProvider(s)
    p.outage = "all_down"
    monkeypatch.setattr("time.sleep", lambda *_: None)
    try:
        p.chat([{"role": "user", "content": "hi"}])
        assert False
    except ProviderError:
        pass
