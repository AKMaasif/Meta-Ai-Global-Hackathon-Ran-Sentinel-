# py scripts/check_voice_agent.py
# py scripts/check_voice_agent.py --audio me.wav
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.care import Care  # noqa: E402
from app.config import settings  # noqa: E402
from app.orchestrator import Sentinel  # noqa: E402
from app.providers import GeminiSpeech, ProviderError, make_provider  # noqa: E402
from app.store import Store  # noqa: E402

SCRIPT = ["Please check my data connection at work",
          "Report the problem, my data is slow at work",
          "Yes, send it",
          "Show me my bill"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, help="a WAV of you asking a question; it becomes the first turn")
    a = ap.parse_args()
    provider, speech = make_provider(settings), GeminiSpeech(settings)
    print(f"Listen: {'none (no MODEL_API_KEY)' if provider.offline else settings.voice_model}")
    print(f"Think:  {'offline rules' if provider.offline else settings.primary_model}")
    print(f"Speak:  {settings.tts_model + ' / ' + settings.tts_voice if speech.enabled else 'browser voice (no GOOGLE_API_KEY)'}\n")
    script, ok = list(SCRIPT), True
    if a.audio:
        try:
            t = provider.transcribe(a.audio.read_bytes(), ["Northstar", "Wi-Fi Calling"])
            print(f"[transcribe] PASS {t['latency_s']} s: \"{t['text']}\"")
            if t["text"]:
                script.insert(0, t["text"])
        except ProviderError as e:
            print(f"[transcribe] FAIL {e}")
            ok = False
    sen = Sentinel(settings, Store(":memory:"), provider)
    care, history = Care(sen), []
    for n, said in enumerate(script, 1):
        t0 = time.time()
        r = care.concierge(said, history, voice=True, page="home")
        history += [{"who": "me", "text": said}, {"who": "bot", "text": r["answer"]}]
        tools = ", ".join(s["tool"] for s in r["steps"]) or "none"
        print(f"\n[{n}] you:   {said}\n    agent: {r['answer']}\n    by {r['by']} in {time.time() - t0:.1f} s; tools: {tools}; screen: {r.get('ui') or '-'}")
        if r["by"].startswith("rules") and not provider.offline:
            print(f"    WARN Meta path fell back to rules ({r.get('note', '')})")
            ok = False
        if speech.enabled:
            try:
                sp = speech.speak(r["answer"])
                out = ROOT / "data" / f"voice_check_{n}.wav"
                out.write_bytes(sp["wav"])
                print(f"    voice: PASS {sp['model']} {sp['seconds']} s of speech in {sp['latency_s']} s -> {out}")
            except ProviderError as e:
                print(f"    voice: FAIL {e}")
                ok = False
    sent = bool(care.reports)
    print(f"\nReport sent after the spoken yes: {'yes' if sent else 'NO'}")
    print("RESULT:", "PASS" if ok and sent else "CHECK THE LINES ABOVE")
    return 0 if ok and sent else 1


if __name__ == "__main__":
    sys.exit(main())
