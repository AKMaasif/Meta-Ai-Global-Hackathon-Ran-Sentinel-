from app.safety import validate_plan

INC = {"id": "RNS-1", "cell_id": "SEA-RAN-001"}
RUNNING = {"tx_power_dbm": 43.0, "tilt_deg": 4.0}
GOOD_SANDBOX = {"coverage_loss_pct": 0.0, "neighbour_after_prb": 60.0, "after": {"prb_util": 78.0, "far_user_share": 0.08},
                "limits": {"coverage_loss_pct": 1.0, "neighbour_prb": 85.0}}


def plan(**over):
    p = {"cause": "capacity_congestion", "summary": "x", "prerequisite_checks": ["neighbour_load"],
         "action": {"type": "adjust_tx_power", "cell_id": "SEA-RAN-001", "delta": -3.0},
         "rollback": {"restore_value": 43.0, "trigger": "ho < 97%"}, "evidence_ids": ["E1"]}
    p.update(over)
    return p


def check(p, sandbox=GOOD_SANDBOX, err=None):
    return validate_plan(p, INC, RUNNING, {"E1", "E2"}, sandbox, err)


def test_good_plan_passes():
    r = check(plan())
    assert r["passed"], r


def test_unknown_action_rejected():
    r = check(plan(action={"type": "reboot_site", "cell_id": "SEA-RAN-001"}))
    assert not r["passed"] and "Action in allow-list" in r["failed"]


def test_step_over_limit_rejected():
    r = check(plan(action={"type": "adjust_tx_power", "cell_id": "SEA-RAN-001", "delta": -6.0}))
    assert "Step within limit" in r["failed"]


def test_out_of_bounds_rejected():
    r = validate_plan(plan(action={"type": "adjust_tx_power", "cell_id": "SEA-RAN-001", "delta": -3.0}), INC,
                      {"tx_power_dbm": 39.0, "tilt_deg": 4.0}, {"E1"}, GOOD_SANDBOX)
    assert "Result within bounds" in r["failed"]


def test_missing_rollback_rejected():
    assert "Rollback restores current value" in check(plan(rollback={}))["failed"]


def test_wrong_rollback_value_rejected():
    assert "Rollback restores current value" in check(plan(rollback={"restore_value": 46.0, "trigger": "x"}))["failed"]


def test_action_must_fit_diagnosis():
    r = check(plan(cause="external_interference"))
    assert "Fits the diagnosis" in r["failed"]


def test_other_cell_rejected():
    r = check(plan(action={"type": "adjust_tx_power", "cell_id": "SEA-RAN-002", "delta": -1.0}))
    assert "Targets the incident cell" in r["failed"]


def test_uncited_or_unknown_evidence_rejected():
    assert "Evidence cited" in check(plan(evidence_ids=[]))["failed"]
    assert "Evidence cited" in check(plan(evidence_ids=["E9"]))["failed"]


def test_needs_read_only_checks_first():
    assert "Read-only checks first" in check(plan(prerequisite_checks=["delete_everything"]))["failed"]


def test_sandbox_coverage_loss_rejected():
    bad = {**GOOD_SANDBOX, "coverage_loss_pct": 6.0}
    assert "Sandbox impact" in check(plan(), sandbox=bad)["failed"]


def test_sandbox_target_not_met_rejected():
    bad = {**GOOD_SANDBOX, "after": {"prb_util": 91.0, "far_user_share": 0.08}}
    assert "Sandbox impact" in check(plan(), sandbox=bad)["failed"]


def test_not_simulated_never_passes():
    r = check(plan(), sandbox=None, err="twin down")
    assert not r["passed"] and not r["simulated"] and not r["failed"]


def test_non_config_plan_skips_sandbox():
    r = check(plan(cause="hardware_fault", action={"type": "no_config_change", "cell_id": "SEA-RAN-001"}, rollback={},
                   prerequisite_checks=["vswr_and_power_readback"]), sandbox=None)
    assert r["passed"], r


def test_twin_hint_points_planner_to_an_action_that_meets_the_target():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import offline_settings, run_until
    from app.orchestrator import Sentinel
    from app.providers import OfflineProvider
    from app.store import Store
    sen = Sentinel(offline_settings(), Store(":memory:"), OfflineProvider())
    sen.sync = True
    sen.inject("SEA-RAN-010", "capacity_surge", 3)
    inc = run_until(sen, "SEA-RAN-010", ticks=8)
    running = sen.mplane.get_config("SEA-RAN-010")["running"]
    diag = {"hypotheses": [{"cause": "capacity_congestion"}]}
    plan = {"action": {"type": "adjust_tilt", "cell_id": "SEA-RAN-010", "delta": 2.0}}
    hint = sen._twin_hint(inc, diag, plan, running, {"failed": ["Sandbox impact"]})
    assert hint and hint["status"] == "INFO" and "adjust_tx_power -3" in hint["reason"]
    assert sen._twin_hint(inc, diag, plan, running, {"failed": ["Step within limit"]}) is None
