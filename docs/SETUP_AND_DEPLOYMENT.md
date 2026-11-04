# Setup and deployment

RAN Sentinel runs as one local Python process. Fresh installation and startup checks passed on Windows, Ubuntu/WSL, GitHub-hosted Ubuntu, and GitHub-hosted Apple Silicon macOS with Python 3.14. Those hosted runs each passed 207 application tests on the earlier revision. The no-login/local-speech revision passed 206 application tests and the local Windows and Ubuntu/WSL smoke checks; previous hosted results do not certify these changes. See the [installation verification record](LOCAL_INSTALL_VERIFICATION.md) for environments, results and limits. There is **no deployment configuration** in the repository: no Dockerfile, no cloud manifests, no reverse-proxy or TLS setup. Running it anywhere other than `127.0.0.1` has not been tested; see [Security](SECURITY_AND_ACCESS_CONTROL.md) before trying.

## 1. Prerequisites

| Need | For | Notes |
| --- | --- | --- |
| Python 3.10 or newer (`py` launcher on Windows) | the app, tests, scripts | `start.bat` uses `py`, or `python` when the launcher is missing |
| A Meta Model API key | Meta-powered agents | optional: without it the app uses the offline rules engine and says so on screen |
| Internet access | initial package installation; optional Meta calls and street-map tiles | after installation, the no-key demo works offline with bundled map outlines |
| Installed English system voice | local spoken replies | optional; choose Text only if unavailable |
| Node.js + Playwright | browser regression scripts | optional; not needed to run the app |
| `huggingface_hub` | `scripts/benchmark_telecomts.py` only | optional, downloads 1.1 GB once |

Python packages (`requirements.txt`): fastapi, uvicorn[standard], numpy, scikit-learn, openai, httpx, python-dotenv, pypdf, pytest.

## 2. Directory layout

```
ran-sentinel/
  run.py                 starts uvicorn on 127.0.0.1:8000 (app.main:app)
  start.bat              one-click start for Windows
  requirements.txt
  .env.example           every setting, without values; copy to .env
  backend/app/
    main.py              FastAPI routes, sessions, the simulator tick thread
    config.py            Settings: reads .env (python-dotenv), defaults
    orchestrator.py      Sentinel: incident state machine, decisions, monitoring
    agents.py            Muse Spark / Wonder agents and their fallbacks
    providers.py         Meta Model API client: chat, SAM (/responses), voice (/asr/transcribe), retries
    tools.py             read-only Investigator tools
    detection.py         threshold + Isolation Forest + cell baseline detector
    safety.py            the 9 plan rules
    twin.py              Maveric twin + fallback twin
    maveric.py           Maveric RADP client, training data, what-if
    mplane.py            simulated Open M-Plane radio unit (confirmed-commit, rollback)
    regulatory.py        FCC Part 4 user-minute check
    simulator.py         36-cell Seattle LTE cluster
    radio.py             path loss / antenna model for coverage and the test phone
    care.py              Northstar Connect customer care layer
    store.py             SQLite store (incidents, ledger, tickets, customer_updates)
  frontend/
    shared/              ui.js (api, morph, poller), local-speech.js, geomap.js, base.css, vendor/
    ops/                 operations console (index.html, app.js, ops.css)
    connect/             customer app
  scripts/               check_meta.py, audit_agents.py, check_field_files.py, benchmark_*.py, check_live_refresh.js
  tests/                 pytest suite
  data/                  sentinel.db (created at start), benchmarks/*.json
  docs/                  this documentation, workflow.mmd
```

## 3. Install and run

### Windows

Follow the [three-section README installation guide](../README.md#run-it-windows): **1. Local demo**, **2. Live AI and voice**, and **3. Docker RF twin**. Start with Section 1; the other two are optional. The guide includes manual Windows, macOS and Linux commands, no-login demo buttons and a success check.

On Windows, double-click `start.bat` or run `.\start.bat` in PowerShell. The launcher creates `.venv` when absent, checks requirements on every run (including after an interrupted install), and creates `.env` only if missing. It then starts the server and prints both portal URLs. Open those URLs yourself and keep the terminal running. API keys are optional for the offline simulator.

Manual PowerShell commands after cloning and entering the repository:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe run.py
```

No activation command is needed. If `py` is unavailable, use `python -m venv .venv` first.

| Portal | URL | Entry |
|---|---|---|
| Engineer | http://127.0.0.1:8000/ops/ | Explore engineer demo |
| Customer | http://127.0.0.1:8000/connect/ | Explore customer demo |

No credentials or outside account are needed. Sample data is fictional and the network is simulated. Both roles are intentionally open for local evaluation; customer session tokens cannot call engineer APIs. For an occupied port, stop the old server or use `.\.venv\Scripts\python.exe run.py --port 8001` and open the printed URLs. Use one server per checkout because startup resets simulator state.

### macOS / Linux

From the cloned project folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
.venv/bin/python run.py
```

On Ubuntu/Debian, install `python3-venv` first if Python reports that `ensurepip` is unavailable. Open the same portal URLs and choose the Explore demo buttons. For any Python command below, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`. Docker and Node.js are optional.

## 4. Configuration (`.env`)

`.env` sits in the project root and is read by `backend/app/config.py` (`load_dotenv(ROOT / ".env")`). It is in `.gitignore`. Only the variable names are listed here. Defaults are the values `config.py` uses when a variable is missing.

| Variable | Purpose | Default in `config.py` |
| --- | --- | --- |
| `MODEL_API_KEY` | Meta Model API key; empty = offline rules engine | empty |
| `META_BASE_URL` | OpenAI-compatible endpoint | `https://api.meta.ai/v1` |
| `PRIMARY_MODEL`, `FALLBACK_MODEL`, `LAST_RESORT_MODEL` | three-tier chat chain | `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1` |
| `REVIEWER_MODEL` | Plan Reviewer (second opinion) | `muse-spark-1.2` |
| `WONDER_MODEL` | escalation brief, shift handover | `muse-wonder-1.0` |
| `VISION_MODEL`, `SAM_MODEL` | field photos | `muse-spark-1.3`, `sam-3.1` |
| `VOICE_MODEL` | voice notes and spoken questions | `muse-voice-transcribe-1.0` |
| `ASSISTANT_MODEL` | customer assistant and Concierge | `muse-spark-1.3` |
| `MODEL_MAX_TOKENS`, `MODEL_TIMEOUT_SECONDS` | per-call limits | 4000, 60 |
| `REASONING_EFFORT`, `AGENT_EFFORT` | optional reasoning effort, for every agent or per agent (`analyst=high,voice_agent=minimal`) | empty = model default |
| `ONE_TOOL_PER_TURN` | investigator runs one tool per model turn (`0` to allow parallel calls) | `1` |
| `FIREWORKS_API_KEY` | optional last fallback on Muse Spark Open (Fireworks, billed per token) | empty = never called |
| `MAVERIC_URL` | optional Maveric RADP service, e.g. http://localhost:8080 ([setup](MAVERIC_TWIN.md)) | empty = fallback twin |
| `MAVERIC_MODEL` | model trained by `scripts/maveric_setup.py` | `ran-sentinel-seattle` |
| `MAVERIC_TIMEOUT_SECONDS` | wait per Maveric simulation before falling back | `90` |
| `FCC_USERS_PER_SITE` | users per macro site for the FCC Part 4 check | 1500 |
| `SIM_TICK_SECONDS` | real seconds per simulated 15-minute window | 3 |
| `OPS_EMAIL`, `OPS_PASSWORD` | optional private legacy API sign-in; not needed for demo entry | password empty |
| `CUSTOMER_EMAIL`, `CUSTOMER_PASSWORD` | optional private legacy API sign-in; not needed for demo entry | password empty |

Restart the server after changing `.env`.

## 5. Database

Nothing to set up. `Store` creates `data/sentinel.db` and its tables on first start (`CREATE TABLE IF NOT EXISTS`). **Incident, ledger, engineering-ticket and customer-update tables are emptied at every start and demo reset**. Customer support requests and replies persist separately. There are no migrations and no backups. The schema is in [API and database](API_AND_DATABASE.md).

## 6. Health checks

1. **The server is up:** http://127.0.0.1:8000/ redirects to `/ops/`, and the demo entry page loads.
2. **The simulator is running:** after choosing Explore engineer demo, the clock in the top bar advances every `SIM_TICK_SECONDS`, and the status bar shows "Updated hh:mm:ss".
3. **The models are connected:** the top bar shows "Meta Model API" rather than "Offline rules engine". The status bar shows the primary model, the number of calls and the average latency.
4. **Each Meta model works with your key:** `.\.venv\Scripts\python.exe scripts/check_meta.py`. Options: `--image site.jpg` and `--audio note.wav`. The script prints only the key's last 4 characters.
5. **Each agent works live through the app code:** `.\.venv\Scripts\python.exe scripts/audit_agents.py` (add `--json out.json` to save the results). It prints PASS / FALLBACK / FAIL per agent.

## 7. Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q  # offline; see current verification report for results
.\.venv\Scripts\python.exe scripts/check_local_install.py  # isolated startup/demo-entry/fault smoke test
```

Live refresh in a real browser. One-time setup, in the project folder:

```powershell
npm i --no-save playwright
npx playwright install chromium
```

Then start the app in one window (`.\.venv\Scripts\python.exe run.py`) and run the check in a second window, also in the project folder:

```powershell
node scripts\check_live_refresh.js
```

The script opens both no-login demos. If there is no incident yet, it creates a hardware fault on `SEA-RAN-001` so the click check has a row to click. Use an isolated offline server whose sample state can be changed. It takes about two minutes. It reports a plain error if Playwright is missing, the app is unreachable or demo entry fails. `BASE_URL` selects a different local port.

Local speech and navigation regressions are checked by `node scripts/check_local_speech.js` and `node scripts/check_navigation_ui.js`. Voice workflow and memory checks use `check_voice_ui.js` and `check_voice_memory_ui.js`; customer support uses `check_support_ui.js`. These require Playwright only for testing, not normal installation.

Benchmarks: `py scripts\benchmark_simulator.py`. For TelecomTS, `pip install huggingface_hub`, then `py scripts\benchmark_telecomts.py --export-features data\telecomts_features.csv.gz`.

## 8. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| "Offline rules engine" everywhere | `MODEL_API_KEY` is empty, or `.env` is not in the project root | put the key in `.env` in the project folder and restart |
| An agent shows a fallback model or a template | the primary model failed or timed out | check the agent console on the incident page; run `check_meta.py` |
| `[Errno 10048]` / address already in use | another server on port 8000 | stop your previous server, or run `python run.py --port 8001` |
| The map shows outlines only, with a note | no internet, or the tile host is blocked | expected offline; the outlines and the network still work |
| "Connection lost · showing data from …" | the server stopped or the network dropped | restart `.\.venv\Scripts\python.exe run.py`; the page recovers within 15 s by itself |
| `Cannot find module 'playwright'` (older script) or "Playwright is not installed" | Playwright not installed in the project folder | run `npm i --no-save playwright` and `npx playwright install chromium` in `ran-sentinel` |
| `locator.boundingBox: Timeout 30000ms exceeded` waiting for `tr.click` (older script) | there were no incident rows: a fresh start with no fault, or demo entry did not finish | use the current script, which opens the no-login demos and creates a fault itself |
| Data seems to stop after a long idle | the tab was hidden (polling pauses) | bring the tab to the front; it refreshes at once |
| Everything is gone after a restart | by design: store and memory are reset at start | — |
| `py` not found | Python is not installed or not on PATH | install Python 3.10+ from python.org |

## 9. Verification checklist

- [ ] `python -m pytest -q` reports all tests passed (see the current installation verification report).
- [ ] `node scripts/check_support_ui.js` reports all 53 support UI checks passed (app running).
- [ ] Optional live AI: `.\.venv\Scripts\python.exe scripts/check_meta.py` passes for every model you use (requires provider access and may incur charges).
- [ ] Optional live AI: `.\.venv\Scripts\python.exe scripts/audit_agents.py` ends with "All agents passed live."
- [ ] The console clock advances and shows "Offline rules engine" without a key; with optional live access it shows "Meta Model API".
- [ ] Demo controls → create a Capacity surge → an incident opens within about two windows and reaches the approvals queue.
- [ ] Approve it; the M-Plane commit is confirmed after monitoring, or rolled back.
- [ ] The customer app shows a plain-language update for an affected place, with no cell ids.
- [ ] `node scripts\check_live_refresh.js` reports 12 of 12 PASS.
- [ ] `.env` and any key file are not committed (`git status` shows neither).

## 10. Deployment

Not supported yet. Before any shared or hosted deployment, at least the following would be needed:
- HTTPS and the `Secure` cookie flag;
- hashed credentials and session expiry;
- disable open demo entry and add CSRF protection and rate limits to state-changing routes;
- a persistent store that is not reset at start;
- binding to an address other than `127.0.0.1` in `run.py`.

None of this has been built or tested.
