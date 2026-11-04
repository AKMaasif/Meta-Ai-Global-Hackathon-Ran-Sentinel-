import json

import pytest

from app.care import Care


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
