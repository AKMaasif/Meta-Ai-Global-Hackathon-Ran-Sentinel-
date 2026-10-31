import pytest
from conftest import run_until
from test_llm_path import ScriptedLLM, make

NOTE = "Spectrum analyser shows a narrowband emitter, looks like a signal booster in the office block east of the site."


def _paused(sentinel, fault="interference"):
    sentinel.flags["diag_outage"] = True
    sentinel.inject("SEA-RAN-001", fault, 2)
    return run_until(sentinel, "SEA-RAN-001", ticks=6)


def test_agent_pauses_and_asks_the_field_instead_of_guessing(sentinel):
    inc = _paused(sentinel)
    assert inc["status"] == "AWAITING_EVIDENCE"
    req = inc["evidence_requests"][0]
    assert req["status"] == "open" and "spectrum analyser" in req["ask"].lower()
    assert not inc["plans"] and inc["ticket_id"] is None
    assert inc["stages"]["investigate"]["status"] == "waiting"


def test_field_report_resumes_and_settles_the_diagnosis(sentinel):
    inc = _paused(sentinel)
    before = len(inc["evidence"])
    sentinel.provide_evidence(inc["id"], "Sarah Chen", NOTE)
    assert inc["status"] == "AWAITING_DEPARTMENT", inc.get("escalation")
    assert len(inc["evidence"]) > before
    fr = [e for e in inc["evidence"] if e["tool"] == "field_report"]
    assert fr and fr[0]["result"]["note"] == NOTE
    top = inc["diagnosis"]["hypotheses"][0]
    assert top["cause"] == "external_interference" and fr[0]["id"] in top["supporting_evidence"]
    ver = inc["verification"]
    assert ver["passed"] and any("field report" in r["reason"] for r in ver["rules"] if r["rule"] == "Confirming check run")
    assert inc["evidence_requests"][0]["answer"]["evidence_id"] == fr[0]["id"]


def test_second_dead_end_escalates_instead_of_asking_again(sentinel):
    inc = _paused(sentinel)
    sentinel.provide_evidence(inc["id"], "Sarah Chen", "Nothing unusual seen on site.")
    assert inc["status"] == "ESCALATED" and "Not enough evidence" in inc["escalation"]
    assert len(inc["evidence_requests"]) == 1


def test_answer_needs_text_and_an_open_request(sentinel):
    inc = _paused(sentinel)
    with pytest.raises(ValueError):
        sentinel.provide_evidence(inc["id"], "Sarah Chen", "  ")
    sentinel.provide_evidence(inc["id"], "Sarah Chen", NOTE)
    with pytest.raises(ValueError):
        sentinel.provide_evidence(inc["id"], "Sarah Chen", NOTE)


def test_model_investigator_can_request_evidence():
    ask = ("request_evidence", '{"ask": "Photograph the feeder connectors", "why": "hardware or interference"}')
    data = [("get_kpi_window", '{"cell_id": "SEA-RAN-001", "metrics": ["prb_util", "sinr_db"]}'),
            ("get_alarm_history", '{"cell_id": "SEA-RAN-001"}'),
            ("get_cell_configuration", '{"cell_id": "SEA-RAN-001"}'),
            ("run_diagnostic_check", '{"cell_id": "SEA-RAN-001", "check": "vswr_and_power_readback"}'),
            ("get_kpi_window", '{"cell_id": "SEA-RAN-001", "metrics": ["drop_rate"]}')]

    class Asker(ScriptedLLM):
        script = [ask] + data + [ask]

        def chat(self, messages, tools=None, agent="", models=None):
            if agent == "investigator" and self.script:
                self.calls.append(agent)
                name, args = self.script.pop(0)
                return {"content": "", "tool_calls": [{"id": f"r{len(self.script)}", "name": name, "arguments": args}]}, \
                    {"agent": agent, "ok": True}
            return super().chat(messages, tools, agent, models)
    sen = make(Asker())
    sen.inject("SEA-RAN-001", "hardware", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert any(l["event"] == "field_request_refused" for l in sen.store.ledger(inc["id"]))
    assert inc["status"] == "AWAITING_EVIDENCE"
    assert inc["evidence_requests"][0]["by"] == "investigator" and "feeder" in inc["evidence_requests"][0]["ask"]


def test_engineer_signs_off_or_disputes_the_root_cause(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    assert inc["status"] == "AWAITING_DEPARTMENT"
    with pytest.raises(ValueError):
        sentinel.sign_off_rca(inc["id"], "Sarah Chen", "dispute", "")
    tid = inc["ticket_id"]
    sentinel.sign_off_rca(inc["id"], "Sarah Chen", "dispute", "Stadium is empty today; check the neighbour first.")
    assert sentinel.store.get_ticket(tid)["status"] == "returned"
    assert any(l["event"] == "root_cause_disputed" for l in sentinel.store.ledger(inc["id"]))
    assert inc["status"] == "AWAITING_DEPARTMENT" and inc["ticket_id"] != tid
    rec = sentinel.sign_off_rca(inc["id"], "Sarah Chen", "confirm", "Agree")
    assert inc["rca_signoff"] == rec and rec["cause"] == inc["diagnosis"]["hypotheses"][0]["cause"]
