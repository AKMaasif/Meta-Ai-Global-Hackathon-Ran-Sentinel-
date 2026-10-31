# py scripts/maveric_setup.py
# py scripts/maveric_setup.py --url http://localhost:8080 --points 60
# py scripts/maveric_setup.py --test-only
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import maveric  # noqa: E402
from app.config import settings  # noqa: E402
from app.simulator import NetworkSimulator  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the Maveric RF twin on the Seattle cluster and test a what-if")
    ap.add_argument("--url", default=settings.maveric_url or os.environ.get("MAVERIC_URL") or "http://localhost:8080")
    ap.add_argument("--model", default=settings.maveric_model)
    ap.add_argument("--points", type=int, default=60, help="samples per cell per tilt")
    ap.add_argument("--wait", type=int, default=3600, help="seconds to wait for training")
    ap.add_argument("--test-only", action="store_true")
    ap.add_argument("--cell", default="SEA-RAN-004")
    a = ap.parse_args()

    client = maveric.RadpClient(a.url, timeout=120)
    if not client.reachable():
        sys.exit(f"Maveric is not answering at {a.url}. Start it with: docker compose -f dc.yml -f dc-prod.yml up -d --build")
    print(f"Maveric at {a.url}")
    cells = NetworkSimulator(seed=7, history=False).cells

    if not a.test_only:
        out = ROOT / "data" / "maveric"
        out.mkdir(parents=True, exist_ok=True)
        topo, train = maveric.topology_csv(cells), maveric.training_csv(cells, a.points)
        (out / "topology.csv").write_text(topo)
        (out / "ue_training_data.csv").write_text(train)
        print(f"{len(cells)} cells, {train.count(chr(10)) - 1} training rows (tilts {maveric.TRAIN_TILTS}) -> data/maveric/")
        print("training job:", client.train(a.model, train, topo, {"maxiter": 100, "lr": 0.05, "stopping_threshold": 1e-4}))
        t0 = time.time()
        while not client.model_trained(a.model):
            if time.time() - t0 > a.wait:
                sys.exit("training still running; check `docker compose logs training` and rerun with --test-only later")
            print(f"  training... {time.time() - t0:.0f} s", end="\r")
            time.sleep(10)
        print(f"\nmodel {a.model} trained in {time.time() - t0:.0f} s")
    elif not client.model_trained(a.model):
        sys.exit(f"model {a.model} is not trained yet")

    c = cells[a.cell]
    for label, change in [("tilt +2", {"tilt_deg": c.config.tilt_deg + 2}),
                          ("power -2 dB", {"tx_power_dbm": c.config.tx_power_dbm - 2}),
                          ("power -8 dB", {"tx_power_dbm": c.config.tx_power_dbm - 8})]:
        t0 = time.time()
        rf = maveric.what_if(client, a.model, cells, a.cell, change, timeout=300)
        print(f"{a.cell} {label:12} coverage loss {rf['coverage_loss_pct']:5.2f}%  holes {rf['new_holes']:3}/{rf['served_before']:<3} "
              f"to neighbours {rf['handed_to_neighbours']:3}  median RSRP {rf['median_rsrp_before']} -> {rf['median_rsrp_after']} dBm  "
              f"({time.time() - t0:.0f} s)")
    print(f"\nPut MAVERIC_URL={a.url} in .env and restart run.py. The what-if then uses Maveric for coverage.")


if __name__ == "__main__":
    main()
