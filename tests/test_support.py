import pytest
from fastapi.testclient import TestClient

from app import main, support
from app.store import Store
from app.support import Support, SupportError

GOOD = {"name": "Jordan Rivera", "email": "jordan@example.com", "subject": "No signal at home",
        "category": "network", "description": "Since noon the phone shows SOS indoors at home."}


@pytest.fixture
def client(sentinel, monkeypatch):
    monkeypatch.setattr(main, "sentinel", sentinel)
    main._failed.clear()
    return TestClient(main.app)


def login(c, portal):
    s = main.settings
    email, pw = (s.ops_email, s.ops_password) if portal == "ops" else (s.customer_email, s.customer_password)
    assert c.post("/api/login", json={"email": email, "password": pw, "portal": portal}).status_code == 200


@pytest.fixture
def customer(client):
    login(client, "connect")
    return client


@pytest.fixture
def staff(sentinel, monkeypatch):
    c = TestClient(main.app)
    login(c, "ops")
    return c


def test_create_ticket_returns_reference_and_first_message(customer):
    r = customer.post("/api/care/support", json=GOOD)
    assert r.status_code == 200
    t = r.json()
    assert t["id"] == "CS-100001" and t["status"] == "open" and t["status_label"] == "Open"
    assert t["category_label"] == "Network and coverage" and t["priority"] == "normal"
    assert [m["role"] for m in t["messages"]] == ["customer"] and t["messages"][0]["body"] == GOOD["description"]
    assert "owner" not in t


def test_ticket_ids_are_unique_and_sequential(customer):
    ids = [customer.post("/api/care/support", json={**GOOD, "subject": f"Problem {i}"}).json()["id"] for i in range(5)]
    assert ids == [f"CS-{100001 + i}" for i in range(5)] and len(set(ids)) == 5


@pytest.mark.parametrize("field,value,needle", [
    ("name", "", "Enter your name"), ("name", "J", "at least 2"), ("name", "x" * 81, "80 characters or fewer"),
    ("email", "", "Enter your email"), ("email", "jordan", "like name@example.com"), ("email", "a@b", "like name@example.com"),
    ("email", "x<script>@e.com", "like name@example.com"), ("subject", "  ", "Enter a subject"), ("subject", "abc", "at least 4"),
    ("category", "", "Choose a category"), ("category", "admin", "Choose a category"),
    ("description", "short", "at least 10"), ("description", "x" * 4001, "4000 characters or fewer")])
def test_invalid_contact_form_fields_are_rejected(customer, field, value, needle):
    r = customer.post("/api/care/support", json={**GOOD, field: value})
    assert r.status_code == 422
    d = r.json()["detail"]
    assert needle in d["fields"][field] and d["message"] == "Please fix the highlighted fields."
    assert customer.get("/api/care/support").json()["tickets"] == []


def test_wrong_types_and_missing_body_are_rejected(customer):
    assert customer.post("/api/care/support", json={**GOOD, "subject": ["x"]}).status_code == 422
    assert customer.post("/api/care/support", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 422
    assert customer.post("/api/care/support", json={}).status_code == 422


def test_input_is_cleaned_but_stored_verbatim_for_safe_display(customer):
    t = customer.post("/api/care/support", json={**GOOD, "name": "  Jordan \x07 Rivera ", "subject": "<b>Help</b>\tnow",
                                                  "description": "Line one\r\n\r\n\r\n\r\nLine two <img src=x onerror=alert(1)>"}).json()
    assert t["name"] == "Jordan Rivera" and t["subject"] == "<b>Help</b> now"
    assert t["messages"][0]["body"] == "Line one\n\nLine two <img src=x onerror=alert(1)>"


def test_tickets_persist_in_sqlite_across_restarts(tmp_path):
    db = tmp_path / "sentinel.db"
    t = Support(Store(db)).create("customer@northstar.demo", GOOD)
    Support(Store(db)).staff_reply(t["id"], "Sarah Chen", "We are looking at it.")
    again = Support(Store(db))
    mine = again.mine("customer@northstar.demo")
    assert [x["id"] for x in mine] == [t["id"]] and mine[0]["status"] == "waiting_customer"
    assert [m["role"] for m in again.view_customer(t["id"], "customer@northstar.demo")["messages"]] == ["customer", "agent", "system"]


def test_simulation_reset_keeps_support_tickets(tmp_path):
    store = Store(tmp_path / "s.db")
    Support(store).create("customer@northstar.demo", GOOD)
    store.reset()
    assert len(store.list_support_tickets()) == 1


def test_customer_sees_only_their_own_tickets(customer, sentinel):
    other = Support(sentinel.store).create("someone.else@northstar.demo", {**GOOD, "subject": "Not yours"})
    mine = customer.post("/api/care/support", json=GOOD).json()
    assert [t["id"] for t in customer.get("/api/care/support").json()["tickets"]] == [mine["id"]]
    for path in (f"/api/care/support/{other['id']}", f"/api/care/support/{other['id'].lower()}"):
        assert customer.get(path).status_code == 404
    assert customer.post(f"/api/care/support/{other['id']}/reply", json={"body": "hi"}).status_code == 404
    assert customer.post(f"/api/care/support/{other['id']}/close").status_code == 404
    assert len(sentinel.store.support_messages(other["id"])) == 1


def test_second_customer_session_cannot_read_first_customers_ticket(customer, sentinel):
    t = customer.post("/api/care/support", json=GOOD).json()
    c2 = TestClient(main.app)
    main.sessions["second-customer-token"] = {"email": "second@northstar.demo", "portal": "connect"}
    c2.cookies.set("rs_connect", "second-customer-token")
    try:
        assert c2.get("/api/care/support").json()["tickets"] == []
        assert c2.get(f"/api/care/support/{t['id']}").status_code == 404
    finally:
        main.sessions.pop("second-customer-token", None)


@pytest.mark.parametrize("method,path", [
    ("get", "/api/care/support"), ("post", "/api/care/support"), ("get", "/api/care/support/CS-100001"),
    ("post", "/api/care/support/CS-100001/reply"), ("post", "/api/care/support/CS-100001/close"),
    ("get", "/api/care/help"), ("get", "/api/care/help/outage-credit"),
    ("get", "/api/support/tickets"), ("get", "/api/support/tickets/CS-100001"),
    ("post", "/api/support/tickets/CS-100001/reply"), ("post", "/api/support/tickets/CS-100001/update")])
def test_support_endpoints_require_sign_in(client, method, path):
    r = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401


def test_customer_cannot_use_admin_endpoints(customer):
    t = customer.post("/api/care/support", json=GOOD).json()
    assert customer.get("/api/support/tickets").status_code == 401
    assert customer.post(f"/api/support/tickets/{t['id']}/update", json={"status": "resolved"}).status_code == 401
    assert customer.post(f"/api/support/tickets/{t['id']}/reply", json={"body": "self-approved"}).status_code == 401


def test_staff_session_cannot_use_customer_endpoints(staff):
    assert staff.get("/api/care/support").status_code == 401
    assert staff.post("/api/care/support", json=GOOD).status_code == 401


def test_full_conversation_and_status_history(customer, staff):
    tid = customer.post("/api/care/support", json=GOOD).json()["id"]
    lst = staff.get("/api/support/tickets").json()
    assert lst["unread"] == 1 and lst["tickets"][0]["unread_staff"] and lst["tickets"][0]["owner"] == main.settings.customer_email
    assert staff.get("/api/state").json()["summary"]["support_unread"] == 1
    assert staff.get(f"/api/support/tickets/{tid}").json()["unread_staff"] is False
    r = staff.post(f"/api/support/tickets/{tid}/reply", json={"body": "Engineers are fixing the cell.", "status": "waiting_customer"}).json()
    assert r["status"] == "waiting_customer" and r["assignee"] == "Sarah Chen" and r["first_response"]
    assert customer.get("/api/care/home").json()["support_unread"] == 1
    v = customer.get(f"/api/care/support/{tid}").json()
    assert v["status_label"] == "Waiting for your reply" and v["unread_customer"] is False
    assert customer.get("/api/care/home").json()["support_unread"] == 0
    r = customer.post(f"/api/care/support/{tid}/reply", json={"body": "Thanks, it works again."}).json()
    assert r["status"] == "open" and r["replies"] == 1
    staff.post(f"/api/support/tickets/{tid}/update", json={"status": "resolved", "priority": "high"})
    r = customer.post(f"/api/care/support/{tid}/reply", json={"body": "Actually it dropped again."}).json()
    assert r["status"] == "open" and any(m["body"] == "Reopened by your reply" for m in r["messages"])
    r = customer.post(f"/api/care/support/{tid}/close").json()
    assert r["status"] == "closed"
    roles = [m["role"] for m in r["messages"]]
    assert roles.count("customer") == 3 and roles.count("agent") == 1 and roles.count("system") >= 5
    assert customer.post(f"/api/care/support/{tid}/reply", json={"body": "one more"}).status_code == 409
    assert customer.post(f"/api/care/support/{tid}/close").status_code == 409
    assert staff.post(f"/api/support/tickets/{tid}/reply", json={"body": "hello"}).status_code == 409
    assert staff.post(f"/api/support/tickets/{tid}/update", json={"status": "open"}).json()["status"] == "open"


def test_admin_filters_and_search(customer, staff):
    a = customer.post("/api/care/support", json=GOOD).json()["id"]
    b = customer.post("/api/care/support", json={**GOOD, "category": "billing", "subject": "Bill looks wrong",
                                                    "description": "There is a charge I do not recognise on my bill."}).json()["id"]
    staff.post(f"/api/support/tickets/{a}/update", json={"status": "resolved"})
    get = lambda **p: [t["id"] for t in staff.get("/api/support/tickets", params=p).json()["tickets"]]
    assert get() == [b] and set(get(status="all")) == {a, b} and get(status="resolved") == [a]
    assert get(status="all", category="billing") == [b]
    assert get(status="all", q="recognise") == [b] and get(status="all", q=a.lower()) == [a] and get(status="all", q="nothing-like-this") == []
    counts = staff.get("/api/support/tickets", params={"status": "all"}).json()["counts"]
    assert counts["open"] == 1 and counts["resolved"] == 1
    assert staff.get("/api/support/tickets", params={"status": "bogus"}).status_code == 400
    assert staff.get("/api/support/tickets", params={"category": "bogus"}).status_code == 400


def test_admin_rejects_bad_status_priority_and_empty_reply(customer, staff):
    tid = customer.post("/api/care/support", json=GOOD).json()["id"]
    assert staff.post(f"/api/support/tickets/{tid}/update", json={"status": "deleted"}).status_code == 422
    assert staff.post(f"/api/support/tickets/{tid}/update", json={"priority": "p0"}).status_code == 422
    assert staff.post(f"/api/support/tickets/{tid}/update", json={}).status_code == 400
    assert staff.post(f"/api/support/tickets/{tid}/reply", json={"body": "   "}).status_code == 422
    assert staff.post(f"/api/support/tickets/{tid}/reply", json={"body": "x" * 4001}).status_code == 422
    assert staff.post(f"/api/support/tickets/{tid}/reply", json={"body": "ok", "status": "nope"}).status_code == 422
    assert staff.get("/api/support/tickets/CS-999999").status_code == 404
    assert len(staff.get(f"/api/support/tickets/{tid}").json()["messages"]) == 1


def test_customer_reply_validation(customer):
    tid = customer.post("/api/care/support", json=GOOD).json()["id"]
    assert customer.post(f"/api/care/support/{tid}/reply", json={"body": ""}).status_code == 422
    assert customer.post(f"/api/care/support/{tid}/reply", json={"body": "y" * 4001}).status_code == 422
    assert customer.get("/api/care/support/CS-999999").status_code == 404
    assert customer.get("/api/care/support/../../api/state").status_code in (401, 404)


def test_open_request_limit_per_customer(customer):
    for i in range(support.MAX_ACTIVE_PER_CUSTOMER):
        assert customer.post("/api/care/support", json={**GOOD, "subject": f"Request {i}"}).status_code == 200
    r = customer.post("/api/care/support", json=GOOD)
    assert r.status_code == 429 and "open requests" in r.json()["detail"]["message"]


def test_help_catalogue_search_and_articles(customer):
    d = customer.get("/api/care/help").json()
    assert len(d["articles"]) == len(support.ARTICLES) and all(p in support.BY_ID for p in d["popular"])
    assert sum(c["count"] for c in d["categories"]) == len(support.ARTICLES)
    ids = [a["id"] for a in customer.get("/api/care/help", params={"q": "credit"}).json()["articles"]]
    assert ids[0] == "outage-credit"
    assert customer.get("/api/care/help", params={"q": "slow data"}).json()["articles"][0]["id"] == "slow-data"
    assert customer.get("/api/care/help", params={"q": "zzzqqq"}).json()["articles"] == []
    assert {a["category"] for a in customer.get("/api/care/help", params={"category": "billing"}).json()["articles"]} == {"billing"}
    assert customer.get("/api/care/help", params={"category": "nope"}).status_code == 400
    a = customer.get("/api/care/help/outage-credit").json()
    assert a["category_label"] == "Billing and credits" and a["image"]["src"].startswith("/connect/help/")
    assert customer.get("/api/care/help/does-not-exist").status_code == 404


def test_every_article_image_and_link_is_real():
    from app.config import ROOT
    routes = {"home", "network", "account", "bill", "help", "assistant", "support", "notifications", "report", "shop"}
    for a in support.ARTICLES:
        if a.get("image"):
            assert (ROOT / "frontend" / a["image"]["src"].lstrip("/")).is_file(), a["id"]
        for _, href in a.get("links", []):
            assert href.startswith("#/") and href[2:].split("/")[0] in routes, href


def test_support_error_carries_fields():
    with pytest.raises(SupportError) as e:
        support.validate_new({})
    assert e.value.status == 422 and set(e.value.fields) == {"name", "email", "subject", "category", "description"}
