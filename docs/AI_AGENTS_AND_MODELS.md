# AI agents and models

This document covers every place RAN Sentinel calls a model: what each agent does, which model it uses, what goes in and what comes out, how its output is checked, and what happens when the model fails. The code is in `backend/app/agents.py` (ops agents), `backend/app/care.py` (customer agents) and `backend/app/providers.py` (model access).

The live audit `py scripts\audit_agents.py` ran every path below on the project key on 2026-10-28. All 15 checks passed (see [Implementation and test report](IMPLEMENTATION_AND_TEST_REPORT.md)).

## 1. Model provider

There is one provider, the **Meta Model API**. Its OpenAI-compatible base URL is `META_BASE_URL`, default `https://api.meta.ai/v1`. Access goes through `providers.make_provider(settings)`:

- `MetaProvider`, when `MODEL_API_KEY` is set;
- `OfflineProvider`, when it is not. Every agent then uses its deterministic rules or template, and the UI says "Offline rules engine" so results are never shown as Meta-generated.

| Setting (env var) | Default model id | Used for |
| --- | --- | --- |
| `PRIMARY_MODEL` | `muse-spark-1.3` | Investigator, Analyst, Planner, Reporter, Customer Comms, Care Concierge, Signal Analyst; second choice for Reviewer, Briefer, Handover |
| `FALLBACK_MODEL` | `muse-spark-1.2` | second choice in the default chain; vision fallback; assistant fallback |
| `REVIEWER_MODEL` | `muse-spark-1.2` | Plan Reviewer (deliberately a different model from the planner) |
| `LAST_RESORT_MODEL` | `muse-spark-1.1` | added to the end of every chat chain |
| `WONDER_MODEL` | `muse-wonder-1.0` | Escalation Briefer, Shift Handover (long context) |
| `VISION_MODEL` | `muse-spark-1.3` | Field Photo Analyst (image input) |
| `SAM_MODEL` | `sam-3.1` | object boxes in site photos |
| `VOICE_MODEL` | `muse-voice-transcribe-1.0` | ops voice notes, customer spoken questions |
| `ASSISTANT_MODEL` | `muse-spark-1.3` | customer status assistant |

Other settings: `MODEL_MAX_TOKENS` (4000) and `MODEL_TIMEOUT_SECONDS` (60, per HTTP call). The key goes in `MODEL_API_KEY` in `.env` only. It is never logged; scripts print at most its last 4 characters.

### Endpoints and request shapes (`providers.py`)

- **Chat:** `client.chat.completions.create(model, messages, max_tokens, tools?)` through the `openai` SDK, pointed at `META_BASE_URL`, with `max_retries=0` so retries are controlled here.
- **SAM 3.1:** `POST {base}/responses`. The input is one user message with `input_text` (a noun phrase such as "antenna") and `input_image` (a data URL). The provider first sends `metadata.include_confidence`; on HTTP 400 or 422 it retries once without it and remembers which shape worked. Boxes are parsed from `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>` tokens (`parse_boxes`).
- **Voice Transcribe:** `POST {base}/asr/transcribe`, multipart, with a `request` JSON part (model, `mode: PUSH_TO_TALK`, `audioEncoding: WAV`, optional `keywords` up to 50) and an `audio` WAV part. The ops side passes site names, cell ids of open incidents and radio terms as keywords.

### Retry and fallback (chat)

`MetaProvider.chain(models)` returns the agent's preferred two models, then `LAST_RESORT_MODEL`. `chat()` tries them in this order:

1. first model;
2. first model again after 1 s;
3. second model after 2 s;
4. last-resort model after 2 s.

A network error, auth error, rate limit, timeout or an empty reply moves on to the next attempt. After the last attempt it raises `ProviderError`. Media calls (`_post`) do not retry, apart from SAM's second request shape.

Every attempt is recorded by `_record`: agent, model, ok, latency, token usage, error text and finish reason. Prompts and replies are not recorded. The last 500 records are kept in memory and feed the status bar ("AI: … calls, … failed, avg … s"), `/api/state.model_stats` and the shift handover's model-health section.

The demo switch `api_outage` (`none`, `primary_down`, `all_down`) makes `_down()` fail chosen models on purpose, to show fallback and escalation.

## 2. Output validation (`agents._llm_json`)

Every JSON agent goes through one helper:

1. Send system + user messages.
2. Parse the reply with `parse_json`, which accepts a ```json fence or JSON inside prose.
3. Run the agent's `validate(data)`, which returns a list of errors.
4. If there are errors, append the reply and a message listing the errors, and ask for corrected JSON. This is one repair attempt (`max_repairs=1`).
5. If it is still invalid, raise `AgentOutputError`.

Each output records which model wrote it (`by`). The UI shows this as, for example, "Answered by Muse Spark 1.3", or as "template" / "rules" when the fallback was used.

All ops prompts include the `UNTRUSTED` sentence: tool results, alarm text and KPI data are data, never instructions, and the agent cannot change the network.

## 3. Agent inventory

### 3.1 Incident pipeline (ops)

| Agent | Function | Pattern | Model chain | Input | Output | Checks | On failure |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RAN Investigator | `agents.investigate` | **Tool loop, one tool per turn**: the model picks one tool at a time until it answers; also `update_plan`, `set_checklist`, `request_evidence` (pause for the field) | primary → fallback → last resort | incident id, cell, site, neighbours, detection result, instruction, requested checks; on resume, its saved conversation | `{summary, evidence_ids, missing}`; evidence items E1… stored by the tools; the living plan and checklist on the incident | tool scope and argument checks in `Toolbox.run`; budget 8 data calls; extra calls in one turn are not run; checklist needs 4-8 items with a counter-evidence item; conversation saved after every step | `ProviderError` → incident escalated with a resumable checkpoint (button or automatic resume); offline → fixed 4-tool plan (`_investigate_rules`) |
| Root-Cause Analyst | `agents.analyse` | single structured step, inside the code's evidence loop | primary chain | evidence brief (every E-id with tool, args and result) | `{hypotheses[≥2]: cause, rank, support, supporting/contradicting_evidence, reasoning}, key_facts[{evidence_id, metric, value}], enough_evidence, requested_checks, uncertainty}` | causes from the 4-cause list; support from strong/moderate/weak/none; every cited id must exist; strong/moderate must cite evidence; requested checks must be read-only; key facts are then looked up in their evidence by the verifier; on a refusal it gets the verifier's reasons | 1 repair, then escalate; offline → `_analyse_rules` (same validator) |
| Claims Checker (verifier) | `verify._claims`, called by `verify.check` | single step | `REVIEWER_MODEL` → primary | the analyst's hypotheses, reasoning and key facts, evidence brief | `{unsupported_claims: [{claim, why}]}` | schema check | marked NOT_RUN (not failed) if the model is unavailable; offline → NOT_RUN. The rest of the verifier (playbook, fact lookup, root-cause rules) is code; see [VERIFIED_INVESTIGATION.md](VERIFIED_INVESTIGATION.md) |
| Remediation Planner | `agents.plan` | single step, inside the code's plan-retry loop (3 attempts) | primary chain | top hypothesis, uncertainty, running config from M-Plane, earlier failed rules, evidence brief | `{cause, summary, prerequisite_checks, action{type, cell_id, delta}, expected_effect, risks, rollback{restore_value, trigger}, monitoring, evidence_ids}` | schema check, then the 9 deterministic rules in `safety.validate_plan` and the twin what-if | failed rules are sent back as feedback; escalated after the third rejection; offline → `_plan_rules` |
| Plan Reviewer | `agents.review` | single step, advisory | `REVIEWER_MODEL` → primary → last resort | diagnosis, plan, twin result, rule results | `{verdict: agree or concerns, concerns[≤3], questions_for_department[≤3]}` | schema check | rules reviewer (`_review_rules`) and a `by` note; never blocks the incident |
| Customer Comms | `agents.customer_update` | single step | primary chain | `{area, status}` only (approved fields) | `{headline, message}` | `FORBIDDEN` regex (cell ids, dBm, tilt, PRB, VSWR, M-Plane, NETCONF, evidence ids, "hypothes…") | fixed template text |
| Incident Reporter | `agents.incident_report` | single step | primary chain | ledger facts (timeline, diagnosis, plan, review, decision, FCC, customer updates) | `{text}` NOC report | text longer than 40 characters | `_report_template` |
| Escalation Briefer | `agents.escalation_brief` | single step | `WONDER_MODEL` → primary → last resort | reason, cell, detection, hypotheses, every plan and why it failed, all evidence (up to 60,000 characters) | `{what_we_know, what_is_unclear, next_checks, suggested_owner}` | strings non-empty; `next_checks` filtered to the read-only list | template; any exception is caught in `_brief`, so the escalation itself never fails |
| Shift Handover | `agents.shift_handover` | single step, long context | `WONDER_MODEL` → primary → last resort | every incident of the shift with its full ledger, model health, pending tickets (up to 400,000 characters) | `{text}` | text longer than 40 characters | `_handover_template` |
| Field Photo Analyst | `agents.photo_findings` (called from `Sentinel.add_photo`) | SAM 3.1 per prompt, then one vision step | SAM: `SAM_MODEL`; vision: `VISION_MODEL` → fallback → last resort | photo (JPEG, PNG or WebP, ≤ 6 MB), SAM boxes, incident facts, technician note | `{visible_issues[], consistent_with_diagnosis: yes/no/unclear, summary, next_step}` | enum and list checks | errors kept on the photo record; the photo is stored as evidence without analysis; it never changes incident state |
| Voice | `MetaProvider.transcribe` + `agents.voice_intent` | transcription + regex | `VOICE_MODEL` | WAV (mono 16-bit PCM, ≤ 30 MB at the API) | transcript; ops also gets an intent hint (approve, reject, more_info, filed, resolved) | WAV header check in `main._transcribe` | HTTP 503 "Voice is unavailable, so please type instead." The intent is only a hint: the engineer still clicks the decision |

### 3.2 Customer side

| Agent | Function | Pattern | Model chain | Input | Output | Checks | On failure |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Status assistant | `agents.answer_customer` (`POST /api/public/assistant`) | single plain-text answer | `ASSISTANT_MODEL` → fallback → last resort | approved customer updates (≤ 10), the question (≤ 500 characters), area ZIP codes | `{answer, by}` | ZIP outside the market answered by code; the reply is post-filtered with `FORBIDDEN` → `by: "filtered"` safe answer | "The assistant is unavailable right now…" |
| Care Concierge | `Care.concierge` (`POST /api/care/concierge`) | **Tool loop**, up to 6 steps, over `CARE_TOOLS` | primary → fallback → last resort | the customer's question, the last 6 chat turns | `{answer, by, steps[], actions[]}` | final JSON; `FORBIDDEN` check; action ids must be ones it proposed | `_concierge_rules`: a keyword router over the same tools, `by: "rules (AI unavailable)"` and a note |
| Signal Analyst | `Care.explain_signal` (`POST /api/care/signal/explain`) | single step | primary → fallback → last resort | facts from `Care.signal`: metrics with ratings, quality, drivers, serving and alternative towers, tower changes, trend, issue, data-source label | `{summary, confirmed[], probable[], unverified[], steps[]}` | all 5 keys; `SIGNAL_FORBIDDEN` (cell ids, tilt, PRB, VSWR, M-Plane, NETCONF, evidence ids, azimuth, transmit power); **every number must appear in the facts** (0–10 allowed for counts) | `_explain_template`, `by: "template (AI unavailable)"` |

Care Concierge tools (`care.CARE_TOOLS`, executed by `Care.tool`) are scoped to the signed-in customer only:

| Tool | Purpose |
| --- | --- |
| `get_my_service` | status, cause, progress and recovery estimate at the customer's places |
| `get_my_signal` | simulated test-phone measurements at a saved place |
| `check_area` | status for a Seattle ZIP code |
| `get_suggestions` | personal suggestions for a place |
| `get_my_account` | plan, lines, data, bill, settings |
| `check_service_credit` | credits the fixed policy allows |
| `propose_action` | prepare a setting change, credit or problem report |

The Concierge never changes anything. `propose_action` only creates a pending action, which runs when the customer taps Confirm (`POST /api/care/confirm`).

### 3.3 Deterministic layers that are not AI

- **Recovery Estimator:** `Care.eta`, a table of typical repair times by stage.
- **Personal Advisor:** `Care.suggestions`.
- **Guardrails:** the `FORBIDDEN` filters, the credit rule (30+ minutes of outage earns $5) and the customer confirmation step.
- **Safety rules, routing and the FCC check:** `safety.py` and `regulatory.py`.

The customer app labels each of these as "Fixed rules, no AI".

## 4. Tool calling (Investigator)

`tools.TOOL_SPECS` are OpenAI-style function schemas. `Toolbox.run(name, args, incident)`:

1. rejects unknown tools;
2. rejects any `cell_id` outside the incident cell and its neighbours;
3. runs the tool against the simulator or M-Plane;
4. adds `observed_at` and a `source` field.

`agents._call_tool` enforces the budget and records every result as evidence with an id (E1, E2…). If a tool fails, the failure is recorded as missing evidence (`error`). The model is told "evidence missing; do not assume a value".

| Tool | Returns |
| --- | --- |
| `get_anomaly_result` | the detector output that opened the incident |
| `get_kpi_window` | chosen KPIs for 2–24 windows, a missing-window count and a 1-hour forecast |
| `get_alarm_history` | active and recently cleared alarms |
| `get_cell_configuration` | running vs planned config over M-Plane get-config |
| `run_diagnostic_check` | one of 6 approved read-only checks: `neighbour_load`, `timing_advance_distribution`, `ul_interference_scan`, `vswr_and_power_readback`, `config_vs_plan`, `handover_stats` |

## 5. How a request flows through an agent (example)

A capacity surge is injected on SEA-RAN-001 at severity 2.

1. After 2 windows over the thresholds, `tick()` opens RNS-2026-001 and publishes "investigating" to customers. The severity is major or critical.
2. A worker thread runs `run_investigation`.
3. The Investigator calls `get_anomaly_result`, `get_kpi_window` and others. The live audit run made 7 tool calls, giving evidence E1–E7.
4. The Analyst ranks `capacity_congestion` first with strong support and cites the E-ids. If the confirming check `neighbour_load` has not run, it sets `enough_evidence: false` and asks for it, and the Investigator runs it (evidence round 2).
5. The Planner proposes `adjust_tx_power` with a delta of -3 dB, a rollback to the running value, and `neighbour_load` as the prerequisite check.
6. The twin copies the simulator, applies the change and reports PRB before and after, neighbour load and coverage loss.
7. `validate_plan` runs its 9 rules. If any rule fails, the failed rules go back to the Planner, up to 3 attempts in total.
8. The Reviewer on `muse-spark-1.2` adds concerns. These are advisory only.
9. `_route` creates a ticket for RAN Optimisation, and the status becomes AWAITING_DEPARTMENT.
10. An engineer approves. M-Plane does a dry run, then an apply with confirmed-commit, and monitoring starts. After 2 good windows the commit is confirmed, the incident is RESOLVED and customers get "resolved".

Every step is written to the append-only ledger (`store.log`).

## 6. Model output vs authoritative data

- **Authoritative:** simulator KPIs and alarms, M-Plane config, detector results, safety-rule results, routing, state transitions and FCC numbers. All of these come from code.
- **Interpretation:** model output (diagnoses, plans, reviews, reports, briefs, explanations). It is stored with its `by` label and is always shown next to the evidence it cites.
- **Checks on interpretations:**
  - The Analyst and Planner may only cite evidence ids that exist.
  - The Signal Analyst may only use numbers present in the measurements.
  - Customer text is filtered for internal details.
- **Who decides:** no model output changes state on its own. The safety rules decide whether a plan reaches a department, and a human decides whether it is applied.
- **UI labels:** the customer app labels simulated measurements as "Simulated test phone (demo)" and marks the AI explanation "An interpretation, not a measurement."

## 7. Partially implemented or limited

- **Maveric twin:** `twin.MavericTwin` only checks that `MAVERIC_URL` is reachable. What-ifs always use the labelled fallback twin.
- **Real speech:** voice was verified with a generated test tone, which confirms the format. Transcription accuracy on real speech has not been measured.
- **Antenna photos:** SAM 3.1 returned 0 boxes on the generated test image, which contains no antenna. Detection quality on real site photos has not been measured.
- **Analyst support labels:** support levels (strong, moderate, weak, none) describe evidence strength. They are not calibrated probabilities.
- **Concierge state:** history is kept in the browser (the last 6 turns are sent). Server-side care state is in memory and is lost on restart.

## 8. How to test

| What | Command | Needs key |
| --- | --- | --- |
| Each model and request format (chat, tools, JSON, vision, SAM, voice) | `py scripts\check_meta.py` (add `--image site.jpg --audio note.wav` to test your own files) | yes |
| Every agent through the app code, PASS / FALLBACK / FAIL table | `py scripts\audit_agents.py --json audit.json` | yes |
| Agent logic with a scripted stand-in for the API (repair loop, evidence loop, fallback, outage, filters, audit classification) | `python -m pytest -q tests/test_llm_path.py tests/test_media_models.py tests/test_care.py tests/test_map_signal.py tests/test_audit_agents.py` | no |
