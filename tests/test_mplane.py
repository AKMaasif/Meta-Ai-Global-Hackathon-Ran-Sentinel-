import xml.etree.ElementTree as ET

from app.mplane import CONFIRM_TIMEOUT_TICKS, MPlaneClient
from app.simulator import NetworkSimulator


def test_package_is_wellformed_and_has_rollback():
    sim = NetworkSimulator(history=False)
    m = MPlaneClient(sim)
    pkg = m.build_change_package("SEA-RAN-001", {"tx_power_dbm": 40.0}, "RNS-1")
    ET.fromstring(pkg["edit_config"])
    assert "<confirmed/>" in pkg["commit"] and pkg["rollback_values"] == {"tx_power_dbm": 43.0}
    assert m.dry_run(pkg)["ok"]


def test_dry_run_rejects_out_of_capability():
    m = MPlaneClient(NetworkSimulator(history=False))
    pkg = m.build_change_package("SEA-RAN-001", {"tx_power_dbm": 52.0}, "RNS-1")
    assert not m.dry_run(pkg)["ok"]


def test_unconfirmed_commit_rolls_back_by_itself():
    sim = NetworkSimulator(history=False)
    m = MPlaneClient(sim)
    m.apply(m.build_change_package("SEA-RAN-001", {"tx_power_dbm": 40.0}, "RNS-1"))
    assert sim.cells["SEA-RAN-001"].config.tx_power_dbm == 40.0
    for _ in range(CONFIRM_TIMEOUT_TICKS):
        sim.step()
        m.on_tick()
    assert sim.cells["SEA-RAN-001"].config.tx_power_dbm == 43.0


def test_confirmed_commit_keeps_change():
    sim = NetworkSimulator(history=False)
    m = MPlaneClient(sim)
    m.apply(m.build_change_package("SEA-RAN-001", {"tilt_deg": 5.0}, "RNS-1"))
    assert m.confirm("SEA-RAN-001")
    for _ in range(CONFIRM_TIMEOUT_TICKS + 1):
        sim.step()
        m.on_tick()
    assert sim.cells["SEA-RAN-001"].config.tilt_deg == 5.0


def test_second_change_blocked_while_pending():
    m = MPlaneClient(NetworkSimulator(history=False))
    m.apply(m.build_change_package("SEA-RAN-001", {"tilt_deg": 5.0}, "RNS-1"))
    assert not m.dry_run(m.build_change_package("SEA-RAN-001", {"tilt_deg": 6.0}, "RNS-2"))["ok"]
