# RAN Sentinel: 3-minute demo script

Record at 1440×900 in a browser at 100% zoom. Start the app with `start.bat`, with a Meta key in `.env`, and sign in to the console before recording. Open the customer app in a second tab. Times are targets. Leave about 10 seconds of slack.

## Before you record

- Restart the server so incident numbers start at RNS-2026-001.
- In Demo controls, check that **Red-team the first plan** is on.
- Have a site photo (JPG or PNG of an antenna or connector) ready on the desktop.
- Do one practice run, then restart again.

## Script

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00–0:15 | Network overview | Let the page sit. Point at the alarm counters and the status bar. | "Small US carriers run the same LTE network as the big three, with a fraction of the people. RAN Sentinel is an AI co-engineer for their operations centre, built on Meta's models. This is a simulated Seattle cluster on bands B66, B2 and B71." |
| 0:15–0:30 | Demo controls drawer | Open Demo controls. Pick SEA-RAN-001, **Capacity surge**, severity 2. Click **Create problem**. | "I'll create a problem live: a stadium crowd arrives on one cell." |
| 0:30–0:45 | Alarm monitor | Open Alarm monitor. Show the new alarms and acknowledge one. | "Within two telemetry windows the detector confirms it. It combines threshold rules, an Isolation Forest and a per-cell baseline, benchmarked on the open TelecomTS dataset." |
| 0:45–1:15 | Incident workspace, Agent console tab | Open the incident from the work queue. Show the workflow timeline, then the Agent console tab. | "Muse Spark 1.3 investigates with read-only tools: KPIs, alarms, M-Plane config, neighbours. Every call is logged here. It ranks four causes and cites evidence for each." |
| 1:15–1:40 | Plans tab | Show the blocked first plan and the safe revised plan. | "I red-teamed the first plan on purpose. Nine fixed safety rules and a digital twin blocked it and sent the reasons back. The planner revised it, and Muse Spark 1.2 reviewed it as an independent second opinion." |
| 1:40–2:00 | Decision panel | Click the microphone and say "Looks good, approve it." Show the highlighted button, then click **Approve**. | "Muse Voice Transcribe takes a dictated note. It only highlights a button; the engineer still decides. The change goes out over Open M-Plane as a confirmed-commit, so the radio rolls back by itself if the cell doesn't recover." |
| 2:00–2:20 | Second incident, Photos tab | Create a **Hardware fault** on SEA-RAN-020. When it routes to Field Operations, upload the site photo. | "Hardware goes to the field team. A technician's photo goes to SAM 3.1, which boxes the antenna, cable and connectors, and Spark reads it against the diagnosis." |
| 2:20–2:35 | Demo controls, then Incidents | Set **Meta API: all models down**, create a third problem, show it escalating with a brief. Set the switch back to none. | "If Meta's models are unavailable, it falls back through Spark 1.2 and 1.1, then escalates to a person. Muse Wonder writes escalation briefs and the shift handover from the whole ledger." |
| 2:35–2:50 | Customer app tab | Enter ZIP 98101. Ask "Is there an issue in 98101?" | "Customers see only confirmed, plain-language updates, filtered for internal details." |
| 2:50–3:00 | Safety ledger | Scroll the ledger. | "Every step, from evidence to action, is in the Safety Ledger, and outages are tracked against FCC Part 4. RAN Sentinel: faster fixes that are proven safe first." |

## If something goes wrong while recording

- **No incident after a minute:** check the status bar shows the telemetry clock moving. Raise the severity to 3.
- **Model call is slow:** keep talking over the Agent console; the timeline updates on its own.
- **Voice gives an empty transcript:** say the note again closer to the microphone, or type it.

## On-screen captions (optional)

1. Six Meta models, one job each
2. Unsafe plan blocked by fixed rules and a twin
3. Approved change with automatic rollback
4. Every step in the Safety Ledger

The FCC check is decision support, not legal advice. The network and the operator are simulated.
