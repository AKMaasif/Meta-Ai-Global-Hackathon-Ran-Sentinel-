from conftest import run_until
from test_llm_path import ScriptedLLM, make

from app import workplan
from app.providers import ProviderError


def test_offline_plan_tracks_every_step(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    wp = inc["work_plan"]
    steps = {s["step"]: s["status"] for s in wp["steps"]}
    assert steps["Read the detector result"] == "done" and steps["Run neighbour load"] == "done"
    assert steps["Send it to the owning department"] == "done"
    assert not [s for s in wp["steps"] if s["status"] in ("todo", "doing")]
    assert wp["revision"] >= 4 and any("Leading cause" in h["note"] for h in wp["history"])


def test_model_writes_its_own_plan_and_runs_one_tool_per_turn():
    llm = ScriptedLLM()
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    wp = inc["work_plan"]
    assert wp["history"][0] == {**wp["history"][0], "by": "investigator", "note": "Start broad"}
    assert [s["step"] for s in wp["steps"][:3]] == ["Read the detector result", "Pull the KPI trend", "Read the radio configuration"]
    assert [s["status"] for s in wp["steps"][:3]] == ["done", "done", "dropped"]
    assert all(s["by"] != "investigator" or s["step"] in {"Read the detector result", "Pull the KPI trend",
               "Read the radio configuration"} for s in wp["steps"])


def test_plan_rejects_bad_updates():
    inc = {}
    assert "2-10 steps" in workplan.replace(inc, [{"step": "only one"}], "why", "investigator", "t")
    assert "why" in workplan.replace(inc, [{"step": "a"}, {"step": "b"}], " ", "investigator", "t")
    p = workplan.replace(inc, [{"step": "a", "status": "weird"}, {"step": "b", "status": "done"}], "ok", "investigator", "t")
    assert [s["status"] for s in p["steps"]] == ["todo", "done"] and p["revision"] == 1


def test_api_failure_mid_investigation_resumes_from_the_saved_step():
    llm = ScriptedLLM()
    llm.fail_investigator_at = 2
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "ESCALATED" and "resumes when the API is back" in inc["escalation"]
    cp = inc["checkpoint"]
    assert cp["resumable"] and cp["phase"] == "investigate" and len(cp["messages"]) >= 5
    assert [e["tool"] for e in inc["evidence"]] == ["get_anomaly_result"]
    snap = sen.snapshot(inc)
    assert "messages" not in snap["checkpoint"] and snap["checkpoint"]["steps_saved"] == 2

    llm.fail_investigator_at = None
    old_ticket = inc["ticket_id"]
    sen.resume_investigation(inc["id"], "Sarah Chen")
    assert inc["status"] == "AWAITING_DEPARTMENT", inc.get("escalation")
    tools = [e["tool"] for e in inc["evidence"]]
    assert tools.count("get_anomaly_result") == 1
    assert "get_kpi_window" in tools
    assert sen.store.get_ticket(old_ticket)["status"] == "returned" and inc["checkpoint"] is None


def test_failure_after_analysis_resumes_without_reinvestigating():
    class FailOnce(ScriptedLLM):
        def chat(self, messages, tools=None, agent="", models=None):
            if agent == "planner" and not getattr(self, "failed", False):
                self.failed = True
                raise ProviderError("muse-spark-1.3: timeout")
            return super().chat(messages, tools, agent, models)
    llm = FailOnce()
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "ESCALATED" and inc["checkpoint"]["phase"] == "plan"
    before = (llm.calls.count("investigator"), llm.calls.count("analyst"), llm.calls.count("claims_checker"))
    sen.resume_investigation(inc["id"])
    assert inc["status"] == "AWAITING_DEPARTMENT"
    assert (llm.calls.count("investigator"), llm.calls.count("analyst"), llm.calls.count("claims_checker")) == before


def test_auto_resume_after_two_windows_once_the_api_is_back():
    llm = ScriptedLLM()
    llm.fail = True
    sen = make(llm)
    sen.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sen, "SEA-RAN-001")
    assert inc["status"] == "ESCALATED"
    llm.fail = False
    sen.tick()
    assert inc["status"] == "ESCALATED"
    sen.tick()
    assert inc["status"] == "AWAITING_DEPARTMENT"
    assert any(l["event"] == "investigation_resumed" for l in sen.store.ledger(inc["id"]))
