# Local installation verification

## Native Safari, audio and Docker — 4 November 2026

### Actual Safari browser

The [successful native Safari run](https://github.com/AKMaasif/Meta-Ai-Global-Hackathon-Ran-Sentinel-/actions/runs/41702251423) used **Safari 26.6.2** on a GitHub-hosted Mac through Apple's native Safari driver. **All 13 checks passed**:

- Engineer login, console rendering and search; customer login and navigation.
- Recording/Web Audio API availability, plus synthetic audio through the actual `UI.listen` recording path: silence detection and conversion to mono **16 kHz WAV**.
- Contextual complaint drafting, location correction, refresh restoration, read-back, later confirmation, repeat-confirmation protection, New conversation and viewport fit.

The audio input for that automated check was a generated tone supplied as a synthetic microphone stream. It did not use a physical Mac microphone. The UI checks do not establish audible speech quality or live-provider recognition accuracy. Native Safari checks are available in `.github/workflows/safari.yml` and `scripts/check_safari_ui.py`; Selenium is an optional test dependency, not an application installation requirement.

Initial test runs exposed stale-element/timing races in the automation around repainted controls. The test now waits for controls and reads the current proposal ID atomically; application behavior was not changed for those failures.

### Physical microphone

The project owner separately tested the local customer app with a physical microphone: “My data is slow at work” → “Report that” → “Cancel.” They confirmed that the agent heard the requests, prepared the draft and cancelled without submitting. This is a reported hardware check on the owner's PC, not a macOS/iPhone microphone benchmark.

### Fresh Docker/Maveric integration

A separate checkout of upstream Maveric commit `7573f030523669eaa3bb215fb3b29985c06824c8` was built and started with Docker Desktop's Linux containers on this Windows x86_64 PC. A separate Compose project and volume kept existing containers and models untouched.

The first Windows checkout converted the Kafka entrypoint to CRLF, producing `exec /entrypoint.sh: no such file or directory`. Preserving Linux line endings fixed startup. The [Docker guide](MAVERIC_TWIN.md#setup-once) now clones Maveric with `--config core.autocrlf=false` before building.

The new test model used **12,960 rows across 36 cells** and trained in **30 seconds**. Its tilt +2°, power −2 dB and power −8 dB what-if calls all returned coverage predictions. RAN Sentinel's own `MavericTwin.simulate` returned **Maveric RF twin (coverage) + simulator copy (load)**, confirming use of real Maveric coverage rather than fallback. The test containers were stopped afterwards; the user's `.env` was not changed.

This Docker check does not verify Docker on macOS/Apple Silicon or every Linux host. The native Python installation checks below are separate from the external twin.

## Linux and macOS verification — 4 November 2026

The [public GitHub Actions run](https://github.com/AKMaasif/Meta-Ai-Global-Hackathon-Ran-Sentinel-/actions/runs/41698614152) checked commit `dca1fd3` on fresh Linux and macOS runners. Each job cloned the repository, used the README's `python3 -m venv .venv` and `.venv/bin/python` commands, installed `requirements.txt`, copied `.env.example`, checked dependencies, started a temporary local app, checked both portals, and ran the full application suite. External-service keys were empty.

| Environment | Python | Installation and both-portal smoke check | Application tests |
|---|---|---|---|
| GitHub-hosted Ubuntu, Linux x86_64 | 3.14.9 | Passed | **207 passed**, 280.47 seconds |
| GitHub-hosted macOS, Darwin 25.6.0, Apple Silicon arm64 | 3.14.10 | Passed | **207 passed**, 306.40 seconds |
| Local Ubuntu 26.04.1 LTS under WSL2, x86_64 | 3.14.4 | Passed after installing `python3.14-venv` | Full suite checked on the separate hosted Ubuntu runner |

The smoke checks covered bundled UI assets, both default logins, customer access restrictions, 36 cells, advancing telemetry, an injected fault, its investigation and department ticket. They verify that the local server starts and serves both apps; these were not Safari or physical microphone tests. Docker/Maveric and live provider access were not part of these offline platform checks.

The workflow at `.github/workflows/local-install.yml` repeats these checks for relevant code changes and pull requests, and can be started manually from Actions. It uses read-only repository permissions and no API secrets. Its dependency installation uses a new virtual environment rather than the developer's installed packages.

Ubuntu can omit Python's venv support. The local WSL test exposed that prerequisite, and succeeded after installing the matching package. The README now shows `python3-venv` and the version-specific alternative named by Python's error message.

## Fresh judge installation — 4 November 2026

Verified the published application at commit `0567cf91ec74650df874999b591cb3e91dfaabbf` from a new public GitHub clone in a separate folder. Created a new virtual environment with `py -3 -m venv .venv`, installed `requirements.txt`, and copied `.env.example` to `.env`. No existing project environment, database or credentials were copied.

Environment: Windows, 64-bit CPython 3.14.7. Requirements resolved successfully, including OpenAI SDK 3.43.0, FastAPI 0.162.0, NumPy 2.5.4 and scikit-learn 1.9.1. `pip check` found no broken requirements. The Windows batch launcher also passed its `--help` invocation after checking dependencies.

The full published application suite passed: **207 tests in 289.10 seconds**, using `python -m pytest tests -q -p no:cacheprovider` in the new environment with external-service keys disabled.

The isolated installation smoke check passed both portals, bundled assets, default engineer/customer logins, customer access restrictions, 36 simulated cells, advancing telemetry, an injected hardware fault and its investigation ticket. No external model calls were made.

The README now separates **1. Local demo**, **2. Live AI and voice**, and **3. Docker RF twin**, with default accounts, manual commands, success checks and port-conflict instructions. Only Section 1 is required to run the basic demo.

This Windows check did not cover a fresh Docker/Maveric deployment; subsequent Linux/macOS results are recorded above. Live AI features require each judge's own provider access; the clean offline installation does not establish model availability or credits.

## Earlier verification — 3 November 2026

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
