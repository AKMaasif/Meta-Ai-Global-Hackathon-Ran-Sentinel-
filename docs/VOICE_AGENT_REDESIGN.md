# Voice agent architecture and playback

Updated 4 November 2026. The submitted runtime uses Meta models for transcription and reasoning, and installed local browser/OS voices for spoken output. The earlier cloud-TTS integration and its diagnostic script have been removed. Earlier listening results for that integration do not establish the sound quality of this revision.

## Current workflow

1. A customer opens the login-free sample-data demo and taps Ask.
2. Typed questions enter the conversation directly. With Meta access, the microphone records until a pause, converts the recording to mono WAV, and sends it to Meta Muse Voice Transcribe.
3. Server-side memory resolves simple references such as "report that". Broader questions go through Muse Spark with scoped, allowlisted tools.
4. Reading information and navigating pages can happen immediately. Settings, credits and complaints become visible proposals requiring later explicit confirmation. Corrections replace the proposal ID; Cancel retires it.
5. The complete written answer is displayed before local speech begins. Only installed English voices explicitly marked local by the browser are eligible. No reply text goes to a cloud TTS service.
6. The microphone stays off during speech. Tapping the orb interrupts and begins a new listening turn. Closing the sheet stops speech and prevents late replies from navigating.

This remains a turn-based assistant, not a streaming speech-to-speech model or automatic barge-in system. Meta's recording-upload endpoint is sufficient for the current capture design; realtime WebSockets are not required for this change.

## Local speech and missing voices

`frontend/shared/local-speech.js` discovers local English voices, waits briefly for an asynchronous voice list, and speaks one whole response in one utterance. Cancellation resolves outstanding discovery/playback promises. Errors or unavailable voices leave the full written answer visible. Online-only voices are excluded. The Reply voice selector offers installed voices and Text only; names, gender and sound depend on the device.

Speech playback does not provide offline microphone transcription. Without Meta access, use typed input to test tools, memory, complaint drafting and approvals.

## Verification

- `python scripts/check_local_install.py`: temporary no-key app; both demo roles, assets, access boundaries and one investigated fault.
- `node scripts/check_local_speech.js`: synthetic local/remote voice lists, delayed discovery, interruption, Text only and speech-error fallbacks.
- `node scripts/check_voice_ui.js`: whole-response utterances and approval, cancellation and stale-response behavior using browser speech test doubles.
- `node scripts/check_voice_memory_ui.js`: contextual drafts, corrections, refresh, exact approval IDs, retry protection and separate demo sessions.
- `python scripts/check_voice_agent.py`: configured Meta/offline conversation; `--audio path.wav` additionally makes a Meta transcription call. It does not test physical speakers.

Browser scripts modify sample state; use an isolated offline server and set `BASE_URL` when necessary. Current results and platform limits are in [Local installation verification](LOCAL_INSTALL_VERIFICATION.md). The owner confirmed the revised microphone/listening flow on Windows on 4 November. Physical microphone and speaker checks on macOS and Linux remain unverified.

References: [Meta speech-to-text](https://dev.meta.ai/docs/speech-to-text), [Web Speech synthesis API](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis), and [localService voice property](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisVoice/localService).

See [Voice agent](VOICE_AGENT.md) and [Conversation memory](VOICE_CONVERSATION_MEMORY.md) for data structures and complete behavior.
