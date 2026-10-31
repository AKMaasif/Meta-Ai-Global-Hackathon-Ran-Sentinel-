import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from conftest import offline_settings, run_until

from app import agents
from app.config import Settings
from app.orchestrator import Sentinel
from app.providers import MetaProvider, ProviderError, parse_boxes, response_text
from app.store import Store

ROOT = Path(__file__).resolve().parents[1]
WAV = b"RIFF" + b"\0" * 4 + b"WAVE" + b"\0" * 40
BOXES = ("<0f>1,<|box;x1=10;y1=20;x2=110;y2=220;w=640;h=480;c=0.91|><|mask;x=0;y=0;data=4,4,~abc|>,"
         "2,<|box;x1=300;y1=40;x2=360;y2=90;w=640;h=480|><|mask;x=0;y=0;data=4,4,~xyz|>")


def meta(handler) -> MetaProvider:
    s = Settings()
    s.api_key = "test-key-0000"
    return MetaProvider(s, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_chain_adds_last_resort_tier():
    p = meta(lambda r: httpx.Response(500))
    assert p.chain() == ["muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1"]
    assert p.chain(["muse-wonder-1.0", "muse-spark-1.3"]) == ["muse-wonder-1.0", "muse-spark-1.3", "muse-spark-1.1"]


def test_parse_sam_boxes_and_response_text():
    b = parse_boxes(BOXES)
    assert b[0] == {"x1": 10, "y1": 20, "x2": 110, "y2": 220, "w": 640, "h": 480, "conf": 0.91}
    assert b[1]["conf"] is None and len(b) == 2
    d = {"output": [{"type": "message", "content": [{"type": "output_text", "text": BOXES}]}]}
    assert response_text(d) == BOXES and response_text({"output_text": "x"}) == "x"


def test_segment_falls_back_to_plainer_request_shape():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        assert req.url.path == "/v1/responses" and req.headers["authorization"] == "Bearer test-key-0000"
        if "metadata" in body:
            return httpx.Response(400, json={"error": "unknown field metadata"})
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": BOXES}]}]})
    p = meta(handler)
    r = p.segment(b"\x89PNG....", "image/png", "antenna")
    content = seen[0]["input"][0]["content"]
    assert seen[0]["model"] == "sam-3.1" and content[0] == {"type": "input_text", "text": "antenna"}
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert len(r["boxes"]) == 2 and p._sam_variant == 1
    p.segment(b"x", "image/png", "cable")
    assert "metadata" not in seen[-1]


def test_transcribe_sends_documented_multipart():
    def handler(req):
        assert req.url.path == "/v1/asr/transcribe"
        body = req.content.decode("latin-1")
        assert 'name="request"' in body and "application/json" in body and 'name="audio"; filename="note.wav"' in body
        settings = json.loads(body.split("application/json\r\n\r\n")[1].split("\r\n--")[0])
        assert settings["model"] == "muse-voice-transcribe-1.0" and settings["audioEncoding"] == "WAV"
        assert settings["keywords"] == ["SEA-RAN-001"]
        return httpx.Response(200, json={"sessionId": "s1", "transcript": " Approve the power change. ", "audioDurationMs": 2100, "turns": []})
    r = meta(handler).transcribe(WAV, ["SEA-RAN-001"])
    assert r["text"] == "Approve the power change." and r["duration_ms"] == 2100


def test_media_calls_honour_outage_switch_and_http_errors():
    p = meta(lambda r: httpx.Response(429, text="rate limited"))
    with pytest.raises(ProviderError, match="HTTP 429"):
        p.transcribe(WAV)
    p.outage = "all_down"
    with pytest.raises(ProviderError, match="simulated outage"):
        p.segment(b"x", "image/png", "antenna")


def test_voice_intent_is_a_hint():
    assert agents.voice_intent("Looks good, approve it") == "approve"
    assert agents.voice_intent("Do not approve, neighbour is already loaded") == "reject"
    assert agents.voice_intent("Send it back, I want more information on the neighbour") == "more_info"
    assert agents.voice_intent("Jumper replaced, repair is done") == "resolved"
    assert agents.voice_intent("NORS notification submitted, reference 1234") == "filed"
    assert agents.voice_intent("Checking the alarms now") is None


class VisionDouble:
    offline = False
    label = "Meta Model API (test double)"

    def __init__(self, consistent="yes"):
        self.outage, self.calls, self.consistent, self.seen = "none", [], consistent, []

    def segment(self, image, mime, prompt, agent="field_photo"):
        return {"prompt": prompt, "boxes": parse_boxes(BOXES)[:1], "model": "sam-3.1", "latency_s": 0.1, "raw_chars": 10}

    def chat(self, messages, tools=None, agent="", models=None):
        self.seen.append((agent, models, messages))
        if agent == "field_photo":
            return {"content": json.dumps({"visible_issues": [{"issue": "corroded connector", "object": "connector"}],
                                           "consistent_with_diagnosis": self.consistent, "summary": "Connector at the antenna base is corroded.",
                                           "next_step": "Replace the jumper"}), "tool_calls": []}, {"model": "muse-spark-1.3", "ok": True}
        if agent in ("shift_handover", "escalation_briefer"):
            out = {"text": "Open now: RNS-2026-001 waiting on Field Operations."} if agent == "shift_handover" else \
                {"what_we_know": "VSWR alarm E1", "what_is_unclear": "Which jumper", "next_checks": ["vswr_and_power_readback", "rm -rf"],
                 "suggested_owner": "Field Operations"}
            return {"content": json.dumps(out), "tool_calls": []}, {"model": models[0], "ok": True}
        raise ProviderError("not scripted")


def test_photo_is_evidence_only(sentinel):
    sentinel.inject("SEA-RAN-004", "hardware", 2)
    inc = run_until(sentinel, "SEA-RAN-004")
    status = inc["status"]
    sentinel.provider = VisionDouble()
    rec = sentinel.add_photo(inc["id"], b"\xff\xd8 jpeg", "image/jpeg", "Sarah Chen", "sector 1 jumper")
    assert rec["findings"]["consistent_with_diagnosis"] == "yes" and len(rec["detections"]) == 3
    assert {d["label"] for d in rec["detections"]} == {"antenna", "cable", "connector"}
    assert rec["width"] == 640 and inc["evidence"][-1]["tool"] == "site_photo" and rec["evidence_id"] == inc["evidence"][-1]["id"]
    agent, models, messages = sentinel.provider.seen[-1]
    assert models == ["muse-spark-1.3", "muse-spark-1.2"] and messages[1]["content"][1]["type"] == "image_url"
    assert inc["status"] == status
    assert any(l["event"] == "photo_analysed" for l in sentinel.store.ledger(inc["id"]))
    with pytest.raises(ValueError):
        sentinel.add_photo(inc["id"], b"GIF89a", "image/gif", "Sarah Chen")


def test_photo_offline_is_stored_without_analysis(sentinel):
    sentinel.inject("SEA-RAN-004", "hardware", 2)
    inc = run_until(sentinel, "SEA-RAN-004")
    rec = sentinel.add_photo(inc["id"], b"\xff\xd8 jpeg", "image/jpeg", "Sarah Chen")
    assert rec["findings"] is None and rec["id"] in sentinel.photos and "Meta key" in rec["errors"][0]


def test_escalation_brief_offline_template(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    inc = run_until(sentinel, "SEA-RAN-001")
    sentinel.escalate(inc, "test escalation")
    assert inc["escalation_brief"]["by"] == "template"
    assert sentinel.store.get_ticket(inc["ticket_id"])["brief"] == inc["escalation_brief"]


def test_escalation_brief_and_handover_use_wonder():
    sen = Sentinel(offline_settings(), Store(":memory:"), VisionDouble())
    sen.sync = True
    sen.sim.inject_fault("SEA-RAN-004", "hardware", 2)
    for _ in range(3):
        sen.sim.step()
    inc = sen._open("SEA-RAN-004", {"score": 0.9, "breaches": ["availability"]}, "network")
    assert inc["status"] == "ESCALATED"
    b = inc["escalation_brief"]
    assert b["by"] == "muse-wonder-1.0" and b["next_checks"] == ["vswr_and_power_readback"]
    h = sen.write_handover()
    assert h["by"] == "muse-wonder-1.0" and "RNS-2026-001" in h["text"] and h["incidents"] == 1
    agent, models, messages = sen.provider.seen[-1]
    assert agent == "shift_handover" and models[0] == "muse-wonder-1.0"
    assert "RNS-2026-001" in messages[1]["content"]


def test_handover_offline_template(sentinel):
    sentinel.inject("SEA-RAN-001", "capacity_surge", 2)
    run_until(sentinel, "SEA-RAN-001")
    h = sentinel.write_handover()
    assert h["by"] == "template" and "Open now" in h["text"] and "RNS-2026-001" in h["text"]


def test_check_meta_builds_valid_test_media():
    spec = importlib.util.spec_from_file_location("check_meta", ROOT / "scripts" / "check_meta.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    w = m.test_wav()
    assert w[:4] == b"RIFF" and w[8:12] == b"WAVE" and int.from_bytes(w[24:28], "little") == 16000 and w[22] == 1
    assert m.test_png().startswith(b"\x89PNG\r\n\x1a\n")
