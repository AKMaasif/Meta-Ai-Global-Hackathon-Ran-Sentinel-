import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import fielddocs, main
from test_field_evidence import _paused


@pytest.fixture
def client(sentinel, monkeypatch):
    monkeypatch.setattr(main, "sentinel", sentinel)
    main._failed.clear()
    monkeypatch.setattr(main.settings, "ops_password", "test-staff-secret")
    monkeypatch.setattr(main.settings, "customer_password", "test-member-secret")
    return TestClient(main.app)


def creds(portal):
    s = main.settings
    if portal == "ops":
        return {"email": s.ops_email, "password": s.ops_password, "portal": "ops"}
    return {"email": s.customer_email, "password": s.customer_password, "portal": "connect"}


def test_session_token_only_works_on_its_own_portal(client):
    client.post("/api/login", json=creds("connect"))
    tok = client.cookies.get("rs_connect")
    client.cookies.clear()
    client.cookies.set("rs_ops", tok)
    assert client.get("/api/state").status_code == 401
    client.cookies.clear()
    client.post("/api/login", json=creds("ops"))
    tok = client.cookies.get("rs_ops")
    client.cookies.clear()
    client.cookies.set("rs_connect", tok)
    assert client.get("/api/care/map", params={"place": "home"}).status_code == 401


def test_unknown_portal_is_rejected(client):
    assert client.post("/api/login", json={**creds("connect"), "portal": "../admin"}).status_code == 422


def test_repeated_wrong_passwords_are_locked_out(client):
    bad = {**creds("ops"), "password": "guess"}
    codes = [client.post("/api/login", json=bad).status_code for _ in range(main.MAX_FAILED + 1)]
    assert codes[:main.MAX_FAILED] == [401] * main.MAX_FAILED and codes[-1] == 429
    assert client.post("/api/login", json=creds("ops")).status_code == 429


def test_security_headers(client):
    h = client.get("/ops/").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"


def _docx(xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_zip_bomb_and_dtd_are_refused():
    big = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + "A" * 25_000_000 + "</w:t></w:r></w:p></w:body></w:document>"
    with pytest.raises(fielddocs.DocError, match="too large"):
        fielddocs.extract(_docx(big), "", "bomb.docx")
    laughs = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>'
    with pytest.raises(fielddocs.DocError, match="DTD"):
        fielddocs.extract(_docx(laughs), "", "laughs.docx")
    with pytest.raises(fielddocs.DocError):
        fielddocs.extract(_docx("<w:document><unclosed>"), "", "broken.docx")


def test_upload_names_and_types_are_sanitised(sentinel):
    inc = _paused(sentinel)
    rec = sentinel.add_attachment(inc["id"], b"booster found", "text/html", '../../etc/pa"ss\r\nwd.txt', "Sarah Chen")
    data, mime, name = sentinel.files[rec["id"]]
    assert name == rec["name"] == "passwd.txt" and mime == "text/plain"
    with pytest.raises(ValueError, match="not a JPEG"):
        sentinel.add_attachment(inc["id"], b"GIF89a<script>", "image/jpeg", "photo.jpg", "Sarah Chen")
