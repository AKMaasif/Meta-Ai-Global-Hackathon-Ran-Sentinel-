# Customer voice agent

A hands-free assistant in the Northstar Connect app. The customer talks; the agent answers out loud and operates the app for them
("check my data connection at the gym", "report the problem", "open my bill"). Meta models do the listening and the thinking;
Gemini TTS does the speaking, because Meta has no text-to-speech model yet.

Code: `frontend/connect/app.js` (`voice` module, orb UI), `frontend/shared/ui.js` (`listen`, voice activity detection),
`backend/app/care.py` (`Care.concierge(voice=True)`, `VOICE_TOOLS`, `VOICE_SYSTEM`, `_voice_fast`), `backend/app/providers.py`
(`GeminiSpeech`), `backend/app/main.py` (routes). Tests: `tests/test_voice_agent.py`. Live check: `scripts/check_voice_agent.py`.

## 1. One turn

```
mic -> UI.listen (records until the speaker pauses, 16 kHz WAV)
    -> POST /api/public/voice          Muse Voice Transcribe 1.0, with app words as keyword hints
    -> POST /api/care/voice/turn       Care Concierge on Muse Spark 1.3 with customer-scoped tools
    -> POST /api/care/voice/speak      Gemini TTS, one request per sentence, in parallel, played in order
    -> the browser applies UI actions  (open a page, refresh)
    -> listens again                   until the customer says "bye" or closes the sheet
```

The orb sheet shows the live workflow ("Listening", "Understanding", the tool steps, "Speaking"), a Confirm card for anything that
needs a yes, a text box ("Ask me anything") and suggestion chips. Speaking over the agent interrupts it.

## 2. What it can do

All the Care Concierge tools (service at saved places, signal, ZIP check, suggestions, account, credits, `propose_action`), plus:

| Voice tool | Effect |
|---|---|
| `test_my_connection` | Signal and network status at a saved place; opens the Network page |
| `open_page` | Shows Home, Network, Account, Bill, Help, Notifications, Shop or Report |
| `get_notifications` | Reads the latest notifications |
| `confirm_pending` / `cancel_pending` | Carries out or drops an action proposed in an earlier turn |

## 3. Safety

- A change (setting, credit, problem report) is only **proposed**. It happens on a short spoken "yes" (8 words or fewer) in a
  **later** turn than the proposal, or a tap on Confirm. The model cannot confirm in the same turn. The typed assistant has no
  `confirm_pending` tool; there the customer taps Confirm.
- Tools see only this customer's account and engineer-approved network updates. Cell IDs and technical parameters never reach
  the customer.
- The TTS receives only the answer text. Never put instructions in that text: the TTS reads every word aloud.

## 4. Speed

- **Instant path:** short yes/no answers, "open my bill" and exact "test my connection at home" commands are handled without a
  model call (`by: "instant"`). Everything else goes to Muse Spark.
- **Sentence streaming:** the answer is split into sentences, all are sent to Gemini at once, and playback starts with the first.
- **Lite voice model:** `TTS_MODEL=gemini-3.8-flash-lite-tts`, fallback `gemini-3.8-flash-tts`, voice `Kore`.
- If Gemini is not set up or fails, the browser's own speech voice reads the answer.

## 5. Setup

Put `GOOGLE_API_KEY=` in `.env` (a Gemini API key from Google AI Studio). `py scripts\check_google_tts.py` checks which TTS models
the key can use; `py scripts\check_voice_agent.py` runs a scripted conversation through the real pipeline and saves the spoken
replies as WAV files. Without a Google key the agent still works and speaks with the browser voice.

## 6. Limits

- Real-speech accuracy and end-to-end latency on a real phone are not yet measured.
- Gemini TTS is a Google service; the customer's words are never sent to it, only the agent's answer.
