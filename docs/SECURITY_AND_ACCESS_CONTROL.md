# Security and access control

RAN Sentinel is a local demo, not a production service. This document states what each control does in the code, and where a control is partial or missing. Status:

- **Implemented:** in the code and tested where noted.
- **Partial:** present but limited.
- **Missing:** not in the code.

## 1. Demo entry and sessions

The local evaluation build intentionally offers both roles without credentials through `POST /api/demo/start` with a validated portal. This creates a normal role-scoped session cookie, not a production identity. Anyone who can reach the app can choose either role. This is appropriate only for fictional local data, not a public private-account service. The open demo does not bypass customer confirmation or engineer approval.


| Control | Status | Detail |
| --- | --- | --- |
| Sign-in | Implemented | `POST /api/login` with `{email, password, portal}`. Optional private accounts per portal from `.env`: `OPS_EMAIL` / `OPS_PASSWORD` and `CUSTOMER_EMAIL` / `CUSTOMER_PASSWORD`. Compared with `secrets.compare_digest` (`main._matches`). |
| Wrong portal | Implemented | Right credentials on the wrong sign-in page return `403` with a pointer to the right app, never a session (tested in `tests/test_login.py`). |
| Session token | Implemented | `secrets.token_urlsafe(24)`, stored in the in-memory `sessions` dict with its portal (a customer token in the ops cookie, or the reverse, gets 401; tested), sent as cookie `rs_ops` or `rs_connect` with `HttpOnly` and `SameSite=Lax`. |
| Logout | Implemented | `POST /api/logout` removes both sessions and cookies. |
| Session expiry | Missing | Sessions last until logout or server restart. |
| Secure cookie flag | Missing | Not set, because the app is served over plain HTTP on 127.0.0.1. Must be added if the app is ever served over HTTPS. |
| Password storage | Partial | Plain values from `.env`, not hashes. Passwords default to empty; empty passwords cannot authenticate. Demo entry does not depend on these optional private settings. Configuring a private password does not disable open demo access. |
| Rate limiting or lockout | Implemented | 5 wrong passwords from one address lock sign-in for 5 minutes (`429`). In memory, per client address (tested in `tests/test_security.py`). |
| CSRF protection | Partial | Only `SameSite=Lax` and JSON bodies; there are no CSRF tokens. |

## 2. Authorization

There are two roles, and each route declares one of them as a FastAPI dependency:

- `ops_user` needs a valid `rs_ops` session;
- `customer_user` needs a valid `rs_connect` session.

There is no finer role model. The one ops user acts for every department (RAN Optimisation, Field Operations, Regulatory Compliance…). The decision records the name sent in the request body (default "Sarah Chen"), and that name is not verified.

| Boundary | How it is enforced | Tested |
| --- | --- | --- |
| Customer cannot read operations data | every ops route depends on `ops_user`; a customer cookie gets 401 on `/api/state`, `/api/cells/{id}`, `/api/alarms`, `/api/ledger` | `test_map_signal.py::test_customer_cannot_call_ops_endpoints` |
| Ops cookie does not grant customer routes | customer routes depend on `customer_user` (separate cookie) | by code review |
| Models cannot change the network | agents get read-only tools only. A change happens only after `POST /api/tickets/{id}/decide` with `approve`, then passes through M-Plane dry run, confirmed-commit and automatic rollback | `test_safety.py`, `test_mplane.py`, `test_scenarios.py` |
| Plans outside policy never reach a department | `safety.validate_plan`: 9 fixed rules (allow-list, step ±3 dB or ±2°, bounds 37–46 dBm or 0–12°, cause fit, evidence cited, read-only checks first, rollback, sandbox impact) | `test_safety.py` |
| Investigator stays on its incident | `Toolbox.run` rejects any `cell_id` outside the incident cell and its neighbours; `incident_id` must match | `test_llm_path.py` |

## 3. Customer data isolation and the two maps

The demo has **one** customer account, the fictional subscriber in `care.SUBSCRIBER`. Isolation between different customers is therefore not exercised. What is enforced is that the customer sees only their own places and only published, customer-safe information:

1. **Place scoping:** `/api/care/map`, `/signal`, `/signal/explain` and `/phone` take a `place` id. `Care._place` accepts only the customer's own saved places (home, work, gym); anything else returns 400.
2. **Server-side radius:** `Care.map` returns only towers within `MAP_RADIUS_KM` = 3 km of the customer's test phone. The browser never receives the rest of the network.
3. **Field allow-list:** a customer tower record has only `key, name ("Northstar tower · <site>"), lat/lon (4 decimals), technology, bands, distance, coverage, status, serving, alternative`. No cell ids, transmit power, tilt, KPIs or alarms (tested).
4. **Published status only:** a tower shows `problem` or `unavailable` only after engineers have published a customer update for that area (`Care._public_status`). Internal alarms and unconfirmed diagnoses never reach the customer.
5. **Movement limit:** the simulated phone cannot move more than `PHONE_RADIUS_KM` = 1.5 km from the place (400 otherwise, tested).
6. **Text filters:** all customer-facing model text is checked. `agents.FORBIDDEN` covers status updates, the assistant and the Concierge; `care.SIGNAL_FORBIDDEN` covers the Signal Analyst. They block cell ids, technical parameters, internal system names and evidence ids.

The **ops map** uses `/api/state`, which needs the ops session, and shows every cell, sector, power, tilt and KPI. The customer app never calls it.

## 4. Model and external API integration

| Control | Status | Detail |
| --- | --- | --- |
| API key location | Implemented | `MODEL_API_KEY` in `.env` at the project root. `.env` is in `.gitignore`. So are `meta api key.txt`, `*api key*.txt` and `*api_key*.txt`, added in this change so a plain-text key file next to the project is not committed by accident. |
| Key never reaches the browser | Implemented | All model calls are server-side in `providers.py`. The front ends only call `/api/*`. |
| Key never logged | Implemented | `_record` stores agent, model, ok, latency, usage and error, never the key or prompts. `check_meta.py` and `audit_agents.py` print only the last 4 characters; `audit_agents.redact` removes the key and any long token-like string from error text (tested). |
| Prompt injection | Partial | Agent prompts append `agents.UNTRUSTED`, which tells the model that tool results, alarm descriptions and KPI data are data, not instructions (also used by the Signal Analyst). Outputs are schema-checked, evidence citations are verified and customer text is filtered. A model could still be misled into a wrong but well-formed diagnosis; that is why the safety rules and a human decision sit after it. |
| Customer data sent to Meta | Partial | Customer questions go to `ASSISTANT_MODEL` (default `muse-spark-1.3`). The cheaper `-contributor` variants, where Meta may train on inputs, are deliberately not the default (`.env.example`). |
| Outbound hosts | — | the Meta Model API (`META_BASE_URL`); optional `MAVERIC_URL` (RF what-if); map tiles from `*.basemaps.cartocdn.com`, loaded by the browser. |

## 5. Input validation and error handling

- **Request bodies:** typed with pydantic models; malformed bodies get 422.
- **Uploads:**
  - Photos must be JPEG, PNG or WebP, between 1 byte and 6 MB.
  - Voice must be a WAV with a RIFF/WAVE header, at most 30 MB.
  - Photos are also checked by their first bytes, so a file labelled JPEG must really be one.
  - Field documents (CSV, PDF, DOCX, TXT) are at most 10 MB. A DOCX whose text part unpacks to over 20 MB (zip bomb) or that
    contains a DTD (billion laughs, XXE) is refused. The file name is reduced to its last part without control or quote
    characters, and the file is served back as a download with a fixed content type and `nosniff`.
- **Response headers:** every response has `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
  `Referrer-Policy: same-origin`.
- **Bad input from the browser:** a `ValueError` from the domain code is mapped to 400 with a plain message, and unknown ids get 404.
- **Model failures:** a model failure never crashes a request. Every agent has a fallback, and the investigation escalates on any unexpected exception (`run_investigation`).
- **Customer text:** customer free text (questions, report details) is trimmed to 500 characters for Concierge questions and history (`Care.concierge`). It is passed to the model as a user message; there is no separate injection filter on input, only the `FORBIDDEN` filter on output.

## 6. Audit logging

- **Ledger:** every incident step is written to the append-only `ledger` table with wall-clock and simulated time, actor and payload. That covers detection, tool calls, rankings, plan validation, twin results, reviews, routing, decisions with the user's name and note, M-Plane operations, rollbacks, customer updates and photos. It is shown on the Safety ledger page.
- **Model calls:** recorded in memory (last 500), without prompts.
- **Gaps:** sign-ins, failed sign-ins and customer actions are not written to the ledger.

## 7. Known gaps (summary)

- **Accounts:** one account per role, no hashing, no expiry and no CSRF tokens. The decision "user" field is trusted.
- **Transport:** no HTTPS or Secure cookie. The app binds to 127.0.0.1 only (`run.py`); do not expose it on a network as is.
- **Persistence:** sessions and customer-care state are in memory.
- **Multi-customer isolation:** not testable with one demo subscriber.
- **Prompt injection:** mitigated by structure (schemas, citations, filters, deterministic safety rules, human approval), not prevented.

## 8. Security test run (2026-10-31)

A live attack run against the app (FastAPI test client, offline engine) made 34 checks: every API route without a session,
wrong portal, unknown portal, session token swap between portals, cookie flags, 30 wrong passwords, logout, upload path
traversal, header injection in file names, .exe/.html/.svg uploads, over 10 MB, a GIF labelled JPEG, a 400 MB DOCX zip bomb,
billion laughs, XXE, a malformed PDF, XSS in file names, a prompt-injection file, unknown ids, static-file traversal to `.env`,
customer access to evidence upload and approvals, and security headers.

The first run failed 9: a customer session token opened the ops API (and the reverse), an unknown portal name crashed sign-in
(500), no lockout, file names kept `../` paths, the DOCX zip bomb was read in full, billion laughs and XXE crashed (500), a
GIF passed as a JPEG, and there were no security headers. All 9 are fixed and covered by `tests/test_security.py`; the re-run
passed 34 of 34. Bandit found no other issue in the app code, and pip-audit found no known vulnerable dependency. A git
history scan found no keys (only obvious test placeholders).

Not covered: a prompt-injection file against the live model. The Field Document Analyst is told that file text is data, its
output is display and evidence only, and it cannot change the network; an engineer who uploads a misleading file can still
mislead the diagnosis, which is why the safety rules and a human approval come after it.
