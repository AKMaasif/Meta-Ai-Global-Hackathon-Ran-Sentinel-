# Customer voice assistant

The Northstar Connect assistant helps customers use the app through a conversation. Ask it to check a connection, open a page or prepare a complaint, then use follow-ups such as “report that,” “change it to home” or “read it back.” It remembers the topic within the current signed-in session while checking live demo data for current answers.

## From your microphone to a spoken reply

**Your voice → Meta transcription → conversation memory and Muse Spark/tools → customer review when needed → Gemini Kore speech → browser playback.**

| Part | Model or component | Responsibility |
|---|---|---|
| Capture | Browser microphone, echo cancellation and silence detection | Records until you pause and converts the recording to WAV. |
| Transcribe | Meta Muse Voice Transcribe 1.0 | Converts speech to text, with app vocabulary as keyword hints. |
| Understand | Muse Spark 1.3, with 1.2 as backup | Answers broader questions and uses tools for the customer's account and published network updates. |
| Keep context | Server-side `VoiceConversation` | Resolves simple follow-ups, remembers drafts and outcomes, and supplies recent dialogue and older notes to Spark. |
| Apply an action | Existing Care tools and confirmation checks | Opens pages and prepares changes. A complaint, credit or setting change waits for customer approval. |
| Speak | Gemini 3.8 Flash-Lite TTS; Gemini 3.8 Flash TTS as backup; Kore voice | Generates one complete spoken reply. The browser voice is a fallback if Gemini is unavailable. |

The browser applies navigation or draft updates before speaking the answer. During playback the microphone is off, so the assistant does not transcribe itself. Tap the orb to interrupt and start another listening turn. Closing the sheet stops playback and prevents a late response from navigating the app.

This is a turn-based pipeline rather than a streaming speech-to-speech model. Simple commands and remembered references avoid an extra reasoning-model call; broader questions and cloud speech generation can still take several seconds.

## What the assistant remembers

Memory belongs to the authenticated customer login, not to a history array supplied by the browser.

| Data | Stored as | Why it is kept |
|---|---|---|
| Recent dialogue | `messages`: latest 12 customer and assistant messages | Lets a follow-up refer to the previous question or answer. |
| Older context | `summary`: up to 1,600 characters of older customer statements | Preserves brief context after older turns leave the recent window. |
| Current issue | `issue`: symptom, saved place and customer details | Gives “report that” a specific meaning. |
| Current draft | `state.pending`: one proposal with an action ID; `state.turn`: turn counter | Supports review, correction, cancellation and later confirmation. |
| Action outcomes | `last_action` and up to eight `completed_actions` | Remembers what was sent, changed or cancelled, including report references. |
| Request retries | Up to 16 cached request IDs and responses | Prevents a retried confirmation from submitting the same action again. |

These records live in server RAM. Refreshing the page restores the conversation and, on the report page, the draft's fields. Closing the assistant keeps the conversation. **New conversation**, logout, server restart or simulator reset clears the relevant voice context. After 30 minutes without use, the next access clears expired memory and pending approvals.

Remembering a previous answer does not make it current information. Questions such as “is it still slow?” run fresh network tools. The demo uses one fictional customer account; separate login sessions have separate voice histories and pending approvals.

## A conversation from start to finish

> **Customer:** My data is slow at work.
>
> **Assistant:** Checks the connection at Work and explains the current result.
>
> **Customer:** Report that.
>
> **Assistant:** Opens a complaint draft using the remembered problem and location.
>
> **Customer:** Actually, change the location to home.
>
> **Assistant:** Updates the draft and creates a new approval ID.
>
> **Customer:** Read it back.
>
> **Assistant:** Reads the revised complaint.
>
> **Customer:** Yes, send it.
>
> **Assistant:** Submits that draft once and remembers its reference.

Setting changes work the same way. “Turn on Wi-Fi Calling” prepares a proposal. “Actually, turn it off instead” replaces it and requires fresh confirmation. If a reference is unclear, the assistant asks which problem or setting you mean.

## Customer control

- Reading account or network information and opening pages do not require a separate approval.
- Complaints, credits and setting changes remain proposals until the customer confirms in a later turn or taps Confirm/Send.
- Spoken agreement must refer to the proposal currently shown by that client. Questions and negated agreement do not authorize it.
- A correction invalidates the old approval ID. IDs are not reused across conversation or simulator resets.
- Cancel removes the pending proposal. Manual submission of an edited report retires its voice proposal first, preventing another spoken yes from submitting it again.
- The assistant has the app's allowlisted tools, not unrestricted control of the computer.

## Speech playback

Gemini generates the whole reply once, rather than separate clips for every sentence. The provider reads the returned audio format: WAV containers are decoded as WAV, while raw PCM uses its reported sample rate. Short fades soften clip boundaries without cutting off words. Interrupting cancels playback, releases audio resources and ignores stale responses.

Only the answer text goes to TTS; it can include details the customer provided. Stage directions are kept out of the transcript because Gemini 3.8 reads it verbatim. The original WAV-format defect and its verification are described in the [audio redesign report](VOICE_AGENT_REDESIGN.md).

## Setup and verification

Add your own `MODEL_API_KEY` and `GOOGLE_API_KEY` to `.env`, then restart the app. The default speech settings are `TTS_MODEL=gemini-3.8-flash-lite-tts`, `TTS_FALLBACK_MODEL=gemini-3.8-flash-tts` and `TTS_VOICE=Kore`. Keys stay on the server. Without Meta access, typed requests use the offline rules engine; without Google access, the browser can read replies aloud.

- `python scripts/check_voice_agent.py` checks a scripted conversation and Gemini speech through the configured providers. `--audio path.wav` also checks transcription. These calls can consume API credits.
- `python -m pytest tests/test_voice_memory.py tests/test_voice_agent.py -q` checks voice and memory behavior offline.
- `node scripts/check_voice_ui.js` and `node scripts/check_voice_memory_ui.js` check browser behavior on an isolated offline demo. They create fictional reports and change settings; see the [memory verification instructions](VOICE_CONVERSATION_MEMORY.md#verification).
- On macOS, `python scripts/check_safari_ui.py` checks the actual Safari browser, including synthetic audio recording and WAV conversion. It needs the optional `selenium` package and Apple's Safari remote automation enabled. The [verification record](LOCAL_INSTALL_VERIFICATION.md) links the successful hosted run.

Live Meta follow-ups, speech generation and a transcription round trip have been checked. Recognition accuracy and complete conversation latency on real customer devices have not been benchmarked. Memory is bounded and session-based, rather than permanent recall.

## Where the code lives

| File | Role |
|---|---|
| `frontend/shared/ui.js` | Microphone recording, silence detection and WAV conversion |
| `frontend/connect/app.js` | Voice sheet, transcript, draft controls, restoration, navigation and playback |
| `backend/app/main.py` | Authenticated voice, memory, speech and confirmation endpoints |
| `backend/app/voice_memory.py` | Conversation state, references, corrections, expiry, session isolation and retry handling |
| `backend/app/care.py` | Customer tools, scoped pending actions and the Muse Spark conversation loop |
| `backend/app/providers.py` | Meta transcription/model calls and Gemini speech/audio decoding |

The [conversation memory design](VOICE_CONVERSATION_MEMORY.md) documents the state boundaries, API and recorded test results in more detail.
