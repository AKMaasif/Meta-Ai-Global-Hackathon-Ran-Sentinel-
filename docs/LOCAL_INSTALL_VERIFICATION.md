# Local installation verification

Checked on **3 November 2026** against a fresh clone of the public GitHub repository, with the launcher and installation fixes in this change applied before testing.

## Environment and scope

- Windows, 64-bit CPython 3.14.7, a newly created `.venv`.
- Installed only `requirements.txt` for the app. No pre-existing project environment, database, API keys, Docker service or downloaded TelecomTS dataset was needed.
- Fresh `.env` copied from `.env.example`; model keys and the external twin URL were empty.
- Tested locally on loopback. This verifies the local offline demo, not hosted production operation or access to third-party models.

## Checks

| Check | Result |
|---|---|
| Full Python suite | Passed: **182 tests**, 327.30 seconds, in the fresh environment |
| Fresh `pip install -r requirements.txt` | Passed |
| `python -m pip check` | Passed: no broken requirements |
| Windows `start.bat --help` | Passed: environment/dependency checks and launcher arguments work |
| Isolated `python scripts/check_local_install.py` | Passed: portals, static assets, both default logins, 36 cells, customer access boundary, advancing telemetry, injected fault and investigation ticket |
| Browser live-refresh workflow | Passed: all 12 checks, including refresh interactions and connection recovery |
| Browser support workflow | Passed: all 53 checks across phone, tablet and desktop |

The isolated smoke script creates its own temporary application copy and database, uses a free port, blanks external-service keys, and stops its server afterwards. It does not reset an existing local demo.

## Installation fixes

The Windows launcher now checks dependencies on every run, so an interrupted installation can be retried. It preserves an existing `.env`, supports either the Windows `py` launcher or `python`, calls the virtual environment directly, and propagates startup failures. Manual instructions also use the virtual environment directly, avoiding PowerShell activation restrictions.

The Python launcher checks a busy port before application initialization, avoiding a demo database reset when another server already owns the requested port. It supports `--port 8001` and prints both portal addresses. Launcher regression tests cover help, invalid ports and occupied ports.

The README and setup guide document default accounts, optional model credentials, offline behavior, platform commands and port conflicts. Node.js and Docker are optional, not basic installation requirements.

## Tested dependency versions

The clean install resolved FastAPI 0.162.0, Uvicorn 0.54.0, NumPy 2.5.4, scikit-learn 1.9.1, OpenAI SDK 3.42.1, HTTPX 0.28.1, python-dotenv 1.2.4, pypdf 6.21.4 and pytest 9.2.0. These record this verification environment; requirements remain compatible version ranges and a later install may resolve different releases.

## Limits

macOS, Linux and other Python versions were not exercised in this clean-install check. Their setup commands are supplied in the README. Initial dependency installation needs internet access. Live Meta, Google and Maveric features require the user's own access and services; this offline check does not validate provider availability, credits or model permissions. Browser microphone and speech capabilities also depend on the browser. Run one server per checkout because simulator state resets on startup. This repository is a local demo, with simulated radio controls, rather than a production deployment package.
