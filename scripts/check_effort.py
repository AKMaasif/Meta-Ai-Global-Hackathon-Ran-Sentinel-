# py scripts/check_effort.py
# py scripts/check_effort.py --fireworks
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import EFFORTS, settings  # noqa: E402

QUESTION = ("An LTE cell shows PRB utilisation 96%, SINR 13 dB, UL RSSI -105 dBm, no alarms, far-user share 0.07. "
            "Which one cause fits best: capacity_congestion, external_interference, overshooting_coverage or hardware_fault? "
            "Answer with the cause name only.")
EXPECT = "capacity_congestion"


def run(name: str, client, model: str) -> None:
    print(f"\n{name}  model {model}")
    print(f"  {'effort':8} {'result':9} {'secs':>6} {'tokens':>7} {'reasoning':>9}  answer")
    for effort in (None, *EFFORTS):
        kw = {"model": model, "messages": [{"role": "user", "content": QUESTION}], "max_tokens": settings.max_tokens}
        if effort:
            kw["reasoning_effort"] = effort
        t0 = time.time()
        try:
            r = client.chat.completions.create(**kw)
        except Exception as e:
            print(f"  {effort or '(none)':8} {'REJECTED':9} {time.time() - t0:6.1f}  {type(e).__name__}: {str(e)[:120]}")
            continue
        u = r.usage
        details = getattr(u, "completion_tokens_details", None) if u else None
        reasoning = getattr(details, "reasoning_tokens", None) if details else None
        text = (r.choices[0].message.content or "").strip()
        ok = "right" if EXPECT in text.lower() else "WRONG"
        print(f"  {effort or '(none)':8} {'ok':9} {time.time() - t0:6.1f} {u.completion_tokens if u else '-':>7} "
              f"{reasoning if reasoning is not None else '-':>9}  {ok}: {text[:60]}")


def main() -> None:
    from openai import OpenAI
    ap = argparse.ArgumentParser()
    ap.add_argument("--fireworks", action="store_true")
    a = ap.parse_args()
    if not settings.api_key:
        sys.exit("No MODEL_API_KEY in .env")
    print(f"Meta key ...{settings.api_key[-4:]}")
    run("Meta Model API", OpenAI(base_url=settings.base_url, api_key=settings.api_key, timeout=settings.model_timeout,
                                 max_retries=0), settings.primary_model)
    if a.fireworks:
        if not settings.fireworks_api_key:
            sys.exit("No FIREWORKS_API_KEY in .env")
        print(f"\nFireworks key ...{settings.fireworks_api_key[-4:]}")
        run("Fireworks", OpenAI(base_url=settings.fireworks_base_url, api_key=settings.fireworks_api_key,
                                timeout=settings.model_timeout, max_retries=0), settings.fireworks_model)
    print("\nIf a level is REJECTED, leave it out of AGENT_EFFORT. The app also drops the setting by itself after one rejection.")


if __name__ == "__main__":
    main()
