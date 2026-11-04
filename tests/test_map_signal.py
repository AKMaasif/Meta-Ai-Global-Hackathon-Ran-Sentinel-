import json
import math

import pytest
from conftest import run_until
from fastapi.testclient import TestClient

from app import main, radio
from app.care import MAP_RADIUS_KM, Care


def test_sites_sit_near_their_real_neighbourhoods():
    ref = {"Downtown": (47.606, -122.332), "SoDo": (47.580, -122.330), "Fremont": (47.651, -122.350), "Ballard": (47.668, -122.385)}
    from app.simulator import SITES
    for name, x, y, _ in SITES:
        if name in ref:
            lat, lon = radio.to_latlon(x, y)
            dkm = math.hypot((lat - ref[name][0]) * 110.6, (lon - ref[name][1]) * 75.0)
            assert dkm < 1.6, (name, dkm)


def test_quality_bands_are_per_metric():
    assert radio.rate("rsrp_dbm", -75) == "excellent" and radio.rate("rsrp_dbm", -105) == "poor"
    assert radio.rate("sinr_db", 15) == "good" and radio.rate("latency_ms", 150) == "fair"
    assert radio.rate("packet_loss_pct", 0.0) == "excellent" and radio.rate("packet_loss_pct", None) == "unknown"
    assert radio.overall({"connected": False}) == ("disconnected", [])


def test_customer_map_is_limited_to_their_area(sentinel):
    c = Care(sentinel)
    m = c.map("home")
    assert m["towers"] and all(t["distance_km"] <= MAP_RADIUS_KM for t in m["towers"])
    assert len({t["area"] for t in m["towers"]}) < 12, "never the whole network"
    blob = json.dumps(m)
    assert "SEA-RAN" not in blob and "tx_power" not in blob and "tilt" not in blob
    assert sum(t["serving"] for t in m["towers"]) <= 1
    with pytest.raises(ValueError):
        c.map("someone-elses-place")
    with pytest.raises(ValueError):
        c.move_phone("home", 47.69, -122.40)


def test_serving_tower_comes_from_the_radio_model_not_distance(sentinel):
    c = Care(sentinel)
    s = c.signal("home")
    assert s["source"]["kind"] == "simulated" and s["connection"] in ("connected", "degraded")
    assert set(s["metrics"]) == {"rsrp_dbm", "rsrq_db", "sinr_db", "latency_ms", "packet_loss_pct"}
    assert len(s["series"]) >= 2 and s["serving"]["name"].startswith("Northstar tower")
    px, py = c.phone_xy("home")
    m = c.measure_now(px, py)
    best = max((radio._rsrp(cell, sentinel.sim.latest(cid), px, py)[0], cell.site) for cid, cell in sentinel.sim.cells.items())
    assert m["serving_site"] == best[1]


def test_hardware_fault_weakens_the_modelled_signal(sentinel):
    c = Care(sentinel)
    before = c.signal("home")["metrics"]["rsrp_dbm"]["value"]
    sentinel.inject("SEA-RAN-001", "hardware", 2)
    sentinel.inject("SEA-RAN-002", "hardware", 2)
    sentinel.inject("SEA-RAN-003", "hardware", 2)
    run_until(sentinel, "SEA-RAN-001")
    after = c.signal("home")["metrics"]["rsrp_dbm"]["value"]
    assert after < before


def test_signal_explanation_offline_and_number_guard(sentinel):
    c = Care(sentinel)
    e = c.explain_signal("home")
    assert e["by"] == "template" and e["confirmed"] and "simulated" in e["unverified"][0]

    class Liar:
        offline, label, outage = False, "double", "none"

        def chat(self, messages, tools=None, agent="", models=None):
            return {"content": json.dumps({"summary": "Your RSRP is -61.3 dBm.", "confirmed": [], "probable": [],
                                           "unverified": [], "steps": []}), "tool_calls": []}, {"model": "muse-spark-1.3"}
    sentinel.provider = Liar()
    e = c.explain_signal("home")
    assert e["by"] == "template (AI unavailable)" and "-61.3" not in e["summary"], "an invented number is rejected"


def test_customer_cannot_call_ops_endpoints(sentinel, monkeypatch):
    monkeypatch.setattr(main, "sentinel", sentinel)
    cl = TestClient(main.app)
    s = main.settings
    assert cl.post("/api/demo/start", json={"portal": "connect"}).status_code == 200
    for path in ("/api/state", "/api/cells/SEA-RAN-001", "/api/alarms", "/api/ledger"):
        assert cl.get(path).status_code == 401, path
    r = cl.get("/api/care/map", params={"place": "home"})
    assert r.status_code == 200 and all(t["distance_km"] <= MAP_RADIUS_KM for t in r.json()["towers"])
    assert cl.get("/api/care/map", params={"place": "../../all"}).status_code == 400
    assert cl.post("/api/care/phone", json={"place": "home", "lat": 40.0, "lon": -100.0}).status_code == 400


def test_concierge_signal_tool_is_customer_safe(sentinel):
    care = Care(sentinel)
    r = care.tool("get_my_signal", {"place": "home"})
    text = json.dumps(r)
    assert r["place"] and r["metrics"] and "simulated" in r["data_source"].lower()
    assert "SEA-RAN" not in text and "tilt" not in text.lower()
    assert care.tool("get_my_signal", {"place": "someone-else"})["place"] == care.tool("get_my_signal", {})["place"]
