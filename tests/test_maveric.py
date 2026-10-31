import csv
import io
import json
import zipfile

import httpx
import pytest

from app import maveric, radio
from app.simulator import NetworkSimulator
from app.twin import FallbackTwin, MavericTwin


class FakeRadp:
    def __init__(self, cells, trained=True, fail_sim=False):
        self.cells, self.trained, self.fail_sim = cells, trained, fail_sim
        self.sims, self.trains = {}, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET" and path.startswith("/model/"):
            if path.endswith("/ping") or not self.trained:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json={"status": "trained"})
        if req.method == "POST" and path == "/train":
            parts = self._parts(req)
            self.trains.append(parts)
            return httpx.Response(200, json={"job_id": "j1", "model_id": json.loads(parts["payload"])["model_id"]})
        if req.method == "POST" and path == "/simulation":
            if self.fail_sim:
                return httpx.Response(500, json={"error": "boom"})
            parts = self._parts(req)
            sid = f"s{len(self.sims)}"
            self.sims[sid] = self._predict(parts)
            return httpx.Response(200, json={"simulation_id": sid})
        if req.method == "GET" and path.endswith("/download"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("out.csv", self.sims[path.split("/")[2]])
            return httpx.Response(200, content=buf.getvalue())
        if req.method == "GET" and path.startswith("/simulation/"):
            return httpx.Response(200, json={"simulation_status": "finished"})
        return httpx.Response(404)

    @staticmethod
    def _parts(req):
        body = req.read().decode()
        boundary = req.headers["content-type"].split("boundary=")[1]
        out = {}
        for chunk in body.split("--" + boundary)[1:-1]:
            head, _, data = chunk.partition("\r\n\r\n")
            name = head.split('name="')[1].split('"')[0]
            out[name] = data[:-2]
        return out

    def _predict(self, parts):
        ue = list(csv.DictReader(io.StringIO(parts["ue_data.csv"])))
        cfg = list(csv.DictReader(io.StringIO(parts["config.csv"])))
        rows = []
        for c in cfg:
            cell = maveric._planned(self.cells[c["cell_id"]], float(c["cell_el_deg"]))
            for p in ue:
                lat, lon = float(p["lat"]), float(p["lon"])
                y = (lat - radio.ANCHOR[0]) * radio.KM_PER_DEG_LAT
                x = (lon - radio.ANCHOR[1]) * 111.320 * radio.math.cos(radio.math.radians(radio.ANCHOR[0]))
                r, _ = radio._rsrp(cell, None, x, y, indoor=False)
                rows.append({"cell_id": c["cell_id"], "rxpower_dbm": r, "lon": lon, "lat": lat})
        return maveric._csv(rows, ["cell_id", "rxpower_dbm", "lon", "lat"])


@pytest.fixture()
def sim():
    return NetworkSimulator(seed=7, history=True)


def twin_with(sim, fake):
    client = maveric.RadpClient("http://radp", http=httpx.Client(transport=httpx.MockTransport(fake)))
    return MavericTwin("http://radp", FallbackTwin(sim), "m1", 5, client)


def test_training_files_match_maveric_columns(sim):
    topo = list(csv.DictReader(io.StringIO(maveric.topology_csv(sim.cells))))
    train = list(csv.DictReader(io.StringIO(maveric.training_csv(sim.cells, 5))))
    assert set(topo[0]) == {"cell_id", "cell_name", "cell_lat", "cell_lon", "cell_az_deg", "cell_carrier_freq_mhz"}
    assert set(train[0]) == {"cell_id", "avg_rsrp", "lon", "lat", "cell_el_deg"}
    assert len(topo) == len(sim.cells) and len(train) == len(sim.cells) * 5 * len(maveric.TRAIN_TILTS)
    assert {float(r["cell_el_deg"]) for r in train} == set(maveric.TRAIN_TILTS)


def test_train_posts_three_files(sim):
    fake = FakeRadp(sim.cells)
    client = maveric.RadpClient("http://radp", http=httpx.Client(transport=httpx.MockTransport(fake)))
    client.train("m1", "a,b\n", "c,d\n")
    assert set(fake.trains[0]) == {"payload", "ue_training_data.csv", "topology.csv"}


def test_whatif_uses_maveric_for_coverage(sim):
    t = twin_with(sim, FakeRadp(sim.cells))
    cid = "SEA-RAN-004"
    small = t.simulate(cid, {"tx_power_dbm": sim.cells[cid].config.tx_power_dbm - 2})
    big = t.simulate(cid, {"tx_power_dbm": sim.cells[cid].config.tx_power_dbm - 12})
    tilt = t.simulate(cid, {"tilt_deg": sim.cells[cid].config.tilt_deg + 2})
    assert small["engine"].startswith("Maveric RF twin")
    assert small["rf"]["served_before"] > 0 and small["rf"]["median_rsrp_after"] < small["rf"]["median_rsrp_before"]
    assert big["coverage_loss_pct"] >= small["coverage_loss_pct"]
    assert big["rf"]["handed_to_neighbours"] + big["rf"]["new_holes"] > small["rf"]["handed_to_neighbours"] + small["rf"]["new_holes"]
    assert tilt["rf"]["tilt"][1] == sim.cells[cid].config.tilt_deg + 2
    assert "prb_util" in small["after"]


def test_falls_back_with_a_reason(sim):
    cid = "SEA-RAN-004"
    p = sim.cells[cid].config.tx_power_dbm - 2
    assert "model not trained" in twin_with(sim, FakeRadp(sim.cells, trained=False)).simulate(cid, {"tx_power_dbm": p})["engine"]
    failed = twin_with(sim, FakeRadp(sim.cells, fail_sim=True)).simulate(cid, {"tx_power_dbm": p})
    assert "Maveric failed" in failed["engine"] and "rf" not in failed

    def down(req):
        raise httpx.ConnectError("refused")
    assert "not reachable" in twin_with(sim, down).simulate(cid, {"tx_power_dbm": p})["engine"]
