from __future__ import annotations

import base64
import array
import sys
import io
import json
import re
import time
import wave

import httpx

from .config import Settings


class ProviderError(Exception):
    pass


class MetaProvider:
    offline = False
    label = "Meta Model API"

    def __init__(self, s: Settings, http: httpx.Client | None = None):
        from openai import OpenAI

        self.s = s
        self.client = OpenAI(base_url=s.base_url, api_key=s.api_key, timeout=s.model_timeout, max_retries=0)
        self.http = http or httpx.Client(timeout=s.model_timeout)
        self.outage = "none"
        self.calls: list[dict] = []
        self._sam_variant = 0
        self.effort_ok = {"meta": True, "fireworks": True}
        self.fireworks = (OpenAI(base_url=s.fireworks_base_url, api_key=s.fireworks_api_key, timeout=s.model_timeout,
                                 max_retries=0) if s.fireworks_api_key else None)

    def chain(self, models: list[str] | None = None) -> list[str]:
        out = list(dict.fromkeys((models or [self.s.primary_model, self.s.fallback_model])[:2]))
        if self.s.last_resort_model and self.s.last_resort_model not in out:
            out.append(self.s.last_resort_model)
        return out

    def _down(self, model: str) -> str | None:
        if self.outage == "all_down" or (self.outage == "primary_down" and model == self.s.primary_model):
            return f"{model}: simulated outage (demo switch)"
        return None

    def chat(self, messages: list[dict], tools: list[dict] | None = None, agent: str = "",
             models: list[str] | None = None) -> tuple[dict, dict]:
        chain = self.chain(models)
        attempts = [("meta", chain[0], 0.0), ("meta", chain[0], 1.0)] + [("meta", m, 2.0) for m in chain[1:]]
        if self.fireworks:
            attempts.append(("fireworks", self.s.fireworks_model, 0.0))
        effort = self.s.effort_for(agent)
        last_err = None
        for api, model, wait in attempts:
            if wait:
                time.sleep(wait)
            if api == "meta" and (down := self._down(model)):
                last_err = down
                self._record(agent, model, False, 0, None, last_err)
                continue
            client = self.client if api == "meta" else self.fireworks
            name = model if api == "meta" else "fireworks:" + model.rsplit("/", 1)[-1]
            t0 = time.time()
            try:
                kwargs = {"model": model, "messages": messages, "max_tokens": self.s.max_tokens}
                if tools:
                    kwargs["tools"] = tools
                if effort and self.effort_ok[api]:
                    kwargs["reasoning_effort"] = effort
                try:
                    r = client.chat.completions.create(**kwargs)
                except Exception as e:
                    if "reasoning_effort" not in kwargs or "reasoning" not in str(e).lower():
                        raise
                    self.effort_ok[api] = False
                    del kwargs["reasoning_effort"]
                    r = client.chat.completions.create(**kwargs)
                msg = r.choices[0].message
                out = {"content": msg.content or "", "tool_calls": [
                    {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in (msg.tool_calls or [])]}
                usage = r.usage.model_dump() if r.usage else {}
                meta = self._record(agent, (r.model or model) if api == "meta" else name, True, time.time() - t0, usage, None,
                                    finish=r.choices[0].finish_reason)
                meta["effort"] = kwargs.get("reasoning_effort")
                if not out["content"] and not out["tool_calls"]:
                    last_err = f"{name}: empty response (finish_reason={r.choices[0].finish_reason})"
                    continue
                return out, meta
            except Exception as e:
                last_err = f"{name}: {type(e).__name__}: {str(e)[:200]}"
                self._record(agent, name, False, time.time() - t0, None, last_err)
        raise ProviderError(last_err or "model unavailable")

    def _post(self, agent: str, model: str, path: str, **kw) -> dict:
        if down := self._down(model):
            self._record(agent, model, False, 0, None, down)
            raise ProviderError(down)
        t0 = time.time()
        try:
            r = self.http.post(self.s.base_url.rstrip("/") + path, headers={"Authorization": f"Bearer {self.s.api_key}"}, **kw)
        except httpx.HTTPError as e:
            err = f"{model}: {type(e).__name__}: {str(e)[:200]}"
            self._record(agent, model, False, time.time() - t0, None, err)
            raise ProviderError(err) from e
        if r.status_code >= 400:
            err = f"{model}: HTTP {r.status_code}: {r.text[:200]}"
            self._record(agent, model, False, time.time() - t0, None, err)
            raise ProviderError(err)
        self._record(agent, model, True, time.time() - t0, None, None)
        return r.json()

    def transcribe(self, wav: bytes, keywords: list[str] | None = None, agent: str = "voice") -> dict:
        req = {"model": self.s.voice_model, "mode": "PUSH_TO_TALK", "audioEncoding": "WAV"}
        if keywords:
            req["keywords"] = keywords[:50]
        t0 = time.time()
        d = self._post(agent, self.s.voice_model, "/asr/transcribe",
                       files={"request": (None, json.dumps(req), "application/json"),
                              "audio": ("note.wav", wav, "audio/wav")})
        return {"text": (d.get("transcript") or "").strip(), "turns": d.get("turns") or [],
                "duration_ms": d.get("audioDurationMs"), "model": self.s.voice_model, "latency_s": round(time.time() - t0, 2)}

    def segment(self, image: bytes, mime: str, prompt: str, agent: str = "field_photo") -> dict:
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        content = [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": url}]
        base = {"model": self.s.sam_model, "input": [{"type": "message", "role": "user", "content": content}]}
        variants = [{**base, "metadata": {"include_confidence": "true"}}, base]
        t0, err = time.time(), None
        for i in range(self._sam_variant, len(variants)):
            try:
                d = self._post(agent, self.s.sam_model, "/responses", json=variants[i])
            except ProviderError as e:
                err = e
                if "HTTP 400" in str(e) or "HTTP 422" in str(e):
                    continue
                raise
            self._sam_variant = i
            text = response_text(d)
            return {"prompt": prompt, "boxes": parse_boxes(text), "model": self.s.sam_model,
                    "latency_s": round(time.time() - t0, 2), "raw_chars": len(text)}
        raise err or ProviderError("SAM request failed")

    def _record(self, agent, model, ok, secs, usage, err, finish=None) -> dict:
        rec = {"agent": agent, "model": model, "ok": ok, "latency_s": round(secs, 2),
               "usage": usage, "error": err, "finish_reason": finish, "ts": time.time()}
        self.calls.append(rec)
        del self.calls[:-500]
        return rec


class OfflineProvider:
    offline = True
    label = "Offline rules engine (no Meta key)"

    def __init__(self):
        self.outage = "none"
        self.calls: list[dict] = []

    def chat(self, *a, **k):
        raise ProviderError("offline mode has no language model")

    def transcribe(self, *a, **k):
        raise ProviderError("voice notes need a Meta key (Muse Voice Transcribe)")

    def segment(self, *a, **k):
        raise ProviderError("photo analysis needs a Meta key (SAM 3.1)")


class GeminiSpeech:
    RATE = 24000

    def __init__(self, s: Settings, http: httpx.Client | None = None):
        self.s = s
        self.http = http or httpx.Client(timeout=s.model_timeout)
        self.calls: list[dict] = []

    @property
    def enabled(self) -> bool:
        return bool(self.s.google_api_key)

    def speak(self, text: str, voice: str | None = None) -> dict:
        if not self.enabled:
            raise ProviderError("no GOOGLE_API_KEY set")
        text = text.strip()[:1200]
        # Gemini 3.8 reads text verbatim; never put stage directions here.
        body = {"contents": [{"parts": [{"text": text}]}],
                "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice or self.s.tts_voice}}}}}
        err = None
        for model in dict.fromkeys(m for m in (self.s.tts_model, self.s.tts_fallback_model) if m):
            t0 = time.time()
            try:
                r = self.http.post(f"{self.s.google_base_url.rstrip('/')}/models/{model}:generateContent",
                                   headers={"x-goog-api-key": self.s.google_api_key}, json=body)
                if r.status_code >= 400:
                    raise ProviderError(f"{model}: HTTP {r.status_code}: {r.text[:200]}")
                parts = r.json()["candidates"][0]["content"]["parts"]
                chunks, rate = [], None
                for part in parts:
                    data = part.get("inlineData") or part.get("inline_data")
                    if not data:
                        continue
                    mime = data.get("mimeType", data.get("mime_type", "audio/L16;rate=24000"))
                    audio = base64.b64decode(data["data"], validate=True)
                    if mime.lower().split(";")[0] in ("audio/wav", "audio/wave", "audio/x-wav"):
                        with wave.open(io.BytesIO(audio), "rb") as wav:
                            if (wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) != (1, 2, "NONE"):
                                raise ProviderError(f"{model}: expected mono 16-bit PCM WAV")
                            chunk_rate = wav.getframerate()
                            audio = wav.readframes(wav.getnframes())
                    elif mime.lower().startswith("audio/l16"):
                        match = re.search(r"rate=(\d+)", mime)
                        chunk_rate = int(match.group(1)) if match else self.RATE
                    else:
                        raise ProviderError(f"{model}: unsupported audio format {mime[:60]}")
                    if not 8000 <= chunk_rate <= 96000 or (rate and rate != chunk_rate):
                        raise ProviderError(f"{model}: inconsistent audio sample rate")
                    rate = chunk_rate
                    chunks.append(audio)
                pcm = b"".join(chunks)
                if not pcm or len(pcm) % 2:
                    raise ProviderError(f"{model}: invalid PCM audio returned")
                pcm = soften_pcm_edges(pcm, rate)
            except (httpx.HTTPError, ProviderError, KeyError, IndexError, ValueError, wave.Error, EOFError) as e:
                err = e if isinstance(e, ProviderError) else ProviderError(f"{model}: {type(e).__name__}: {str(e)[:200]}")
                self._record(model, False, time.time() - t0, str(err))
                continue
            self._record(model, True, time.time() - t0, None)
            return {"wav": pcm_to_wav(pcm, rate), "model": model, "voice": voice or self.s.tts_voice,
                    "seconds": round(len(pcm) / (2 * rate), 1), "latency_s": round(time.time() - t0, 2)}
        raise err or ProviderError("text-to-speech unavailable")

    def _record(self, model, ok, secs, err):
        self.calls.append({"agent": "voice_out", "model": model, "ok": ok, "latency_s": round(secs, 2), "error": err, "ts": time.time()})
        del self.calls[:-200]


def soften_pcm_edges(pcm: bytes, rate: int) -> bytes:
    """5 ms ramps prevent discontinuity clicks without removing speech or its tail."""
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    count = min(int(rate * .005), len(samples) // 2)
    if count > 1:
        for i in range(count):
            gain = i / (count - 1)
            samples[i] = round(samples[i] * gain)
            samples[-1 - i] = round(samples[-1 - i] * gain)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def make_provider(s: Settings):
    return MetaProvider(s) if s.meta_enabled else OfflineProvider()


def parse_json(text: str) -> dict:
    if not text:
        raise ValueError("empty reply")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("no JSON object in reply")
    return json.loads(candidate)


def response_text(d: dict) -> str:
    if isinstance(d.get("output_text"), str):
        return d["output_text"]
    parts = []
    for item in d.get("output") or []:
        for c in item.get("content") or []:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "\n".join(parts)


_BOX = re.compile(r"<\|box;([^|>]*)\|>")


def parse_boxes(text: str) -> list[dict]:
    out = []
    for m in _BOX.finditer(text or ""):
        kv = dict(p.split("=", 1) for p in m.group(1).split(";") if "=" in p)
        try:
            b = {k: int(float(kv[k])) for k in ("x1", "y1", "x2", "y2", "w", "h")}
        except (KeyError, ValueError):
            continue
        b["conf"] = round(float(kv["c"]), 3) if "c" in kv else None
        out.append(b)
    return out
