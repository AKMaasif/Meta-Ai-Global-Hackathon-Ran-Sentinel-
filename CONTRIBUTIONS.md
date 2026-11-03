# What was built for this project, and what was not

AKMaasif built the original RAN Sentinel application from scratch as a solo project, completing the project build between **27 October and 2 November 2026**. No code from a pre-existing personal project or another contestant's repository was reused. Subsequent voice-workflow, documentation, presentation and installation-verification updates are recorded in the Git history.

This originality statement applies to the application work listed below. It does not claim authorship of third-party libraries, bundled map assets, datasets or externally accessed models. Those components are credited separately under their respective licences and terms; Maveric runs as a separate service.

## Built for this project (original work)

About 13,000 lines of Python, JavaScript and CSS, plus the documentation.

| Area | What was built | Where |
|---|---|---|
| Network simulator | A simulated 36-cell LTE cluster in Seattle (bands B66, B2, B71) with live KPIs and five injectable fault types | `backend/app/simulator.py`, `radio.py` |
| Detection | Threshold rules + Isolation Forest + per-cell, per-hour Mahalanobis baseline, tuned on the TelecomTS dataset | `backend/app/detection.py`, `scripts/benchmark_*.py` |
| Agent workflow | Orchestrator state machine, Muse Spark investigator with read-only tools, root-cause analyst, planner, reviewer, reporter, escalation and shift handover | `backend/app/orchestrator.py`, `agents.py`, `tools.py` |
| Diagnosis verifier | Hidden playbook check, fact lookup in evidence, claims check on a second model, field-evidence pause and resume, living plan, checkpoints | `backend/app/verify.py`, `workplan.py`, `fielddocs.py` |
| Safety | Nine fixed safety rules and the Evidence-to-Action Safety Ledger | `backend/app/safety.py`, `store.py` |
| Radio change path | Open M-Plane style change packages with confirmed-commit and automatic rollback, against a simulated radio unit | `backend/app/mplane.py` |
| Digital twin | What-if checks; client and training-data generator for Meta's Maveric | `backend/app/twin.py`, `maveric.py`, `scripts/maveric_setup.py` |
| Meta model integration | Provider with fallback chain (Spark 1.3 → 1.2 → 1.1), SAM 3.1 photo analysis, Voice Transcribe, Muse Wonder, Gemini TTS | `backend/app/providers.py` |
| FCC Part 4 check | User-minute tracking and a Regulatory Compliance desk | `backend/app/regulatory.py` |
| Operations console | OSS-style console: overview, alarm monitor, cell explorer, incidents, approvals, ledger, model card, customer support desk | `frontend/ops/` |
| Customer app | Northstar Connect: home, network, account, bill, alerts, outage credits, Care Concierge, voice agent, help center and support tickets | `frontend/connect/`, `backend/app/care.py`, `support.py` |
| Voice conversation memory | Session-scoped dialogue, older context notes, issue and draft tracking, corrections, approval IDs, request retry protection and refresh restoration | `backend/app/voice_memory.py`, `frontend/connect/app.js` |
| Live updates | In-place page patching and serial polling | `frontend/shared/ui.js` |
| Security | Portal-bound sessions, login lockout, file upload checks | `backend/app/main.py` |
| Tests | 207 pytest tests and four Playwright browser checks | `tests/`, `scripts/check_*.js` |
| Documentation | README, docs/ guides, user manual and technical documentation PDFs, sample field-evidence files (drawn illustrations) | `docs/`, `samples/` |

## Not built for this project (used under their licences)

| Component | Use | Licence |
|---|---|---|
| Meta Model API: Muse Spark 1.3/1.2/1.1, Muse Wonder 1.0, SAM 3.1, Muse Voice Transcribe 1.0 | The AI models, called over the API | Meta terms |
| Google Gemini TTS | Spoken replies in the voice agent (Meta has no text-to-speech model) | Google terms |
| Maveric (lf-connectivity) | RF digital twin; run separately in Docker, not included in this repo | MIT |
| Open M-Plane (lf-connectivity) | Referenced for the change-package format; not included | MIT |
| FastAPI, Uvicorn, NumPy, httpx, scikit-learn, OpenAI Python SDK, python-dotenv, pypdf | Python libraries installed from `requirements.txt` | MIT / BSD / Apache-2.0 |
| Leaflet 1.9.4, topojson-client 3.1.0, us-atlas 3.0.1 | Maps; bundled in `frontend/shared/vendor/` with their licence files | BSD-2 / ISC |
| OpenStreetMap and CARTO tiles | Street map background, loaded online only | ODbL / CARTO terms |
| IBM Plex fonts | Typography | SIL OFL |
| TelecomTS dataset | Benchmarking the detector only; not redistributed | MIT |
| Legal-agent workshop (meta-models) | Design patterns that the verifier follows; no code copied | — |

No Meta or vendor endorsement is implied. The network, operator and subscriber are fictional and simulated.
