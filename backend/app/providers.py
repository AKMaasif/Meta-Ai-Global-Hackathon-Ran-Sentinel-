from __future__ import annotations

import base64
import json
import re
import time

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
