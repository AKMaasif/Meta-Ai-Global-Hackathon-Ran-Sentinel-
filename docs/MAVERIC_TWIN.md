# Maveric RF twin

Before a plan reaches an engineer, the what-if step predicts what the change does. With `MAVERIC_URL` set, coverage comes from
Meta's open-source [Maveric](https://github.com/lf-connectivity/maveric) RIC Algorithm Development Platform (RADP), a Bayesian RF
digital twin. Load effects (PRB, neighbour load, far users) still come from the simulator copy, because Maveric predicts signal,
not traffic.

Code: `backend/app/maveric.py` (RADP client, training data, what-if), `backend/app/twin.py` (`MavericTwin`),
`scripts/maveric_setup.py`. Tests: `tests/test_maveric.py` (against a fake RADP server).

## Setup (once)

You need Docker. In a separate folder:

```powershell
git clone https://github.com/lf-connectivity/maveric.git
cd maveric
copy .env-prod .env
docker build -t radp radp
docker compose -f dc.yml -f dc-prod.yml up -d --build
```

When the API answers on port 8080, go back to the RAN Sentinel folder:

```powershell
py scripts\maveric_setup.py
```

The script writes `data/maveric/topology.csv` and `ue_training_data.csv`, trains the model `ran-sentinel-seattle`, waits until it
is trained, and runs three test what-ifs. Then add `MAVERIC_URL=http://localhost:8080` to `.env` and restart `py run.py`.
The status bar shows "Twin: Maveric RADP".

## What it sends

| Maveric input | From RAN Sentinel |
|---|---|
| Topology | the 36 cells: site position, azimuth, carrier frequency (B66 2110, B2 1930, B71 617 MHz) |
| Training data | 40 points per cell at each tilt 0, 3, 6, 9, 12 and 15 degrees: modelled outdoor RSRP from `radio.py` |
| Cell config | electrical tilt of the target cell and every cell within 3 km |
| UE data | a grid of points up to 1.2 km around the target site |

Maveric learns RSRP per cell as a function of position and tilt. A tilt change is predicted by Maveric directly. A power change
shifts that cell's predicted RSRP by the same number of dB.

## What comes back

For every grid point the twin finds the best server before and after the change:

- **served before:** points where the target cell was the best server at -110 dBm or better
- **new holes:** of those, points where no cell reaches -110 dBm after the change
- **to neighbours:** points another cell now serves above -110 dBm
- **median RSRP** of the target cell over its served points, before and after

`coverage_loss_pct` is new holes as a share of served points. The safety rule uses the higher of this and the simulator copy's
estimate, so Maveric can never loosen the gate.

## Measured (2026-10-31, Maveric on Docker)

- Training: 8,640 rows for 36 cells, done in 30 s on CPU.
- Accuracy: against the radio model on 2,664 cell-point pairs around SEA-RAN-004, mean error -0.04 dB, mean absolute error
  1.26 dB, 90th percentile 2.25 dB.
- A what-if takes 2 to 14 s (two simulations when the tilt changes, one for power).
- SEA-RAN-004: tilt +2 hands 12 of 67 served points to neighbours, power -2 dB hands 14, power -8 dB hands 44. No new holes in any
  case, because the dense Seattle grid always has another cell. The same pattern held on SEA-RAN-001, -010 and -020.
- In the incident pipeline, an overshoot on SEA-RAN-004 went through the what-if as
  "Maveric RF twin (coverage) + simulator copy (load): coverage loss 0.0%".

## Fallback

The simulator copy takes over, and the engine label says why, when Maveric is not reachable, the model is not trained yet, or a
call fails or times out (`MAVERIC_TIMEOUT_SECONDS`, default 90). The "Twin outage" demo switch still makes the twin unavailable.

## Limits

- The training data is modelled, not a drive test. Maveric reproduces the radio model closely; it does not add real-world
  propagation. With real drive-test or MDT data the same script would train on measurements instead.
- Maveric predicts tilt effects. Power is applied as a dB offset on its prediction.
