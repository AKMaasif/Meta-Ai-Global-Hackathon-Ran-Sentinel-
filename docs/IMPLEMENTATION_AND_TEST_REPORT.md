# Implementation and test report: live refresh fix and documentation

Date: 2026-10-28. Scope: fix the continuous-refresh flicker and the clicks that needed repeating, without losing live updates, and write the system documentation from the source.

## 1. Summary

The screens blinked and clicks were lost because every refresh replaced the whole application's DOM (`app.innerHTML = …`). The refresh ran from `setInterval`, so requests could overlap.

The fix keeps polling, the same intervals and the same endpoints. Two shared helpers in `frontend/shared/ui.js` change how a refresh is applied and scheduled:

- `UI.morph` patches the page in place.
- `UI.poller` runs one refresh at a time, with cancellation, backoff, a pause for hidden tabs and a visible stale state.

The render functions are unchanged. Details are in [Live-update architecture](LIVE_UPDATE_ARCHITECTURE.md).

## 2. Before and after (measured)

Measured in headless Chromium against the running app. The "before" figures come from the original frontend files, swapped in temporarily and then restored. The customer-app baseline run failed, so its "before" column is marked not measured. The ops map element already survived refreshes before the fix, and fast navigation already ended on the right page.

| Measure | Before | After |
| --- | --- | --- |
| Elements replaced per dashboard refresh | about 660 (1,974 removals in 6 s) | 0 over 3 refreshes |
| Fade animation replays in 6 s | 3–4 | 0 |
| Click held across a refresh opens the incident | 1 of 4 | 4 of 4 |
| Evidence `<details>` open after 5 s | closed | open |
| Search box text across refreshes | kept, but refresh skipped while focused | kept, and the page keeps updating |
| Slow backend (2.5 s per `/api/state`): requests in 10 s | 5, 2 at once | 2, at most 1 at once |
| Backend unreachable | silent, last screen unchanged | "Connection lost · showing data from … · retrying in N s"; recovers within 15 s |
| Customer Network page, elements replaced in 11 s | not measured (same `innerHTML` pattern) | 2–4 |
| Customer scroll position (900 px) after refresh | not measured | kept |
| Customer tab tap across a refresh | not measured | 4 of 4 |
| Customer Explain double tap | not measured (a refresh re-enabled the button) | 1 request |

## 3. Files changed

| File | Change |
| --- | --- |
| `frontend/shared/ui.js` | new `morph` (DOM patching that keeps focus, typed values, `details` and `dialog` open state, and `data-keep` children) and `poller` (serial `setTimeout`, generation counter, `AbortController`, backoff ×2 to 15 s, hidden-tab pause, `online` resume, pointer-down deferral, `paused()` hook); `api()` attaches the active abort signal to GETs |
| `frontend/ops/app.js` | `live()` and `refresh()` use the poller; `paint()` morphs; `#feed` freshness indicator in the status bar; map slot marked `data-keep` |
| `frontend/ops/ops.css` | `#feed.stale` and `.work.stale` styles |
| `frontend/connect/app.js` | `view.html` morphs; one poller for live pages (5 s) and the notification check (8 s); "Connection lost" / "Back online" toasts; Explain button state in `ui.reading`; actions call `poll.now()` |
| `frontend/shared/geomap.js` | `mount` removes leftover empty-state content from the slot |
| `scripts/check_live_refresh.js` | new Playwright check, 12 assertions |
| `.gitignore` | adds `meta api key.txt`, `*api key*.txt` and `*api_key*.txt`, so a plain-text key file is not committed |
| `docs/*.md` | 7 new documents (this one included) |
| `README.md` | documentation index and the live-refresh check |

No backend code changed in this task.

## 4. Tests run

| Test | Result | Where it ran |
| --- | --- | --- |
| `python -m pytest -q` | **125 passed**, 189 s | cloud copy (Linux), 2026-10-30, after the verified-investigation work |
| `python -m pytest -q` | **81 passed**, 6 warnings, 198.7 s | cloud copy (Linux), after the frontend changes |
| `node scripts/check_live_refresh.js` | **12 of 12 PASS** | cloud copy, against a freshly started app with sign-in read from `.env` (2026-10-30). Also checked: clear messages for app not running, missing password, wrong password |
| `py scripts\audit_agents.py` | **all 15 checks PASS**, "All agents passed live." | your PC with your Meta key, before this task (no agent code changed since) |

The 12 browser checks:

1. Ops: no screen rebuild over 3 refreshes.
2. Ops: the map survives refreshes.
3. Ops: a click held across a refresh opens the incident.
4. Ops: text typed across refreshes is kept.
5. Ops: live data keeps flowing.
6. Ops: a slow backend gets one request at a time.
7. Ops: a lost connection is shown and the last data is kept.
8. Ops: the page recovers within 15 s after the connection returns.
9. Connect: no page rebuild over 2 refreshes.
10. Connect: the scroll position and the map survive.
11. Connect: a tap across a refresh switches tab.
12. No JavaScript errors.

These were checked with one-off measurement scripts during the fix and are not in the repeatable check:
- details stay open;
- Demo-control selections are kept;
- the last page wins on fast navigation;
- the Explain double tap sends 1 request.

## 5. Verified and not verified

**Verified:** everything in sections 2 and 4.

**Not verified:**
- **Your PC:** the first two runs on your PC stopped before any check ran. One was missing Playwright; the other was a fresh app with no incident row to click. Both now give a clear message or are handled by the script. A full pass on your PC is not confirmed yet.
- **Hidden-tab pause:** checked by code review only.
- **Browsers:** tested in Chromium only, not Firefox or Safari. Mobile was tested by emulating a 390 px viewport, not on a real device.
- **Load:** there was no load test with more cells or many open browsers.
- **Documentation:** written from the source and checked against it (file paths, function names, env vars, routes). It describes behaviour only where code or tests show it, and marks the rest.

## 6. Remaining issues and next steps

- **Poll volume:** polling sends full snapshots. If the network grows well beyond 36 cells, add an incremental `/api/state?since=` or a Server-Sent Events stream for alarms.
- **Row matching:** `morph` matches list rows by position when they have no id. Adding ids to table rows would make re-sorts exact.
- **Security gaps:** these are listed in [Security](SECURITY_AND_ACCESS_CONTROL.md) section 7: sessions with no expiry, no CSRF tokens, no rate limit, and default demo passwords if `.env` does not set them.

## 7. Change history

From the work in this project, most recent first:

| Change | Main files |
| --- | --- |
| Field evidence files: photo, CSV, PDF, DOCX and TXT attached on the incident page and read by the Field Document Analyst (Muse Spark); `check_field_files.py` live check. RAN Optimisation card shows the change as a facts table with a collapsible second opinion. Every submit button shows a busy state. 129 tests pass | `fielddocs.py`, `agents.py`, `orchestrator.py`, `frontend/ops/`, `frontend/shared/ui.js` |
| Maveric RF twin wired in: trains on the Seattle cluster, predicts coverage before and after tilt or power changes (MAE 1.26 dB vs the radio model) | `maveric.py`, `twin.py`, `scripts/maveric_setup.py`, [MAVERIC_TWIN.md](MAVERIC_TWIN.md) |
| Verified investigation from Meta's legal-agent workshop: diagnosis verifier, field-evidence pause and resume, root-cause sign-off, living plan, one tool per turn, checkpoints and resume; investigation eval script; reasoning effort per agent; UL interference threshold fix (mild interference was missed). 120 tests pass | `verify.py`, `workplan.py`, `orchestrator.py`, `agents.py`, `scripts/eval_investigation.py`, [VERIFIED_INVESTIGATION.md](VERIFIED_INVESTIGATION.md) |
| Customer voice agent: Muse Voice Transcribe + Muse Spark + Gemini TTS, orb UI, instant commands, sentence-by-sentence speech | `care.py`, `providers.py`, `frontend/connect/`, [VOICE_AGENT.md](VOICE_AGENT.md) |
| Live refresh fix, documentation set, `.gitignore` key-file patterns | this report |
| Live agent audit script; customer map limited to 3 km; signal card and Signal Analyst; ops map site popups; map fixes | `scripts/audit_agents.py`, `care.py`, `radio.py`, `geomap.js` |
| Northstar Connect customer app with the AI care layer and Care Concierge | `care.py`, `frontend/connect/` |
| Separate sign-in per portal, with a pointer to the right one | `main.py` (`/api/login`) |
| OSS-style operations console redesign | `frontend/ops/` |
| Meta model integration (Muse Spark tiers, Wonder, SAM 3.1, voice), FCC Part 4 check, TelecomTS benchmark | `providers.py`, `agents.py`, `regulatory.py`, `scripts/` |
