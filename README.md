# RAN Sentinel

An AI co-engineer for mobile networks, built for the Meta Global AI Developer Hackathon.

RAN Sentinel watches a cluster of LTE cells in Seattle, WA (US bands B66, B2 and B71) and spots a degrading cell. Muse Spark agents investigate it with read-only tools and propose a fix. Fixed safety rules and a digital twin check that fix before anyone sees it. The recommendation then goes to the right department. When a configuration change is approved, it is sent as an Open M-Plane change package with automatic rollback, and the cell is watched until it recovers. Customers of the fictional operator **Northstar Connect** see only confirmed, plain-language updates.

Everything runs on a **simulated** network. Nothing here connects to a real operator.

**New since 2026-10-30:** a verified investigation built on the patterns in Meta's
[legal-agent workshop](https://github.com/meta-models/legal-agent-workshop). Every diagnosis passes a verifier the agents cannot skip.
The agent pauses to ask a field engineer when the data cannot settle a cause. It keeps a living plan, works one tool per turn and
resumes from its last step after an API failure, and an engineer signs off the root cause
([details](docs/VERIFIED_INVESTIGATION.md)). Customers also get a hands-free **voice agent** that operates the app
([details](docs/VOICE_AGENT.md)).

**Hackathon entry:** Indie track, theme "Build for Your World". The submission summary is in [SUBMISSION.md](SUBMISSION.md), the 3-minute demo script is in [DEMO.md](DEMO.md), and the code is MIT-licensed ([LICENSE](LICENSE)).

| Judging criterion | Where RAN Sentinel answers it |
|---|---|
| Impact (30%) | Cuts the time from a degrading cell to a safe, approved fix for small carrier ops teams; tracks FCC Part 4 duty; keeps customers informed |
| Use of Meta AI tooling (25%) | Six Meta models, each with one job: Muse Spark 1.3/1.2/1.1, Muse Wonder 1.0, SAM 3.1 and Muse Voice Transcribe 1.0, plus Open M-Plane and Maveric; the investigation follows Meta's legal-agent workshop patterns |
| Demo (25%) | Live fault injection from the console; red-team, twin outage, diagnostics outage and model outage switches show every safety path; a customer voice agent |
| Technical depth (20%) | Six layers, five bounded loops, a diagnosis verifier, nine safety rules, checkpoints and resume, NETCONF confirmed-commit with rollback, detector benchmarked on TelecomTS, 120 automated tests |

What's built for the US market:
- **FCC Part 4 outage check** (47 CFR 4.9(e)). It tracks user-minutes for every outage and, when a wireless outage passes 30 minutes and 900,000 user-minutes, opens a Regulatory Compliance ticket with the 120-minute, 72-hour and 30-day deadlines. Set `FCC_USERS_PER_SITE` in `.env`. This is decision support, not legal advice.
- **Real neighborhoods and ZIP codes.** Customers can check a ZIP code, and the assistant understands one too ("Is there an issue in 98101?").
- **Times in Pacific time.**

## Documentation

| Document | What it covers |
|---|---|
| [System architecture](docs/SYSTEM_ARCHITECTURE.md) | roles, components, runtime model, incident lifecycle, agent loop, data flow, tech stack |
| [AI agents and models](docs/AI_AGENTS_AND_MODELS.md) | every agent, its model and fallback, tools, limits, what is deterministic |
| [Live-update architecture](docs/LIVE_UPDATE_ARCHITECTURE.md) | polling, in-place page patching, request handling, the refresh fix |
| [API and database](docs/API_AND_DATABASE.md) | every route, request and response, the SQLite schema |
| [Setup and deployment](docs/SETUP_AND_DEPLOYMENT.md) | install, `.env` settings, health checks, troubleshooting, verification checklist |
| [Verified investigation](docs/VERIFIED_INVESTIGATION.md) | the verifier, field-evidence pause, living plan, checkpoints and resume, sign-off, and how each maps to Meta's legal-agent workshop |
| [Customer voice agent](docs/VOICE_AGENT.md) | the voice pipeline (Muse Voice Transcribe, Muse Spark, Gemini TTS), its tools, safety and speed |
| [Security and access control](docs/SECURITY_AND_ACCESS_CONTROL.md) | sign-in, roles, customer data limits, secrets, known gaps |
| [Implementation and test report](docs/IMPLEMENTATION_AND_TEST_REPORT.md) | the live-refresh fix with before/after numbers, test results, change history |

## Run it (Windows)

```powershell
git clone https://github.com/AKMaasif/ran-sentinel.git
cd ran-sentinel
```

You need Python 3.10 or newer. The quickest way is to double-click **`start.bat`**. On the first run it creates the virtual environment, installs the requirements and copies `.env.example` to `.env`; then it starts the server and opens the console in your browser. Put your key in `.env` before the next start.

Or step by step:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env          # paste your Meta key after MODEL_API_KEY= (and, for the voice agent, a Gemini key after GOOGLE_API_KEY=)
py scripts\check_meta.py   # checks every Meta model the app uses (chat, tools, JSON, vision, SAM, voice)
py scripts\audit_agents.py # runs every AI agent live through the app code and prints PASS / FALLBACK / FAIL
py run.py
```

Then open:

- Operations console: http://127.0.0.1:8000/ops/ (sign in with `OPS_EMAIL` / `OPS_PASSWORD` from `.env`)
- Northstar Connect customer app: http://127.0.0.1:8000/connect/ (`CUSTOMER_EMAIL` / `CUSTOMER_PASSWORD`)

**Where the API key goes:** `.env` in the project folder, on the line `MODEL_API_KEY=...`. That file is listed in `.gitignore`, so it is never committed. Don't put the key in any `.py` or `.js` file.

Without a key the app still runs, but the agents use an **offline rules engine**. The console then shows "Offline rules engine" everywhere, so those results can't be mistaken for Meta-powered ones.

## The operations console

The console follows the layout of a network operations (OSS) tool: a top bar with global search and live alarm counters by severity, a module rail, one work area and a status bar.

| Module | What it shows |
|---|---|
| **Monitor · Network overview** | KPI tiles with trends, the cluster map, the incident work queue, network health, AI activity and a live model-call feed |
| **Monitor · Alarm monitor** | Every alarm with X.733-style fields (severity, event type, probable cause, managed object, linked incident); filter and acknowledge |
| **Monitor · Cell explorer** | Network tree by site and band; for each cell, KPI charts against limits, alarms, M-Plane radio config and detector scores |
| **Operate · Incidents** | Tabbed incident workspace: fact bar, workflow timeline, diagnosis with its verification, plans and safety checks, evidence, field photos, an agent console with every model call, report and ledger. Beside it: the live investigation plan, any field-evidence request and the decision panel |
| **Operate · Approvals** | One card per team with its queue, and the decisions waiting on each |
| **Assure · Safety ledger** | The Evidence-to-Action Safety Ledger and the Muse Wonder shift handover |
| **Assure · Model card** | Models, fallbacks and the measured accuracy |

The status bar shows the telemetry window, AI calls and average latency, the twin and the M-Plane link. Search by incident ID, cell ID, site name or ZIP code.

## The customer app (Northstar Connect)

A carrier self-service app with the usual pages: **Home**, **Network**, **Account** (lines, plan, settings, places), **Bill** (balance, items, history), **Help**, **Notifications** and **Shop**. On top of that, an AI care layer works for the customer:

- **Proactive alerts** for the places they care about (Home, Work, Gym). The customer hears about a problem before they notice it, then gets progress updates and a "back to normal" message.
- **Network transparency:** a plain-language cause, what they may notice, a six-step repair tracker, and a **recovery-time estimate** with a confidence level.
- **Personal suggestions** that fit the problem and their settings (Wi-Fi Calling, Data Saver, texting instead of calling, device checks when the network is fine).
- **Outage credits** offered automatically by a fixed rule (30+ minutes down at one of their places earns a $5 credit).
- **Problem reports that reach engineers:** if a report matches an open repair, it is added to that incident as evidence for the NOC; if not, the app walks the customer through device checks.
- **Care Concierge** on Muse Spark 1.3 with tool calls. Its tools see only this customer's account and published network updates. It can only *propose* a change; the customer taps Confirm.

| Layer | Runs on | Job |
|---|---|---|
| 1 Listen | Muse Voice Transcribe 1.0 | Spoken questions to text |
| 2 Care Concierge | Muse Spark 1.3 (1.2, 1.1 backup) | Plans the answer and calls customer-scoped tools |
| 3 Network Explainer | Muse Spark 1.3 | Customer updates written from engineer-approved facts |
| 4 Recovery Estimator | Fixed rules | Estimate from repair stage and typical repair times |
| 5 Personal Advisor | Fixed rules | Suggestions for the customer's situation |
| 6 Guardrails | Fixed rules | Blocks internal details, applies the credit rule, needs the customer's confirmation |

**Voice agent.** The "Ask" orb opens a hands-free assistant. The customer speaks; Muse Voice Transcribe turns it into text, the
Care Concierge on Muse Spark answers and operates the app (connection tests, opening pages, reports), and Gemini TTS speaks the
answer sentence by sentence. Changes still need a spoken "yes" in a later turn or a tap on Confirm. See [docs/VOICE_AGENT.md](docs/VOICE_AGENT.md).

The subscriber, account and bill are fictional demo data, and no payment is taken. The code is in `backend/app/care.py` and `frontend/connect/`.

## Maps and signal quality

Both apps use an interactive map of the United States: **Leaflet 1.9.4** with **US state boundaries** from the US Census Bureau (us-atlas 3.0.1, 1:10m). Both are bundled in `frontend/shared/vendor/`, so the outline works offline. When the PC is online, a light street basemap (© OpenStreetMap contributors, © CARTO) loads underneath. If the tiles can't load, the map says so and keeps the state outlines.

- **Operations console, Cluster map:** opens on the whole US, then flies to Seattle. Zoomed out, the cluster is one marker with its cell and incident counts. Zoomed in, you see the 12 sites and 36 sector wedges, coloured by state, with modelled coverage circles. Click a site for its cells, band, azimuth, PRB load, SINR, power and tilt; click a sector to select that cell. Layers can be switched on and off. Zoom and position survive the auto-refresh, which patches the page in place instead of rebuilding it ([details](docs/LIVE_UPDATE_ARCHITECTURE.md)).
- **Customer app, Network page:** only towers within 3 km of the customer's saved place. The server filters them (`GET /api/care/map`) and never sends cell IDs, power or tilt. Each tower is connected, available, problem or unavailable; problem and unavailable appear only once engineers publish an update. The customer can drag the test phone up to 1.5 km and see the signal change.
- **Signal card:** RSRP, RSRQ, SINR, latency and packet loss with a 12-window history, the serving tower, technology and band, tower changes and stability. Each metric has its own scale (for example RSRP: Excellent at -80 dBm or better, Good to -90, Fair to -100, Poor to -124, below that Disconnected). The overall rating is the worst measured metric, and the card names which metric sets it. A missing value shows as Unknown, never as a guess.
- **Signal intelligence:** Muse Spark explains the reading in three lists: *confirmed* (what the numbers show), *probable* (causes the facts support) and *not verified*. The answer is rejected if it uses a number that isn't in the measurements or mentions internal details. Without a key, a fixed template gives the same structure.

**Where the numbers come from:** the sites are fictional but placed on the simulator's km grid, which is anchored at Downtown Seattle, so each one sits near the neighbourhood it is named after. Coverage and the phone's readings come from a radio model of the simulated network (`backend/app/radio.py`): 3GPP TR 36.942 urban path loss, a 3GPP-style sector antenna pattern, each cell's running power and tilt, and its live simulated KPIs. The serving tower is the strongest modelled signal, not the nearest tower. Every screen labels this as a simulated test phone, not the customer's real phone. The browser's own connection info (`navigator.connection`) is shown separately and marked as not cellular.

## Demo: create a problem live

Open **Demo controls** from the module rail (it opens as a drawer beside any page):

1. Pick a cell (or click a sector on the map) and a problem:
   - **Capacity surge:** an event crowd arrives. Fix: lower transmit power so users move to a neighbour. Goes to RAN Optimisation.
   - **Overshoot:** a bad config push set the tilt too low. Fix: restore the tilt. Goes to RAN Optimisation.
   - **External interference:** no config fix exists. Goes to RF Engineering to find the source.
   - **Hardware fault (VSWR):** goes to Field Operations for a site visit, and customers are told a repair is underway.
   - **KPI data dropout:** the agent re-polls the collector by itself. Severity 1 fixes itself; otherwise it goes to the NOC Data Platform team.
2. Click **Create problem**. Within about two telemetry windows the detector opens an incident and the agents start on their own.
3. Open the incident and approve, reject, or ask for more information. For field tickets, click **Mark fixed** after "dispatch".
4. Optional switches:
   - **Red-team the first plan:** forces an aggressive first draft so you can show the safety rules blocking it.
   - **Twin outage:** shows the "not simulated" error path.
   - **Diagnostics outage:** the diagnostic checks time out, so the agent cannot settle the cause from data. It pauses and asks a field engineer; type what was found (for example "spectrum analyser shows a booster east of the site") and it resumes.
   - **Meta API: primary model down / all models down:** shows the model fallback and the escalation path. With a key, an interrupted investigation resumes from its saved step once the API is back.

## How it works

| Layer | What it does | AI? |
|---|---|---|
| 1 Data | Range and missing-data checks; bad windows are quarantined | No |
| 2 Detection | Threshold baseline + Isolation Forest, 2-window confirmation, related-alert grouping | No (ML) |
| 3 Orchestrator | State machine, budgets (8 tool calls, 2 evidence rounds, 3 verifier refusals, 2 plan retries, 1 reopen), checkpoints and resume, field-evidence pause, escalation | No |
| 4 Agents | Investigator (tool calls), Root-Cause Analyst, Remediation Planner, Plan Reviewer (second opinion on a different model), Customer Comms, Customer Assistant, Incident Reporter, Escalation Briefer, Shift Handover, Field Photo Analyst, voice notes | Muse Spark 1.3 / 1.2 / 1.1, Muse Wonder 1.0, SAM 3.1, Muse Voice Transcribe 1.0 (table below) |
| 5 Safety | Diagnosis verifier (hidden playbook, fact lookup, root-cause rules; claims check on a second model) + 9 deterministic plan rules + twin what-if + department approval + M-Plane dry run + confirmed-commit | Mostly no |
| 6 Surfaces | Evidence-to-Action Safety Ledger, ops console, customer app | No |

The five loops, each with a limit:

1. **Evidence:** the analyst asks for more read-only checks (up to 2 rounds). If the cause is still unclear, the agent asks a field engineer once.
2. **Output repair:** agent JSON is schema- and citation-checked, with 1 repair try.
3. **Verification:** a refused diagnosis gets the missing evidence and the verifier's reasons (up to 3 refusals, then a person).
4. **Plan revision:** validator reasons go back to the planner (up to 2 retries).
5. **Recovery:** after a change, the cell is watched. If it recovers, the commit is confirmed. If not, the change is rolled back and the investigation reopens once.

Error paths: bad data, duplicate or related alerts, Meta API errors and timeouts, tool errors, invalid model output, budget exhaustion, unsafe plans, twin unavailable, failed M-Plane dry run, unconfirmed commits (the radio reverts by itself), customer text leaking internal details, and prompt injection in data. The full diagram is in `docs/workflow.mmd`.

## Which Meta model does what

Each model has one job where it helps. None is there just to be listed.

| Model | Used for | Why this model | If it is unavailable |
|---|---|---|---|
| muse-spark-1.3 | Investigator, Analyst, Planner, Customer Comms, Customer Assistant, Incident Reporter, photo reading | Tool calls and JSON output passed on your key | falls back to 1.2, then 1.1 |
| muse-spark-1.2 | Plan Reviewer; Claims Checker in the verifier; fallback for everything | A different model gives a more independent second opinion | falls back to 1.3, then 1.1 |
| muse-spark-1.1 | Last-resort tier | One more chance before an incident escalates to a person | escalate to the NOC Shift Lead |
| muse-wonder-1.0 | Escalation Briefer; Shift Handover | The hardest cases get the strongest model. The handover reads every incident and the whole ledger, which needs the 1M-token context | Muse Spark 1.3, then a template |
| sam-3.1 | Field Photo Analyst: boxes antennas, cables and connectors in a technician's site photo | Segmentation is SAM's job; Spark then reads the photo with those boxes | photo stored without analysis |
| muse-voice-transcribe-1.0 | Dictated decision notes (ops); spoken questions (customers) | Engineers on a mast or in a van have their hands full. Cell IDs and site names are sent as keyword hints | type instead |

The voice and photo features are advisory only. A dictated note can highlight a decision button, but it never clicks it. A photo adds evidence and can raise a "does not match the diagnosis" warning, but it never changes an incident.

**On the key but not used:**
- **muse-image-1.0:** a generated picture is not evidence and could be mistaken for a real site photo.
- **The -contributor variants:** they cost less, but Meta may train on what is sent, and incidents and customer questions can hold sensitive data. You can opt in for the customer assistant only, with `ASSISTANT_MODEL=muse-spark-1.3-contributor`.

`py scripts\check_meta.py` tests each of these models through the same code the app uses. The checks cover chat, tool calls, JSON, vision with an image, SAM with a generated test image, and transcription with a generated WAV. Add `--image site.jpg --audio note.wav` to try your own photo and recording.

## Models and measured accuracy

The live detector has three parts, and any one of them can raise an alert. An alert fires after 2 consecutive 15-minute windows.
- **Threshold rules:** seven limits an engineer would set.
- **Isolation Forest:** learns normal traffic.
- **Cell baseline:** compares each KPI with what is normal for that cell at that hour, scored with Mahalanobis distance.

None of them needs labelled faults. The **Model card** page in the console shows all results.

**Open dataset: [TelecomTS](https://github.com/Ali-maatouk/TelecomTS)** (MIT licence, ICML 2026): 32,000 labelled 5G windows covering 11 anomaly types. The split was 80/20 train/test. The unsupervised detector was chosen on a validation split taken from training data, never on test. Thresholds were set for a 1% false-alarm rate.

| Detector (TelecomTS test set) | Labels needed | F1 | Recall | ROC-AUC | False alarms |
|---|---|---|---|---|---|
| Isolation Forest | No | 0.23 | 0.16 | 0.76 | 0.9% |
| PCA reconstruction, context baseline | No | 0.52 | 0.47 | 0.91 | 1.3% |
| **Mahalanobis, context baseline (selected)** | No | **0.61** | **0.59** | **0.92** | 1.4% |
| Gradient-boosted trees (reference) | Yes | 0.97 | 0.94 | 1.00 | 0.0% |

Root-cause classification with labels scored 99.0% accuracy across the 10 synthetic types, and 98.9% after mapping to RAN Sentinel's causes. Labels make a large difference, so the roadmap turns incidents that engineers confirm in the ledger into training labels. The supervised scores are likely optimistic, because TelecomTS anomalies were recorded in separate sessions from normal traffic. Jamming is the hardest type to detect without labels: only 15% was caught.

To reproduce:

```powershell
pip install huggingface_hub
py scripts\benchmark_telecomts.py --export-features data\telecomts_features.csv.gz   # downloads 1.1 GB once
py scripts\benchmark_telecomts.py --features data\telecomts_features.csv.gz          # fast re-runs
```

| Simulator benchmark (48 injected faults) | Detected | False alarms in 108 normal cell-days |
|---|---|---|
| Threshold rules only | 79.2% | 0 |
| Isolation Forest only | 56.2% | 0 |
| Cell baseline only | 64.6% | 0 |
| **All three (shipped)** | **100%** | **0** |

After the full investigation, the correct root cause ranked first in 97.9% of simulator runs. Re-run this benchmark with `py scripts\benchmark_simulator.py`.

`py scripts\eval_investigation.py` scores the whole verified investigation against the injected faults (add `--live` for the Muse Spark agents). Offline: 11 of 11 incidents correct and verified at severity 2, 12 of 12 at severity 1, and no wrong diagnosis passed the verifier.

## Honest limits

- **Simulated network:** 36 cells in Seattle with a small, explainable KPI model. Northstar Connect is fictional.
- **TelecomTS vs live data:** TelecomTS validates the detection method on real 5G testbed telemetry: per-UE KPIs every 100 ms. The live demo runs on simulated cell-level KPIs every 15 minutes, because no open dataset offers a cell cluster with config control.
- **Twin:** the what-if uses a copy of the simulator ("fallback twin"). The Maveric (lf-connectivity/maveric) adapter does a health check only; full RF-prediction calls are still to be wired.
- **Open M-Plane:** XML uses simplified, O-RAN-style element names and goes to an in-process simulated radio unit, not real hardware or the open-mplane C stack.
- **Meta models:** every model passed `check_meta.py` on a real key (2026-10-28). Voice was checked with a test tone only, so transcription of real speech is not yet measured; try `--audio` with a recorded note.
- **Maps:** the street basemap needs internet; state outlines are offline. Towers and coverage are modelled, not surveyed.
- **Agent audit:** `scripts/audit_agents.py` runs every agent live; its logic is tested with a scripted stand-in, and the live result depends on your key.
- **Support labels:** hypothesis support levels describe evidence strength, not calibrated probabilities.
- **Verified investigation:** measured offline only so far; run `eval_investigation.py --live` for the Muse Spark agents. Resume covers model API failures; restarting the server resets the demo.
- **Voice agent:** spoken replies use Gemini TTS (Google), because Meta has no text-to-speech model yet; without a Google key the browser voice is used. Real-speech accuracy and latency are not yet measured.
- **Reasoning effort:** `AGENT_EFFORT` is optional; `scripts/check_effort.py` shows whether the Meta API accepts it.

## Tests

```powershell
python -m pytest -q
```

120 tests cover the safety rules, M-Plane rollback, detection (no false alerts on a normal day; every fault detected), all five fault scenarios end to end, and the Muse Spark code path. The Muse Spark tests use a scripted stand-in for the API, covering tool calls, the repair loop, the evidence loop, the customer-text filter, model fallback and full outage. Further tests cover:
- the FCC check, the ZIP-aware assistant, the reviewer and reporter agents, and the TelecomTS pipeline;
- the SAM and voice request formats, against a mock HTTP server;
- photo evidence and the voice-intent hints;
- the Wonder briefs and handover, and the three-tier fallback;
- the alarm monitor fields and acknowledge;
- sign-in on each portal, with a pointer to the right one;
- the customer care layer: alerts, recovery estimate, reports to the NOC, credit rule, and the Care Concierge;
- maps and signal: site geography, per-metric quality bands, the customer map radius and hidden fields, serving tower from the radio model, the Signal Analyst number guard, and ops endpoints refusing a customer login;
- the live agent audit script, run against a scripted stand-in;
- the verifier (playbook coverage, fact lookup, made-up numbers and unsupported claims refused, escalation after 3 refusals), the field-evidence pause and resume, root-cause sign-off and dispute;
- the living plan, one tool per turn, and resuming after an API failure at the investigate and plan steps, by button and automatically;
- the voice agent (later-turn confirmation, instant commands, Gemini request format) and per-agent reasoning effort.

The live refresh is checked in a real browser by `node scripts\check_live_refresh.js` (12 checks: no screen rebuilds, clicks and taps that span a refresh, typed text, scroll and map kept, one request at a time on a slow backend, and the lost-connection state). It needs Node.js and Playwright and the app running; see [Setup](docs/SETUP_AND_DEPLOYMENT.md#7-tests).
