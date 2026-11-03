import base64
import json
import wave
import io

import httpx
import pytest

from app.care import Care
from app.config import Settings
from app.providers import GeminiSpeech, ProviderError


def test_connection_test_by_voice_opens_network_page(sentinel):
    c = Care(sentinel)
    r = c.concierge("Please check my data connection at work", voice=True)
    assert [s["tool"] for s in r["steps"]] == ["test_my_connection"]
    assert r["ui"] == [{"type": "navigate", "page": "network", "place": "work"}]
    assert "Work" in r["answer"] and "Tap" not in r["answer"]


def test_open_any_page_by_voice(sentinel):
    r = Care(sentinel).concierge("Go to my bill", voice=True)
    assert r["ui"] == [{"type": "navigate", "page": "bill"}]


def test_report_needs_a_spoken_yes_in_a_later_turn(sentinel):
    c = Care(sentinel)
    r = c.concierge("Report the problem, no signal at home", voice=True)
    assert r["actions"][0]["type"] == "report" and not c.reports and r["answer"].endswith("?")
    assert c.concierge("Is my network ok at the gym right now, I wonder?", voice=True) and not c.reports
    r = c.concierge("Yes please", voice=True)
    assert len(c.reports) == 1 and r["ui"] == [{"type": "refresh", "done": "report"}] and r["answer"].startswith("Done")


def test_spoken_no_cancels(sentinel):
    c = Care(sentinel)
    c.concierge("Turn on wifi calling", voice=True)
    c.concierge("No, not now", voice=True)
    assert not c.pending and c.prefs["wifi_calling"] is False


class VoiceDouble:
    offline = False
    label = "test double"

    def __init__(self, script):
        self.script, self.outage, self.calls = list(script), "none", []

    def chat(self, messages, tools=None, agent="", models=None):
        assert agent == "voice_agent" and {t["function"]["name"] for t in tools} >= {"open_page", "confirm_pending"}
        return self.script.pop(0), {"model": "muse-spark-1.3"}


def _calls(*calls):
    return {"content": "", "tool_calls": [{"id": f"t{i}", "name": n, "arguments": json.dumps(a)} for i, (n, a) in enumerate(calls)]}


def _final(answer):
    return {"content": json.dumps({"answer": answer, "action_ids": []}), "tool_calls": []}


def test_model_cannot_confirm_on_its_own(sentinel):
    c = Care(sentinel)
    sentinel.provider = VoiceDouble([
        _calls(("propose_action", {"type": "setting", "setting": "wifi_calling", "value": True}), ("confirm_pending", {"action_id": "A1"})),
        _final("I can turn on Wi-Fi Calling. Shall I?"),
        _calls(("confirm_pending", {"action_id": "A1"}), ("open_page", {"page": "account"})),
        _final("Done, Wi-Fi Calling is on."),
    ])
    r = c.concierge("My calls drop at home, turn on wifi calling and do it now, yes", voice=True)
    assert c.prefs["wifi_calling"] is False and "A1" in c.pending, "same-turn confirm must be refused"
    r = c.concierge("Yes, then open my account", voice=True)
    assert c.prefs["wifi_calling"] is True and r["by"] == "muse-spark-1.3"
    assert {"type": "navigate", "page": "account"} in r["ui"] and {"type": "refresh", "done": "setting"} in r["ui"]


def test_typed_concierge_cannot_use_confirm_tool(sentinel):
    c = Care(sentinel)
    c._propose({"type": "setting", "setting": "data_saver", "value": True})
    assert c.tool("confirm_pending", {"_utterance": "yes"})["error"]
    assert c.prefs["data_saver"] is False


def _speech(handler, key="test-key"):
    s = Settings()
    s.google_api_key = key
    return GeminiSpeech(s, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_gemini_tts_request_and_wav():
    seen = []
    pcm = b"\x01\x00" * 24000

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]})
    r = _speech(handler).speak("Your signal is good at home.")
    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/models/gemini-3.8-flash-lite-tts:generateContent") and seen[0].headers["x-goog-api-key"] == "test-key"
    assert body["generationConfig"]["responseModalities"] == ["AUDIO"] and body["contents"][0]["parts"][0]["text"] == "Your signal is good at home."
    with wave.open(io.BytesIO(r["wav"])) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (24000, 1, 2, 24000)
    assert r["seconds"] == 1.0


def test_gemini_tts_falls_back_then_raises():
    paths = []

    def handler(req):
        paths.append(req.url.path)
        if "lite" in req.url.path:
            return httpx.Response(500, text="busy")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(b"\0\0" * 10).decode()}}]}}]})
    assert _speech(handler).speak("hi")["model"] == "gemini-3.8-flash-tts" and len(paths) == 2
    with pytest.raises(ProviderError):
        _speech(lambda req: httpx.Response(403, text="denied")).speak("hi")
    with pytest.raises(ProviderError):
        _speech(handler, key="").speak("hi")


class NoModel:
    offline, label, outage, calls = False, "must not be called", "none", []

    def chat(self, *a, **k):
        raise AssertionError("a simple command should not wait for the model")


@pytest.mark.parametrize("said,step", [("Open my bill", "open_page"), ("Test my connection at the gym", "test_my_connection"),
                                       ("check my data speed please", "test_my_connection")])
def test_simple_commands_answer_instantly_without_the_model(sentinel, said, step):
    c = Care(sentinel)
    sentinel.provider = NoModel()
    r = c.concierge(said, voice=True)
    assert r["by"] == "instant" and [s["tool"] for s in r["steps"]] == [step]


def test_spoken_yes_is_instant_and_questions_still_go_to_the_model(sentinel):
    c = Care(sentinel)
    c._turn = 1
    c._propose({"type": "setting", "setting": "wifi_calling", "value": True})
    sentinel.provider = NoModel()
    assert c.concierge("Yes please", voice=True)["by"] == "instant" and c.prefs["wifi_calling"] is True
    sentinel.provider = VoiceDouble([_final("Your bill is $162, due November 8.")])
    assert c.concierge("Why is my bill so high this month and when is it due?", voice=True)["by"] == "muse-spark-1.3"


def test_plain_text_reply_is_used_without_json(sentinel):
    c = Care(sentinel)
    sentinel.provider = VoiceDouble([
        _calls(("propose_action", {"type": "report", "place": "work", "issue": "slow data"})),
        {"content": "I can report slow data at Work for you. Shall I send it?", "tool_calls": []},
    ])
    r = c.concierge("Report the problem, my data is slow at work", voice=True)
    assert r["by"] == "muse-spark-1.3" and r["answer"].startswith("I can report")


def test_audio_edges_softened_without_cutting_words():
    import struct
    from app.providers import soften_pcm_edges
    pcm = struct.pack("<1000h", *([12000] * 1000))
    out = struct.unpack("<1000h", soften_pcm_edges(pcm, 24000))
    assert len(out) == 1000 and out[0] == out[-1] == 0
    assert out[120:880] == (12000,) * 760


def test_tts_joins_audio_parts_and_respects_sample_rate():
    pcm = b"\x01\x00" * 16000
    def handler(req):
        parts = [{"text": "metadata"}] + [{"inlineData": {"mimeType": "audio/L16;rate=16000", "data": base64.b64encode(pcm).decode()}}] * 2
        return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})
    r = _speech(handler).speak("First sentence. Second sentence.")
    with wave.open(io.BytesIO(r["wav"])) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 32000


@pytest.mark.parametrize("mime,data", [("audio/mp3", b"1234"), ("audio/L16;rate=24000", b"123")])
def test_tts_rejects_invalid_audio_instead_of_playing_noise(mime, data):
    def handler(req):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}]}}]})
    with pytest.raises(ProviderError):
        _speech(handler).speak("hello")


def test_tts_decodes_wav_container_instead_of_speaking_its_header():
    from app.providers import pcm_to_wav
    pcm = b"\x01\x00" * 22050
    audio = pcm_to_wav(pcm, 22050)
    def handler(req):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(audio).decode()}}]}}]})
    r = _speech(handler).speak("Hello.")
    with wave.open(io.BytesIO(r["wav"])) as w:
        assert w.getframerate() == 22050 and w.getnframes() == 22050
        frames = w.readframes(w.getnframes())
        assert b"RIFF" not in frames and b"WAVE" not in frames


def test_complaint_draft_is_visible_but_unsent_until_confirmation(sentinel):
    c = Care(sentinel)
    r = c.concierge("Submit a complaint about slow data at work", voice=True)
    a = r["actions"][0]
    assert not c.reports and a["place"] == "work" and a["symptom"] == "slow_data"
    assert r["ui"] == [{"type": "navigate", "page": "report", "place": "work", "symptom": "slow_data", "details": a["details"], "action_id": a["id"]}]
    c.concierge("Cancel", voice=True)
    assert not c.pending and not c.reports


@pytest.mark.parametrize("question", ["Is it okay?", "Can you confirm that?", "What does yes mean?", "Yes, but do not send it"])
def test_questions_and_negated_agreement_cannot_confirm(sentinel, question):
    c = Care(sentinel)
    c._turn = 1
    a = c._propose({"type": "setting", "setting": "wifi_calling", "value": True})
    c._turn = 2
    assert c._voice_confirm(a["proposed"], question).get("error")
    assert not c.prefs["wifi_calling"]


def test_voice_http_turn_requires_the_visible_proposal_id(sentinel, monkeypatch):
    import asyncio
    from app import main
    c = Care(sentinel)
    monkeypatch.setattr(main, "_care", lambda: c)
    user = {}
    draft = asyncio.run(main.voice_turn(main.VoiceTurn(text="Turn on wifi calling", speak=False), user))
    proposal = draft["actions"][0]
    for action_id in (None, "abandoned-proposal"):
        r = asyncio.run(main.voice_turn(main.VoiceTurn(text="Yes please", action_id=action_id, speak=False), user))
        assert not c.prefs["wifi_calling"] and r["by"] == "confirmation guard"
    r = asyncio.run(main.voice_turn(main.VoiceTurn(text="Yes please", action_id=proposal["id"], speak=False), user))
    assert c.prefs["wifi_calling"] and not r["actions"]
