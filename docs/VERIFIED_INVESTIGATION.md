# Verified investigation

How an investigation is checked, paused, planned and resumed. The design follows the patterns in Meta's
[legal-agent workshop](https://github.com/meta-models/legal-agent-workshop): the model investigates, but code decides whether
the result is good enough to act on, and a person signs off.

Code: `backend/app/verify.py`, `backend/app/workplan.py`, `backend/app/agents.py` (investigator tools),
`backend/app/orchestrator.py` (`run_investigation`, `_verify`, `_pause`, `provide_evidence`, `sign_off_rca`,
`resume_investigation`). Tests: `tests/test_verify.py`, `tests/test_field_evidence.py`, `tests/test_plan_and_resume.py`.

## 1. Where it sits in the pipeline

```
detect -> investigate -> analyse -> VERIFY -> plan -> safety rules -> twin -> reviewer -> department -> change -> monitor
              ^   |          |         |
              |   |          |         +-- refused: missing evidence is fetched, the analyst gets the reasons (max 3, then a person)
              |   |          +------------ data cannot settle it: PAUSE and ask a field engineer (once, then a person)
              |   +----------------------- every step saved; an API failure resumes from the last step
              +--------------------------- the living plan is updated at every step
```

No remediation plan is drafted on a diagnosis that has not passed the verifier.

## 2. The investigator

| Tool | What it does | Uses the tool budget |
|---|---|---|
| `update_plan` | Writes or rewrites the plan: 2-10 steps (todo, doing, done, dropped) and one line on why | No |
| `set_checklist` | 4-8 checklist items; at least one must look for evidence **against** the leading suspicion | No |
| `get_anomaly_result`, `get_kpi_window`, `get_alarm_history`, `get_cell_configuration`, `run_diagnostic_check` | Read-only data, scoped to the incident cell and its neighbours | Yes (8 per run) |
| `request_evidence` | Pauses the run and asks a field engineer for what the tools cannot see | No |

The investigator makes **one tool call per turn** (`ONE_TOOL_PER_TURN=1`, the default). If the model asks for several at once, only
the first runs and the others are answered "not run: call one tool per turn". It is slower than parallel calls, but every step is
traceable, the plan can change between steps, and progress can be saved after each one.

Without a Meta key, a rules investigator follows a fixed checklist and plan, so the offline demo shows the same panels.

## 3. The verifier

Four checks run on every diagnosis. The agents cannot skip them.

1. **Playbook coverage (hidden).** For each cause, a list of what an engineer must have seen before accepting it. The agents never
   see the list; a refusal names the kind of evidence that is missing ("offload neighbour headroom checked"), never the right cause.

   | Cause | Playbook (plus "detector result read" and "alarm history reviewed" for every cause) |
   |---|---|
   | Capacity congestion | PRB load measured; SINR or CQI measured; offload neighbour headroom checked |
   | Overshooting coverage | Far-user share measured; running tilt compared with the radio plan |
   | External interference | UL RSSI measured; SINR or CQI measured; uplink interference scan run |
   | Hardware fault | VSWR and power read back; drops or availability measured |

2. **Facts.** The analyst must state 1-5 key facts as `{evidence_id, metric, value}`. Code looks each value up in that evidence
   result (2% tolerance for numbers). A number that is not there is refused. This is the workshop's `record_fact` idea, checked in
   code instead of by quote matching.
3. **Root-cause rules (code):** a known cause; strong or moderate support with cited evidence; the cause's confirming check run;
   a clear margin over the runner-up; at least one alternative cause weighed against evidence.
4. **Claims check (model).** Muse Spark 1.2 (`REVIEWER_MODEL`), a different model from the analyst, reads the reasoning against the
   evidence and lists any claim the evidence does not back. If that model is unavailable the check is marked NOT_RUN, not failed.

A refused diagnosis goes back with the reasons: the investigator fetches the missing evidence, the analyst re-ranks with the
feedback. After **3 refusals** the incident escalates to the NOC Shift Lead. The "Diagnosis verification" panel on the incident
page shows the playbook, each fact with its evidence, the investigator checklist and every rule result.

The playbook is checked in code rather than marked by a model (as the workshop does) because that is stricter, costs nothing and
gives the same answer every time.

## 4. Asking the field (pause and resume)

When the evidence rounds run out and the two leading causes still cannot be separated, the investigation does not guess. It
**pauses** (status `AWAITING_EVIDENCE`) and asks a field engineer for something specific, built from the two causes, for example
"Sweep the uplink with a spectrum analyser near the site ... Photograph the antenna, feeder cable and connectors". The model
investigator can also pause on its own with `request_evidence`.

Nothing is planned or routed while it waits. The engineer answers on the incident page, optionally after adding site photos
(SAM 3.1 + Muse Spark read them). The answer becomes a `field_report` evidence item, and the investigation resumes with
everything gathered so far. An on-site finding that backs the leading cause can stand in for its confirming check, and the
verifier says so ("stood in for by the field report"). The field is asked once; a second dead end goes to a person.

Demo: turn on **Diagnostics outage** in Demo controls. The diagnostic checks then time out, the data alone cannot settle the cause,
and the agent asks the field.

## 5. Engineer sign-off

A verified root cause can be **signed off** or **disputed** from the verification panel. A dispute needs a reason; it returns the
pending ticket and re-runs the investigation with the engineer's note. Sign-offs and disputes go into the ledger and the incident
report.

## 6. The living plan

The "Investigation plan" panel shows the current plan, each step's state, and a "Why it changed" history.

- The model writes and rewrites its own plan with `update_plan`. A step whose text matches a tool that ran is ticked for it.
- The orchestrator adds the steps it forces, each with a reason: more evidence from the analyst, a verifier refusal, a pause for the
  field, planning and routing.
- A failed tool call shows as a dropped step (struck through), so a diagnostics outage is visible at a glance.

## 7. Checkpoints and resume

`run_investigation` runs in phases (investigate, analyse, verify, plan) and saves a checkpoint at each phase. During the investigate
phase it also saves the investigator's whole conversation after every step.

If the Meta Model API fails (after retries and the fallback models), the incident escalates with a resumable checkpoint. It resumes:
- from the **"Resume from the ... step"** button on the escalation banner (`POST /api/incidents/{id}/resume`), or
- by itself two telemetry windows after the API is back (at most twice).

It continues from the saved step: evidence is not fetched again, and a verified diagnosis is not re-verified. The saved conversation
stays on the server; the incident API returns only where it stopped.

Limit: the demo database is reset when the server starts, so resume covers model API failures, not server restarts.

## 8. Measuring it

```powershell
py scripts\eval_investigation.py                  # offline rules engine
py scripts\eval_investigation.py --live           # Muse Spark agents with your key
py scripts\eval_investigation.py --severity 1     # mild faults, harder to tell apart
```

For each fault type on three cells it reports whether the diagnosis matches the injected fault (the simulator's ground truth, never
shown to the agents), whether the verifier passed it and on which attempt, playbook coverage and fact checks. The key number is
`wrong_but_verified`: a wrong diagnosis that got through the verifier. Offline (2026-10-30): 11 of 11 opened incidents diagnosed
correctly at severity 2 and 12 of 12 at severity 1, all verified on the first attempt, `wrong_but_verified` 0. Live on Muse Spark (2026-10-31, severity 2): 11 of 11 correct,
`wrong_but_verified` 0, 8 verified (4 on the first attempt); the 3 overshoot cases asked the field after 1-2 tool calls. Since then
`request_evidence` is refused until the investigator has made 5 data calls, used its budget, or a tool has failed.

## 9. Workshop mapping

| Legal-agent workshop | RAN Sentinel |
|---|---|
| Model picks one tool per turn, progress saved every turn | One tool per turn; checkpoint after every investigator step and every phase |
| `set_checklist` with a counter-evidence item | `set_checklist`, same rule |
| `update_plan` | `update_plan` plus orchestrator-added steps; "Investigation plan" panel |
| `record_fact` with an exact quote | Analyst key facts, each looked up in its evidence by code |
| Coverage against a hidden ground-truth checklist | Hidden per-cause playbook, checked in code |
| Memo rules in code | Root-cause rules in code |
| Claims check by a model | Claims check on Muse Spark 1.2 |
| `request_evidence` pauses; a person releases documents | Pause for field evidence; a field report resumes it |
| Three refused memos escalate | Three refused diagnoses escalate |
| Attorney sign-off | Engineer sign-off or dispute of the root cause |
| Agent Console | Agent console tab and the ledger |
| Offline tests with a fake model | Scripted model stand-in in `tests/test_llm_path.py` |
