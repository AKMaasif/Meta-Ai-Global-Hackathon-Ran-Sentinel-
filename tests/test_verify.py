import pytest
from conftest import run_until
from test_llm_path import ScriptedLLM, make

from app import verify

FAULTS = [("SEA-RAN-001", "capacity_surge", "capacity_congestion"),
          ("SEA-RAN-001", "interference", "external_interference"),
          ("SEA-RAN-001", "overshoot", "overshooting_coverage"),
          ("SEA-RAN-001", "hardware", "hardware_fault")]


@pytest.mark.parametrize("cid,fault,cause", FAULTS)
def test_offline_diagnosis_passes_verifier_for_every_fault(sentinel, cid, fault, cause):
    sentinel.inject(cid, fault, 2)
    inc = run_until(sentinel, cid, ticks=6)
    ver = inc["verification"]
    assert ver and ver["passed"], ver and ver["rules"]
    assert ver["cause"] == cause and verify.truth_score(inc["diagnosis"], fault)["correct"]
    assert ver["coverage"]["score"] == 1.0
    assert ver["facts"] and all(f["verified"] for f in ver["facts"])
    assert inc["stages"]["verify"]["status"] == "pass"
    assert len(inc["checklist"]) == 5 and all(i["done"] for i in inc["checklist"])


def _ev(eid, tool, args, result):
    return {"id": eid, "tool": tool, "args": args, "result": result, "error": None}


def test_fact_check_finds_values_and_refuses_made_up_ones():
    ev = [_ev("E1", "get_kpi_window", {}, {"series": {"prb_util": [80.0, 93.4]}}),
          _ev("E2", "run_diagnostic_check", {"check": "neighbour_load"},
              {"neighbours": [{"cell_id": "X", "prb_util": 61.2, "is_offload_target": True}]})]
    assert verify.check_fact(ev, {"evidence_id": "E1", "metric": "prb_util", "value": 93.4}) is None
    assert verify.check_fact(ev, {"evidence_id": "E2", "metric": "prb_util", "value": 61.2}) is None
    assert "not 97" in verify.check_fact(ev, {"evidence_id": "E1", "metric": "prb_util", "value": 97})
    assert "no 'sinr_db'" in verify.check_fact(ev, {"evidence_id": "E1", "metric": "sinr_db", "value": 9})
    assert "not a successful" in verify.check_fact(ev, {"evidence_id": "E9", "metric": "prb_util", "value": 1})


def test_playbook_coverage_names_what_is_missing_not_the_answer():
    ev = [_ev("E1", "get_anomaly_result", {}, {}), _ev("E2", "get_kpi_window", {}, {"series": {"prb_util": [95]}})]
    cov = verify.coverage(ev, "capacity_congestion")
    missing = {i["fetch"] for i in cov["items"] if not i["covered"]}
    assert missing == {"get_alarm_history", "get_kpi_window", "neighbour_load"}
    assert cov["covered"] == 2 and cov["total"] == 5


def test_made_up_number_is_refused_then_escalates_after_three():
    llm = ScriptedLLM()
    llm.fact_error = 7.5
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "ESCALATED" and "refused by the verifier 3 times" in inc["escalation"]
    assert "Facts match the evidence" in inc["verification"]["failed"]
    assert not inc["plans"]
    refusals = [l for l in sen.store.ledger(inc["id"]) if l["event"] == "diagnosis_refused"]
    assert len(refusals) == 3
    assert llm.calls.count("claims_checker") == 3


def test_unsupported_claim_is_refused_and_feedback_reaches_the_analyst():
    llm = ScriptedLLM()
    llm.claims = [{"claim": "A stadium event is under way", "why": "no evidence of an event"}]
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "ESCALATED"
    assert "Claims check" in inc["verification"]["failed"]
    assert inc["verification"]["claims"][0]["claim"].startswith("A stadium")


def test_verifier_fetches_missing_evidence_then_passes():
    llm = ScriptedLLM()
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "AWAITING_DEPARTMENT", inc.get("escalation")
    assert inc["verification"]["passed"] and inc["verification"]["attempt"] == 2
    assert any(e["tool"] == "get_alarm_history" for e in inc["evidence"])
    assert inc["verification"]["claims_by"] == "muse-spark-1.3"


def test_model_checklist_needs_counter_evidence_item():
    from app.agents import set_checklist
    from types import SimpleNamespace
    ctx = SimpleNamespace(incident={}, trace=lambda *a: None)
    items = [{"item": f"step {i}"} for i in range(4)]
    assert "counter_evidence" in set_checklist(ctx, {"items": items})["error"]
    assert "4-8" in set_checklist(ctx, {"items": items[:2]})["error"]
    items[3]["counter_evidence"] = True
    assert set_checklist(ctx, {"items": items})["ok"] and len(ctx.incident["checklist"]) == 4
