import json
from datetime import datetime, timedelta

import pytest
from conftest import run_until

from app import agents
from app.care import Care, CREDIT_AMOUNT


def _home_incident(sentinel, fault="hardware"):
    sentinel.inject("SEA-RAN-001", fault, 2)
    inc = run_until(sentinel, "SEA-RAN-001", ticks=6)
    assert inc and inc["customer_status"], "a published update is the gate for customers"
    return inc


def test_quiet_network_has_no_alerts(sentinel):
    c = Care(sentinel)
    c.sync()
    assert c.notifications == [] and all(c.place_status(p)["status"] == "normal" for p in c.places)


def test_outage_at_home_notifies_with_estimate_and_safe_text(sentinel):
    inc = _home_incident(sentinel)
    c = Care(sentinel)
    c.sync()
    n = c.notifications[0]
    assert n["kind"] == "alert" and n["place"] == "Home" and n["reference"] == inc["id"]
    home = c.place_status(c.places[0])
    issue = home["issue"]
    assert issue["eta"]["state"] == "estimating" and issue["eta"]["low_min"] < issue["eta"]["high_min"]
    assert [j["state"] for j in issue["journey"]].count("current") == 1
    blob = json.dumps({"n": c.notifications, "issue": issue})
    assert not agents.FORBIDDEN.search(blob), "no cell IDs or settings reach the customer"
    assert any(s["id"] == "wifi_calling" for s in home["suggestions"])
    c.sync()
    assert len(c.notifications) == 1, "no duplicate alert for an unchanged state"


def test_report_is_evidence_for_engineers_and_never_changes_state(sentinel):
    inc = _home_incident(sentinel)
    status = inc["status"]
    c = Care(sentinel)
    r = c.report("home", "no_service", "Nothing since lunch")
    assert r["outcome"] == "linked" and r["linked"] == inc["id"]
    assert inc["evidence"][-1]["tool"] == "customer_report" and inc["status"] == status
    r2 = c.report("gym", "slow_data")
    assert r2["outcome"] == "device_check" and r2["suggestions"][0]["id"] == "airplane"
    with pytest.raises(ValueError):
        c.report("home", "bogus")


def test_credit_policy_and_customer_confirmation(sentinel):
    inc = _home_incident(sentinel)
    c = Care(sentinel)
    assert not any(x["eligible"] for x in c.credit_status())
    inc["created"] = (sentinel.sim.now - timedelta(minutes=45)).isoformat()
    el = [x for x in c.credit_status() if x["eligible"]]
    assert el and el[0]["reference"] == inc["id"]
    p = c.tool("propose_action", {"type": "credit", "reference": inc["id"]})
    assert c.credits == [], "proposing changes nothing"
    assert "credit applied" in c.confirm(p["proposed"])["done"]
    assert c.credits[0]["amount"] == CREDIT_AMOUNT
    with pytest.raises(ValueError):
        c.apply_credit(inc["id"])
    assert any(l["event"] == "service_credit" for l in sentinel.store.ledger(inc["id"]))


def test_concierge_rules_path_is_grounded(sentinel):
    _home_incident(sentinel)
    c = Care(sentinel)
    r = c.concierge("When will my service be back?")
    assert r["by"] == "rules" and "Home" in r["answer"] and "Estimated" in r["answer"]
    assert r["steps"][0]["tool"] == "get_my_service" and r["actions"][0]["type"] == "setting"
    assert "None of your places qualify" in c.concierge("Can I get a credit?")["answer"]
    z = c.concierge("Is there an issue in 98119?")
    assert "Queen Anne" in z["answer"]


class CareDouble:
    offline = False
    label = "test double"

    def __init__(self, final):
        self.turn, self.final, self.outage, self.calls = 0, final, "none", []

    def chat(self, messages, tools=None, agent="", models=None):
        self.turn += 1
        if self.turn == 1:
            return {"content": "", "tool_calls": [{"id": "t1", "name": "get_my_service", "arguments": "{}"},
                                                   {"id": "t2", "name": "propose_action", "arguments": json.dumps({"type": "setting", "setting": "wifi_calling", "value": True})}]}, {"model": "muse-spark-1.3"}
        return {"content": json.dumps(self.final), "tool_calls": []}, {"model": "muse-spark-1.3"}


def test_concierge_tool_calls_and_safety_filter(sentinel):
    _home_incident(sentinel)
    c = Care(sentinel)
    sentinel.provider = CareDouble({"answer": "Engineers are repairing equipment near Home. Tap Confirm below to turn on Wi-Fi Calling.", "action_ids": ["A1"]})
    r = c.concierge("My phone has no signal at home")
    assert r["by"] == "muse-spark-1.3" and [s["tool"] for s in r["steps"]] == ["get_my_service", "propose_action"]
    assert r["actions"][0]["setting"] == "wifi_calling" and c.prefs["wifi_calling"] is False
    c.confirm(r["actions"][0]["id"])
    assert c.prefs["wifi_calling"] is True
    sentinel.provider = CareDouble({"answer": "Cell SEA-RAN-001 has VSWR alarm E3.", "action_ids": []})
    r = c.concierge("why?")
    assert r["by"] == "rules (AI unavailable)" and "SEA-RAN" not in r["answer"]
