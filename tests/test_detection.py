import numpy as np
import pytest

from app.detection import Detector, check_quality, features
from app.simulator import NetworkSimulator, training_rows


@pytest.fixture(scope="module")
def detector():
    rows = training_rows()
    return Detector(np.array([features(r) for r in rows]), rows=rows)


def test_no_false_alerts_on_normal_day(detector):
    sim = NetworkSimulator(seed=3)
    alerts = 0
    for _ in range(96):
        sim.step()
        alerts += sum(detector.evaluate(sim.latest(c), c)["alert"] for c in sim.cells)
    assert alerts == 0


@pytest.mark.parametrize("fault,cell", [("capacity_surge", "SEA-RAN-001"), ("interference", "SEA-RAN-010"),
                                        ("overshoot", "SEA-RAN-014"), ("hardware", "SEA-RAN-020")])
def test_each_fault_is_detected(detector, fault, cell):
    sim = NetworkSimulator(seed=5)
    sim.inject_fault(cell, fault, 2)
    hit = False
    for _ in range(3):
        sim.step()
        hit = hit or detector.evaluate(sim.latest(cell), cell)["alert"]
    assert hit


def test_missing_data_is_quality_issue_not_anomaly(detector):
    sim = NetworkSimulator(seed=5)
    sim.inject_fault("SEA-RAN-030", "data_dropout", 2)
    for _ in range(2):
        sim.step()
        r = detector.evaluate(sim.latest("SEA-RAN-030"), "SEA-RAN-030")
    assert r["data_quality_alert"] and not r["alert"]


def test_out_of_range_values_flagged():
    assert check_quality({"prb_util": 140, "active_users": 1, "dl_thpt_mbps": 1, "cqi": 9, "sinr_db": 10, "ul_rssi_dbm": -105,
                          "drop_rate": 0.4, "ho_success": 99, "far_user_share": 0.1, "availability": 100})
