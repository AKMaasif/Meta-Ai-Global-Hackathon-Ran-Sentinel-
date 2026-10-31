# RAN Sentinel: hackathon submission

**Event:** Meta Global AI Developer Hackathon, 2026
**Track:** Indie developer
**Theme:** Build for Your World (Meta's models brought into mobile-network operations, the builder's own field)
**Builder:** AKMaasif (QuanTell), an LTE RAN engineer
**Licence:** MIT (see `LICENSE`)

## One line

RAN Sentinel is an AI co-engineer for a mobile network's operations centre. It spots a degrading cell, has Meta's Muse Spark agents investigate it with read-only tools, and proves the proposed fix is safe with fixed rules and a what-if model. It sends the fix to the right team, applies an approved change over Open M-Plane with automatic rollback, and keeps customers informed in plain language.

## The problem

US regional and rural carriers run the same kind of LTE network as the national carriers, but with a much smaller operations team. Each degraded cell means an engineer opens dashboards, alarms and configuration, works out the cause, and decides who should act. A wrong power or tilt change can harm neighbour cells. Outages also carry federal reporting duties under FCC Part 4 (47 CFR 4.9).

## What it does

1. **Detects.** Threshold rules, an Isolation Forest and a per-cell, per-hour baseline scored with Mahalanobis distance watch 36 simulated cells in Seattle on bands B66, B2 and B71.
2. **Investigates and verifies.** Muse Spark agents call read-only tools for KPIs, alarms, M-Plane configuration and diagnostics, one step at a time with a living plan. They rank four causes, citing evidence, and ask for more checks when unsure. A verifier the agents cannot skip checks every diagnosis: a hidden engineering playbook, every stated number looked up in its evidence, root-cause rules, and a claims check on a second model. When the data cannot settle it, the agent asks a field engineer instead of guessing. An engineer signs off the root cause. This follows Meta's legal-agent workshop patterns.
3. **Proves it is safe.** Nine deterministic rules, a twin what-if and an M-Plane dry run check every plan. A second model reviews the plan, and unsafe plans go back to the planner with the reasons.
4. **Routes it to one team.** The teams are RAN Optimisation, RF Engineering, Field Operations, NOC Data Platform, NOC Shift Lead and Regulatory Compliance. Nothing changes on the network until that team approves.
5. **Acts and checks.** An approved change goes out as a NETCONF confirmed-commit. If the cell does not recover, the radio rolls back by itself.
6. **Keeps records.** Every step goes into the Evidence-to-Action Safety Ledger. The app also tracks the FCC Part 4 outage threshold, writes incident reports and a shift handover, and publishes customer updates that are filtered for internal details.

## Use of Meta AI tooling

| Meta model | Role in RAN Sentinel |
|---|---|
| muse-spark-1.3 | Investigator (tool calls), Root-Cause Analyst, Remediation Planner, Customer Comms, Customer Assistant, Incident Reporter, photo reading |
| muse-spark-1.2 | Plan Reviewer and Claims Checker, an independent second opinion on a different model; fallback for every agent |
| muse-spark-1.1 | Last-resort fallback tier before an incident escalates to a person |
| muse-wonder-1.0 | Escalation Briefer for the hardest cases; Shift Handover that reads every incident and the whole ledger (1M-token context) |
| sam-3.1 | Boxes antennas, cables and connectors in a field technician's site photo |
| muse-voice-transcribe-1.0 | Dictated decision notes for engineers; the customer voice agent's ears (it answers with Gemini TTS, since Meta has no text-to-speech model yet) |

Every model passed `scripts/check_meta.py` on a real Meta Model API key on 2026-10-28. Agent output is schema-checked, with one repair attempt. Every chat call has a retry and a model fallback chain. Muse Image and the contributor variants are deliberately not used; the reasons are on the Model card page.

Meta open-source telecom work is used as well: Open M-Plane (Linux Foundation) shapes the change packages, and Maveric (lf-connectivity) is the twin adapter.

## Technical depth

- Six layers: data checks, detection, orchestrator state machine, agents, safety, ledger and user interfaces.
- Five bounded loops: evidence, output repair, diagnosis verification, plan revision and recovery monitoring. Investigations save a checkpoint after every step and resume after a model outage. Every error path is handled: model outage, invalid output, unsafe plan, twin outage, failed dry run, unconfirmed commit, and prompt injection in data.
- Detector chosen on validation data from the open TelecomTS 5G dataset (MIT, ICML 2026). It reaches F1 0.61 and ROC-AUC 0.92 without labels, against F1 0.23 for a plain Isolation Forest. On the simulator it catches 48 of 48 faults with zero false alarms in 108 normal cell-days.
- 120 automated tests. `scripts/eval_investigation.py` scores the verified investigation against injected faults: offline, 23 of 23 correct and verified, with no wrong diagnosis passing the verifier.

## Run it

Windows: double-click `start.bat`, or follow the steps in `README.md`. The 3-minute demo script is in `DEMO.md`. Open http://127.0.0.1:8000/ops/ (operations console) and http://127.0.0.1:8000/connect/ (customer app). The demo logins are in `.env.example`.

## Originality and third-party components

Built during the hackathon, from 26 October to 4 November 2026. Third-party components are used under their licences:
- **Libraries:** FastAPI, Uvicorn, NumPy and httpx (MIT or BSD); scikit-learn (BSD); the OpenAI Python SDK (Apache-2.0), used as the client for Meta's OpenAI-compatible endpoint; python-dotenv (BSD).
- **Maps:** Leaflet 1.9.4 (BSD-2), topojson-client 3.1.0 (ISC) and us-atlas 3.0.1 state boundaries (ISC; data from the US Census Bureau), bundled. Street tiles © OpenStreetMap contributors and © CARTO, loaded online only.
- **Fonts:** IBM Plex (SIL OFL).
- **Data:** TelecomTS (MIT), used for benchmarking only and not redistributed.

Open M-Plane and Maveric are referenced, not bundled.

## Honest limits

- The network, radio units and customers are simulated, and Northstar Connect is fictional.
- The twin uses a copy of the simulator. The Maveric adapter only checks that the service is running.
- Tower sites are fictional; coverage and the customer's signal readings come from a radio model of the simulated network.
- The FCC check is decision support, not legal advice.
- No Meta or vendor endorsement is implied.
