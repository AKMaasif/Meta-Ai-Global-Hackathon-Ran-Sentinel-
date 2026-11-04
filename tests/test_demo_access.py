import asyncio

from fastapi.testclient import TestClient

from app import main
from app.care import Care


def test_demo_needs_no_credentials_and_preserves_portal_boundaries(sentinel, monkeypatch):
    monkeypatch.setattr(main, "sentinel", sentinel)
    for name in ("ops_password", "customer_password"):
        monkeypatch.setattr(main.settings, name, "")
    client = TestClient(main.app)
    response = client.post("/api/demo/start", json={"portal": "ops"})
    assert response.status_code == 200 and response.json()["demo"]
    assert client.get("/api/state").json()["offline"]


def test_demo_session_roles_and_logout(sentinel, monkeypatch):
    monkeypatch.setattr(main, "sentinel", sentinel)
    ops, customer = TestClient(main.app), TestClient(main.app)
    assert customer.get("/api/care/home").status_code == 401
    assert ops.post("/api/demo/start", json={"portal": "ops"}).json()["demo"]
    assert customer.post("/api/demo/start", json={"portal": "connect"}).json()["demo"]
    assert ops.get("/api/state").status_code == 200
    assert customer.get("/api/care/home").status_code == 200
    assert customer.get("/api/state").status_code == 401
    token = customer.cookies.get("rs_connect")
    customer.cookies.set("rs_ops", token)
    assert customer.get("/api/state").status_code == 401
    cookie = customer.post("/api/demo/start", json={"portal": "connect"}).headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert token not in main.sessions
    customer.post("/api/logout")
    assert customer.get("/api/care/home").status_code == 401


def test_demo_rejects_invalid_portal():
    client = TestClient(main.app)
    assert client.post("/api/demo/start", json={"portal": "admin"}).status_code == 422
    assert client.post("/api/demo/start", json={}).status_code == 422


def test_blank_private_password_cannot_sign_in(monkeypatch):
    monkeypatch.setattr(main.settings, "ops_password", "")
    main._failed.clear()
    response = TestClient(main.app).post("/api/login", json={"portal": "ops", "email": main.settings.ops_email, "password": ""})
    assert response.status_code == 401


def test_voice_returns_text_without_cloud_speech(sentinel, monkeypatch):
    care = Care(sentinel)
    monkeypatch.setattr(main, "_care", lambda: care)
    monkeypatch.setattr(main, "sentinel", sentinel)
    user = {}
    result = asyncio.run(main.voice_turn(main.VoiceTurn(text="Open my bill", speak=True), user))
    assert result["audio"] is None and result["voice_by"] == "browser"
    assert result["answer"] and not sentinel.provider.calls
    assert main.voice_status(user)["speak"] == "browser"
    assert "/api/care/voice/speak" not in {route.path for route in main.app.routes}


def test_new_demo_session_does_not_inherit_voice_memory(sentinel, monkeypatch):
    monkeypatch.setattr(main, "sentinel", sentinel)
    client = TestClient(main.app)
    client.post("/api/demo/start", json={"portal": "connect"})
    first = client.post("/api/care/voice/turn", json={"text": "My data is slow at work"})
    assert first.status_code == 200
    assert client.get("/api/care/voice/memory").json()["messages"]
    client.post("/api/demo/start", json={"portal": "connect"})
    assert not client.get("/api/care/voice/memory").json()["messages"]
