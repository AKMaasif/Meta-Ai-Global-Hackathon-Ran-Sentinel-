import importlib.util
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from conftest import run_until

from app import agents, regulatory
from app.providers import OfflineProvider

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cells_carry_us_bands_and_zip_codes(sentinel):
    c = sentinel.sim.cell_info("SEA-RAN-001")
    assert c["zip_code"] == "98101" and c["band"].startswith("B66")
    assert sentinel.mplane.get_config("SEA-RAN-001")["running"]["earfcn"] == 66786
    assert {x.band.split()[0] for x in sentinel.sim.cells.values()} == {"B66", "B2", "B71"}


def test_fcc_check_degradation_is_not_an_outage(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    sentinel.tick()
    assert inc["fcc"]["status"] == "not_an_outage"


def test_fcc_check_hardware_outage_below_then_above_threshold():
    t0 = datetime(2026, 11, 3, 20, 0)
    inc = {"created": t0.isoformat(), "kind": "network", "kpi_at_detection": {"availability": 99.2},
           "diagnosis": {"hypotheses": [{"cause": "hardware_fault"}]}}
    a = regulatory.assess(inc, t0 + timedelta(minutes=60), users_per_site=1500)
    assert a["status"] == "below_threshold" and a["user_minutes"] == 500 * 60
    b = regulatory.assess(inc, t0 + timedelta(minutes=60), users_per_site=60000)
    assert b["status"] == "reportable"
    assert b["deadlines"]["notification"] == (t0 + timedelta(minutes=120)).isoformat()
    c = regulatory.assess(inc, t0 + timedelta(minutes=20), users_per_site=10_000_000)
    assert c["status"] == "below_threshold"


def test_reportable_outage_creates_compliance_ticket(sentinel):
    sentinel.s.fcc_users_per_site = 300_000
    sentinel.inject("SEA-RAN-004", "hardware", 2)
    inc = run_until(sentinel, "SEA-RAN-004")
    for _ in range(4):
        sentinel.tick()
    assert inc["fcc"]["status"] == "reportable"
    t = sentinel.store.get_ticket(inc["regulatory_ticket"])
    assert t["department"] == "Regulatory Compliance" and t["kind"] == "regulatory"
    assert sentinel.decide(t["id"], "filed", "Sarah Chen", "NORS notification submitted")["status"] == "done"
    assert sentinel.store.get_ticket(inc["ticket_id"])["status"] == "pending"


def test_zip_code_answers_for_that_area():
    areas = [{"area": "Downtown", "zip": "98101", "status": "degraded", "text": "Slower service downtown."},
             {"area": "Ballard", "zip": "98107", "status": "normal", "text": "No known issues."}]
    p = OfflineProvider()
    assert "Slower service downtown" in agents.answer_customer(p, "Problems in 98101?", [], areas)["answer"]
    assert "no known problems in Ballard" in agents.answer_customer(p, "is ballard ok", [], areas)["answer"]
    assert "outside" in agents.answer_customer(p, "what about 98052", [], areas)["answer"]


def test_reviewer_runs_and_travels_with_the_ticket(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    assert inc["status"] == "AWAITING_DEPARTMENT"
    assert inc["stages"]["second_opinion"]["status"] == "pass"
    assert inc["review"]["verdict"] in ("agree", "concerns")
    assert sentinel.store.get_ticket(inc["ticket_id"])["review"] == inc["review"]


def test_incident_report_from_ledger(sentinel):
    sentinel.inject("SEA-RAN-007", "hardware", 2)
    inc = run_until(sentinel, "SEA-RAN-007")
    rep = sentinel.write_report(inc["id"])
    assert inc["id"] in rep["text"] and "FCC Part 4" in rep["text"] and rep["by"] == "template"


TYPES = ["Antenna Failure", "Co-Channel Interference (Severe)", "High Network Congestion (Sudden Spike)", "Jamming"]


def _fake_telecomts(path: Path, n=320):
    rng = random.Random(0)
    with path.open("w") as f:
        for i in range(n):
            anomalous = i % 4 == 0
            typ = TYPES[(i // 4) % len(TYPES)] if anomalous else None
            shift = {None: 0, TYPES[0]: -8, TYPES[1]: 5, TYPES[2]: 12, TYPES[3]: 9}[typ]
            k = {"DL_bitrate": [rng.gauss(20 + shift, 2) for _ in range(128)],
                 "RSRP": [rng.gauss(-90 - (shift if typ == TYPES[0] else 0), 1) for _ in range(128)],
                 "SINR": [rng.gauss(15 - (shift if typ in TYPES[1:4:2] else 0), 1) for _ in range(128)],
                 "UL_Protocol": [rng.choice(["TCP", "UDP", None]) for _ in range(128)]}
            labels = {"zone": "AB"[i % 2], "application": "File", "mobility": "No", "congestion": "No"}
            f.write(json.dumps({"KPIs": k, "anomalies": {"exists": anomalous, "type": typ}, "labels": labels,
                                "QnA": {"x": "y"}}) + "\n")


def test_telecomts_benchmark_pipeline_on_schema_fixture(tmp_path):
    bench = _load_script("benchmark_telecomts")
    data = tmp_path / "scenario" / "chunked.jsonl"
    data.parent.mkdir()
    _fake_telecomts(data)
    d = bench.load(bench.find_files(tmp_path))
    res = bench.evaluate(d)
    assert res["windows"] == 320 and res["features_per_window"] == 3 * 17 + 3
    u = res["unsupervised"]
    assert u["selected"] in u["detectors"] and u["detectors"]["mahalanobis_context"]["test"]["roc_auc"] > 0.8
    assert res["supervised_gbt"]["f1"] > 0.8 and res["root_cause"]["accuracy"] > 0.8
    assert "sentinel_causes" in res["root_cause"]
    table = tmp_path / "f.csv.gz"
    bench.export_features(d, table)
    again = bench.evaluate(bench.load_features(table))
    assert again["unsupervised"]["selected"] == u["selected"]
    assert abs(again["supervised_gbt"]["f1"] - res["supervised_gbt"]["f1"]) < 1e-6


def test_live_detector_uses_cell_baseline(sentinel):
    det = sentinel.detector
    assert det.baseline is not None
    sentinel.inject("SEA-RAN-001", "overshoot", 1)
    sentinel.tick()
    r = det.evaluate(sentinel.sim.latest("SEA-RAN-001"), "SEA-RAN-001")
    assert r["baseline_score"] is not None and "triggered_by" in r


def test_model_card_reads_benchmark_files():
    sim = ROOT / "data" / "benchmarks" / "simulator.json"
    if sim.exists():
        d = json.loads(sim.read_text())
        assert d["detection"]["combined"]["detection_rate"] >= d["detection"]["thresholds_only"]["detection_rate"]
