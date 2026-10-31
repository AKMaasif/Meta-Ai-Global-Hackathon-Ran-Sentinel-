from conftest import run_until


def finish(sen, inc, ticks=6):
    for _ in range(ticks):
        sen.tick()
        if inc["status"] != "MONITORING":
            break
    return inc


def test_capacity_red_team_then_fix_and_resolve(sentinel):
    sentinel.flags["red_team"] = True
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    assert inc and inc["status"] == "AWAITING_DEPARTMENT"
    assert inc["diagnosis"]["hypotheses"][0]["cause"] == "capacity_congestion"
    assert inc["evidence_rounds"] >= 1
    assert not inc["plans"][0]["validation"]["passed"]
    assert inc["plans"][-1]["validation"]["passed"]
    assert inc["department"] == "RAN Optimisation"
    sentinel.decide(inc["ticket_id"], "approve", "tester", "ok")
    assert inc["change"]["dry_run"]["ok"]
    finish(sentinel, inc)
    assert inc["status"] == "RESOLVED"
    assert "SEA-RAN-001" not in sentinel.mplane.pending
    assert sentinel.sim.cells["SEA-RAN-001"].config.tx_power_dbm < 43.0


def test_overshoot_restores_tilt(sentinel):
    sentinel.inject("SEA-RAN-014", "overshoot", 2)
    inc = run_until(sentinel, "SEA-RAN-014")
    assert inc["diagnosis"]["hypotheses"][0]["cause"] == "overshooting_coverage"
    assert inc["plans"][-1]["plan"]["action"]["type"] == "adjust_tilt"
    sentinel.decide(inc["ticket_id"], "approve", "tester")
    assert finish(sentinel, inc)["status"] == "RESOLVED"


def test_interference_goes_to_rf_engineering(sentinel):
    sentinel.inject("SEA-RAN-010", "interference", 2)
    inc = run_until(sentinel, "SEA-RAN-010")
    assert inc["department"] == "RF Engineering"
    sentinel.decide(inc["ticket_id"], "approve", "rf")
    assert inc["status"] == "FIELD_WORK"
    sentinel.decide(inc["ticket_id"], "resolved", "rf", "illegal repeater removed")
    assert finish(sentinel, inc)["status"] == "RESOLVED"


def test_hardware_goes_to_field_ops_with_customer_update(sentinel):
    sentinel.inject("SEA-RAN-020", "hardware", 2)
    inc = run_until(sentinel, "SEA-RAN-020")
    assert inc["department"] == "Field Operations"
    statuses = [u["status"] for u in sentinel.store.customer_updates() if u["incident_id"] == inc["id"]]
    assert "field_team" in statuses


def test_data_dropout_auto_repolls_then_routes(sentinel):
    sentinel.inject("SEA-RAN-030", "data_dropout", 2)
    inc = run_until(sentinel, "SEA-RAN-030")
    assert inc["kind"] == "data_quality"
    for _ in range(3):
        sentinel.tick()
    assert inc["status"] == "AWAITING_DEPARTMENT" and inc["department"] == "NOC Data Platform"
    sentinel.decide(inc["ticket_id"], "resolved", "noc", "collector restarted")
    assert finish(sentinel, inc)["status"] == "RESOLVED"


def test_transient_dropout_fixed_automatically(sentinel):
    sentinel.inject("SEA-RAN-033", "data_dropout", 1)
    inc = run_until(sentinel, "SEA-RAN-033")
    for _ in range(5):
        sentinel.tick()
    assert inc["status"] == "RESOLVED" and inc["ticket_id"] is None


def test_twin_outage_flags_not_simulated(sentinel):
    sentinel.flags["twin_outage"] = True
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    t = sentinel.store.get_ticket(inc["ticket_id"])
    assert t["not_simulated"] and not inc["plans"][-1]["validation"]["passed"]


def test_neighbour_symptoms_attach_to_parent(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 3)
    inc = run_until(sentinel, "SEA-RAN-001")
    for _ in range(2):
        sentinel.tick()
    assert all(i["id"] == inc["id"] or i["cell_id"] not in inc["neighbours"] for i in sentinel.incidents.values())


def test_rejection_requires_reason(sentinel):
    sentinel.inject("SEA-RAN-014", "overshoot", 2)
    inc = run_until(sentinel, "SEA-RAN-014")
    import pytest
    with pytest.raises(ValueError):
        sentinel.decide(inc["ticket_id"], "reject", "tester", "")
    sentinel.decide(inc["ticket_id"], "reject", "tester", "maintenance window tomorrow")
    assert inc["status"] == "REJECTED"


def test_failed_fix_rolls_back_and_reopens(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    sentinel.decide(inc["ticket_id"], "approve", "tester")
    sentinel.sim.inject_fault("SEA-RAN-001", "capacity_surge", 3)
    sentinel.sim.cells["SEA-RAN-001"].capacity_users = 90.0
    for _ in range(6):
        sentinel.tick()
        if inc["reopen_count"]:
            break
    assert inc["reopen_count"] == 1
    assert any(l["event"] == "rollback" for l in sentinel.store.ledger(inc["id"]))
