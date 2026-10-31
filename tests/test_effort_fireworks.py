import types

import pytest

from app.config import Settings, _efforts
from app.providers import MetaProvider, ProviderError


def _reply(model):
    msg = types.SimpleNamespace(content="ok", tool_calls=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")], usage=None, model=model)


def _client(log, fail=lambda kw: None):
    def create(**kw):
        log.append(dict(kw))
        if err := fail(kw):
            raise err
        return _reply(kw["model"])
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def _settings(**kw):
    s = Settings()
    s.api_key = "test-not-a-real-key"
    s.fireworks_api_key = ""
    s.reasoning_effort, s.agent_effort = "", {}
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_effort_parsing_ignores_unknown_levels():
    assert _efforts("analyst=high, voice_agent=minimal,planner=extreme,=low") == {"analyst": "high", "voice_agent": "minimal"}


def test_effort_sent_per_agent_and_off_by_default():
    p = MetaProvider(_settings(agent_effort={"analyst": "high"}))
    log = []
    p.client = _client(log)
    _, meta = p.chat([{"role": "user", "content": "hi"}], agent="analyst")
    p.chat([{"role": "user", "content": "hi"}], agent="planner")
    assert log[0]["reasoning_effort"] == "high" and meta["effort"] == "high"
    assert "reasoning_effort" not in log[1]


def test_rejected_effort_is_dropped_once_and_not_sent_again():
    p = MetaProvider(_settings(reasoning_effort="low"))
    log = []
    p.client = _client(log, lambda kw: ValueError("400 unknown parameter: reasoning_effort") if "reasoning_effort" in kw else None)
    out, _ = p.chat([{"role": "user", "content": "hi"}], agent="analyst")
    p.chat([{"role": "user", "content": "hi"}], agent="analyst")
    assert out["content"] == "ok" and p.effort_ok["meta"] is False
    assert ["reasoning_effort" in k for k in log] == [True, False, False]


def test_fireworks_answers_when_every_meta_model_is_down(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    p = MetaProvider(_settings(fireworks_api_key="fw-test-not-real"))
    p.outage = "all_down"
    log = []
    p.fireworks = _client(log)
    out, meta = p.chat([{"role": "user", "content": "hi"}], agent="analyst")
    assert out["content"] == "ok" and meta["model"] == "fireworks:muse-spark-open"
    assert log[0]["model"] == "accounts/fireworks/models/muse-spark-open"


def test_no_fireworks_key_means_no_fireworks_call(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    p = MetaProvider(_settings())
    p.outage = "all_down"
    assert p.fireworks is None
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "hi"}])
