# py scripts/check_meta.py
# py scripts/check_meta.py --audio note.wav --image site.jpg
from __future__ import annotations

import argparse
import base64
import json
import math
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.providers import MetaProvider, ProviderError, parse_json  # noqa: E402
from app.tools import TOOL_SPECS  # noqa: E402


def test_wav(seconds: float = 1.5, rate: int = 16000) -> bytes:
    n = int(seconds * rate)
    pcm = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n))
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def test_png(w: int = 320, h: int = 240) -> bytes:
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            row += b"\xff\xff\xff" if 100 <= x < 220 and 60 <= y < 180 else b"\x20\x30\x40"
        rows.append(bytes(row))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def line(ok: bool, name: str, secs: float, extra: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'} {name:14s} {secs:5.1f}s  {extra}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, help="your own WAV (mono 16-bit PCM, 16 or 24 kHz) to transcribe")
    ap.add_argument("--image", type=Path, help="your own site photo (JPEG/PNG) to segment")
    args = ap.parse_args()
    if not settings.api_key:
        print(f"No MODEL_API_KEY in {ROOT / '.env'}. Copy .env.example to .env and paste your key after MODEL_API_KEY=")
        return 1
    from openai import OpenAI

    client = OpenAI(base_url=settings.base_url, api_key=settings.api_key, timeout=settings.model_timeout, max_retries=0)
    print(f"Endpoint {settings.base_url} (key ends ...{settings.api_key[-4:]})")
    try:
        names = sorted(m.id for m in client.models.list().data)
        print("Models on this key:", ", ".join(names))
    except Exception as e:
        names = []
        print("Could not list models:", type(e).__name__, str(e)[:200])

    failures = 0
    for model in dict.fromkeys([settings.primary_model, settings.fallback_model, settings.reviewer_model]):
        if names and model not in names:
            print(f"\n{model}: FAIL not available on this key")
            failures += 1
            continue
        print(f"\n{model}")
        tests = [
            ("plain reply", [{"role": "user", "content": "Reply with the single word: ready"}], None,
             lambda m: bool(m.content and m.content.strip())),
            ("tool call", [{"role": "system", "content": "You investigate mobile network cells using tools."},
                           {"role": "user", "content": "Get the KPI window for cell SEA-RAN-001, metrics prb_util and sinr_db."}],
             TOOL_SPECS, lambda m: bool(m.tool_calls) and m.tool_calls[0].function.name == "get_kpi_window"),
            ("JSON reply", [{"role": "user", "content": 'Reply with only JSON: {"cause": "capacity_congestion", "ok": true}'}], None,
             lambda m: parse_json(m.content or "").get("ok") is True),
        ]
        for name, messages, tools, check in tests:
            t0 = time.time()
            try:
                kw = {"model": model, "messages": messages, "max_tokens": settings.max_tokens}
                if tools:
                    kw["tools"] = tools
                r = client.chat.completions.create(**kw)
                ok = check(r.choices[0].message)
                usage = r.usage.model_dump() if r.usage else {}
                print(f"  {'PASS' if ok else 'FAIL'} {name:12s} {time.time() - t0:5.1f}s  tokens {usage.get('total_tokens', '?')}"
                      + ("" if ok else f"  reply: {json.dumps((r.choices[0].message.content or '')[:200])}"))
                failures += not ok
            except Exception as e:
                print(f"  FAIL {name:12s} {type(e).__name__}: {str(e)[:200]}")
                failures += 1

    for model, role in ((settings.last_resort_model, "last-resort tier"), (settings.wonder_model, "escalation briefs, shift handover")):
        print(f"\n{model}  ({role})")
        if names and model not in names:
            print("  FAIL not available on this key (the app skips to the next model)")
            failures += 1
            continue
        for name, prompt, check in (("plain reply", "Reply with the single word: ready", lambda c: bool(c.strip())),
                                    ("JSON reply", 'Reply with only JSON: {"ok": true}', lambda c: parse_json(c).get("ok") is True)):
            t0 = time.time()
            try:
                r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                                   max_tokens=settings.max_tokens)
                c = r.choices[0].message.content or ""
                failures += line(check(c), name, time.time() - t0, "" if check(c) else json.dumps(c[:150]))
            except Exception as e:
                failures += line(False, name, time.time() - t0, f"{type(e).__name__}: {str(e)[:200]}")

    png = test_png()
    img, mime = (args.image.read_bytes(), "image/png" if args.image.suffix.lower() == ".png" else "image/jpeg") if args.image else (png, "image/png")
    data_url = f"data:{mime};base64,{base64.b64encode(img).decode()}"

    print(f"\n{settings.vision_model}  (field photo analyst, image input)")
    t0 = time.time()
    try:
        r = client.chat.completions.create(model=settings.vision_model, max_tokens=settings.max_tokens, messages=[{"role": "user", "content": [
            {"type": "text", "text": 'Describe the main object in one or two words. Reply with only JSON: {"object": str}'},
            {"type": "image_url", "image_url": {"url": data_url}}]}])
        c = r.choices[0].message.content or ""
        obj = parse_json(c).get("object")
        failures += line(bool(obj), "image + JSON", time.time() - t0, f"saw: {obj}")
    except Exception as e:
        failures += line(False, "image + JSON", time.time() - t0, f"{type(e).__name__}: {str(e)[:200]}")

    provider = MetaProvider(settings)
    print(f"\n{settings.sam_model}  (site photo: finds antennas, cables, connectors)")
    if names and settings.sam_model not in names:
        print("  FAIL not available on this key (photos are stored without analysis)")
        failures += 1
    else:
        prompt = "antenna" if args.image else "white square"
        t0 = time.time()
        try:
            seg = provider.segment(img, mime, prompt)
            shape = ["with confidence", "without metadata"][provider._sam_variant]
            boxes = seg["boxes"]
            extra = f"'{prompt}': {len(boxes)} box(es), request shape {shape}"
            if boxes:
                extra += f", first {boxes[0]['x1']},{boxes[0]['y1']}-{boxes[0]['x2']},{boxes[0]['y2']} of {boxes[0]['w']}x{boxes[0]['h']}"
            ok = bool(boxes) or bool(args.image)
            failures += line(ok, "segment", time.time() - t0, extra + ("" if ok else f" (reply had {seg['raw_chars']} chars, no box tokens)"))
        except ProviderError as e:
            failures += line(False, "segment", time.time() - t0, str(e)[:300])

    print(f"\n{settings.voice_model}  (voice notes and spoken questions)")
    wav = args.audio.read_bytes() if args.audio else test_wav()
    t0 = time.time()
    try:
        tr = provider.transcribe(wav, ["SEA-RAN-001", "VSWR"])
        failures += line(True, "transcribe", time.time() - t0,
                         f"{tr['duration_ms']} ms of audio, transcript: {json.dumps(tr['text'][:120]) if tr['text'] else '(empty; expected for the test tone)'}")
    except ProviderError as e:
        failures += line(False, "transcribe", time.time() - t0, str(e)[:300])

    unused = [m for m in names if m.endswith("-contributor") or m.startswith("muse-image")]
    if unused:
        print("\nOn the key but not used by design:", ", ".join(unused))
        print("  -contributor: cheaper, but Meta may train on what is sent; set ASSISTANT_MODEL to opt in for the customer assistant.")
        print("  muse-image: generated pictures are not evidence, so the app does not create images.")
    print("\nAll checks passed." if not failures else f"\n{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
