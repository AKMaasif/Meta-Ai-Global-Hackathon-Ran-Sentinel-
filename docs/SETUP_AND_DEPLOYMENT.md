# Setup and deployment

RAN Sentinel runs as one local Python process on Windows (it was run on the project PC (Windows) with Python 3.14, and the test suite also runs on Linux). There is **no deployment configuration** in the repository: no Dockerfile, no cloud manifests, no reverse-proxy or TLS setup. Running it anywhere other than `127.0.0.1` has not been tested; see [Security](SECURITY_AND_ACCESS_CONTROL.md) before trying.

## 1. Prerequisites

| Need | For | Notes |
| --- | --- | --- |
| Python 3.10 or newer (`py` launcher on Windows) | the app, tests, scripts | `start.bat` stops with a link if `py` is missing |
| A Meta Model API key | Meta-powered agents | optional: without it the app uses the offline rules engine and says so on screen |
| Internet access | Meta models, street map tiles | optional: state outlines and Leaflet are bundled in `frontend/shared/vendor/` |
| Node.js + Playwright | `scripts/check_live_refresh.js` only | optional |
| `huggingface_hub` | `scripts/benchmark_telecomts.py` only | optional, downloads 1.1 GB once |

Python packages (`requirements.txt`): fastapi, uvicorn[standard], numpy, scikit-learn, openai, httpx, python-dotenv, pytest.

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
    shared/              ui.js (api, morph, poller), geomap.js, base.css, vendor/
    ops/                 operations console (index.html, app.js, ops.css)
    connect/             customer app
  scripts/               check_meta.py, audit_agents.py, check_field_files.py, benchmark_*.py, check_live_refresh.js
  tests/                 pytest suite
  data/                  sentinel.db (created at start), benchmarks/*.json
  docs/                  this documentation, workflow.mmd
```

## 3. Install and run

### One click (Windows)

Double-click `start.bat`. On the first run it:

1. creates `.venv` with `py -m venv .venv`;
2. runs `pip install -r requirements.txt`;
3. copies `.env.example` to `.env` if there is no `.env`;
4. opens http://127.0.0.1:8000/ops/ after 5 seconds;
5. runs `py run.py`.

Later runs skip steps 1–3.

### Manual

```powershell
cd "D:\Meta Ai Heckatho\ran-sentinel"
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
py run.py
```

Open the operations console at http://127.0.0.1:8000/ops/ and the customer app at http://127.0.0.1:8000/connect/.

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
| `GOOGLE_API_KEY` | Gemini key for the voice agent's spoken replies; empty = browser voice | empty |
| `TTS_MODEL`, `TTS_FALLBACK_MODEL`, `TTS_VOICE` | Gemini TTS models and voice | `gemini-3.8-flash-lite-tts`, `gemini-3.8-flash-tts`, `Kore` |
| `REASONING_EFFORT`, `AGENT_EFFORT` | optional reasoning effort, for every agent or per agent (`analyst=high,voice_agent=minimal`) | empty = model default |
| `ONE_TOOL_PER_TURN` | investigator runs one tool per model turn (`0` to allow parallel calls) | `1` |
| `FIREWORKS_API_KEY` | optional last fallback on Muse Spark Open (Fireworks, billed per token) | empty = never called |
| `MAVERIC_URL` | optional Maveric RADP service, e.g. http://localhost:8080 ([setup](MAVERIC_TWIN.md)) | empty = fallback twin |
| `MAVERIC_MODEL` | model trained by `scripts/maveric_setup.py` | `ran-sentinel-seattle` |
| `MAVERIC_TIMEOUT_SECONDS` | wait per Maveric simulation before falling back | `90` |
| `FCC_USERS_PER_SITE` | users per macro site for the FCC Part 4 check | 1500 |
| `SIM_TICK_SECONDS` | real seconds per simulated 15-minute window | 3 |
| `OPS_EMAIL`, `OPS_PASSWORD` | operations sign-in | demo values; set your own |
| `CUSTOMER_EMAIL`, `CUSTOMER_PASSWORD` | customer sign-in | demo values; set your own |

Restart the server after changing `.env`.

## 5. Database

Nothing to set up. `Store` creates `data/sentinel.db` and its tables on first start (`CREATE TABLE IF NOT EXISTS`). **The tables are emptied at every start and every demo reset**, so the database holds only the current shift. There are no migrations and no backups. The schema is in [API and database](API_AND_DATABASE.md).

## 6. Health checks

1. **The server is up:** http://127.0.0.1:8000/ redirects to `/ops/`, and the sign-in page loads.
2. **The simulator is running:** after sign-in, the clock in the top bar advances every `SIM_TICK_SECONDS`, and the status bar shows "Updated hh:mm:ss".
3. **The models are connected:** the top bar shows "Meta Model API" rather than "Offline rules engine". The status bar shows the primary model, the number of calls and the average latency.
4. **Each Meta model works with your key:** `py scripts\check_meta.py`. Options: `--image site.jpg` and `--audio note.wav`. The script prints only the key's last 4 characters.
5. **Each agent works live through the app code:** `py scripts\audit_agents.py` (add `--json out.json` to save the results). It prints PASS / FALLBACK / FAIL per agent.

## 7. Tests

```powershell
python -m pytest -q                      # 125 tests, about 3 minutes, no key or network needed
```

Live refresh in a real browser. One-time setup, in the project folder:

```powershell
npm i --no-save playwright
npx playwright install chromium
```

Then start the app in one window (`py run.py`) and run the check in a second window, also in the project folder:

```powershell
node scripts\check_live_refresh.js
```

The script reads `OPS_EMAIL`, `OPS_PASSWORD`, `CUSTOMER_EMAIL` and `CUSTOMER_PASSWORD` from `.env` (or from the environment, which wins) and never prints them. If there is no open incident yet, it creates one hardware fault on `SEA-RAN-001` through Demo controls, so the click check has a row to click. It takes about 2 minutes. It stops with a plain message, exit code 2, if:
- Playwright is missing;
- the app is not running;
- a password is not found;
- a sign-in fails.

Benchmarks: `py scripts\benchmark_simulator.py`. For TelecomTS, `pip install huggingface_hub`, then `py scripts\benchmark_telecomts.py --export-features data\telecomts_features.csv.gz`.

## 8. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| "Offline rules engine" everywhere | `MODEL_API_KEY` is empty, or `.env` is not in the project root | put the key in `ran-sentinel\.env` and restart |
| An agent shows a fallback model or a template | the primary model failed or timed out | check the agent console on the incident page; run `check_meta.py` |
| `[Errno 10048]` / address already in use | another server on port 8000 | close the other window, or stop the process using the port |
| "This is an engineer account…" or "This is a Northstar Connect customer account…" on sign-in | the right account on the wrong portal | sign in on the other app: engineers at `/ops/`, customers at `/connect/` |
| "Email or password is incorrect" | the values differ from `.env` | check `OPS_*` / `CUSTOMER_*` in `.env`, then restart |
| The map shows outlines only, with a note | no internet, or the tile host is blocked | expected offline; the outlines and the network still work |
| "Connection lost · showing data from …" | the server stopped or the network dropped | restart `py run.py`; the page recovers within 15 s by itself |
| `Cannot find module 'playwright'` (older script) or "Playwright is not installed" | Playwright not installed in the project folder | run `npm i --no-save playwright` and `npx playwright install chromium` in `ran-sentinel` |
| `locator.boundingBox: Timeout 30000ms exceeded` waiting for `tr.click` (older script) | there were no incident rows: a fresh start with no fault, or the sign-in did not happen | use the current script, which signs in from `.env` and creates a fault itself |
| Data seems to stop after a long idle | the tab was hidden (polling pauses) | bring the tab to the front; it refreshes at once |
| Everything is gone after a restart | by design: store and memory are reset at start | — |
| `py` not found | Python is not installed or not on PATH | install Python 3.10+ from python.org |

## 9. Verification checklist

- [ ] `python -m pytest -q` reports all tests passed (129 at the time of writing).
- [ ] `py scripts\check_meta.py` passes for every model you use.
- [ ] `py scripts\audit_agents.py` ends with "All agents passed live."
- [ ] The console shows "Meta Model API" and the clock advances.
- [ ] Demo controls → create a Capacity surge → an incident opens within about two windows and reaches the approvals queue.
- [ ] Approve it; the M-Plane commit is confirmed after monitoring, or rolled back.
- [ ] The customer app shows a plain-language update for an affected place, with no cell ids.
- [ ] `node scripts\check_live_refresh.js` reports 12 of 12 PASS.
- [ ] `.env` and any key file are not committed (`git status` shows neither).

## 10. Deployment

Not supported yet. Before any shared or hosted deployment, at least the following would be needed:
- HTTPS and the `Secure` cookie flag;
- hashed credentials and session expiry;
- CSRF tokens and rate limiting on sign-in;
- a persistent store that is not reset at start;
- binding to an address other than `127.0.0.1` in `run.py`.

None of this has been built or tested.
