from __future__ import annotations

import re
from datetime import datetime, timezone

from .store import Store

CATEGORIES = {
    "network": "Network and coverage",
    "billing": "Billing and credits",
    "account": "Account and settings",
    "device": "Phone and device",
    "app": "Using the app and assistant",
    "other": "Something else",
}
STATUSES = {
    "open": "Open",
    "in_progress": "In progress",
    "waiting_customer": "Waiting for your reply",
    "resolved": "Resolved",
    "closed": "Closed",
}
STAFF_STATUSES = {**STATUSES, "waiting_customer": "Waiting for customer"}
PRIORITIES = {"low": "Low", "normal": "Normal", "high": "High", "urgent": "Urgent"}
ACTIVE = {"open", "in_progress", "waiting_customer"}
MAX_ACTIVE_PER_CUSTOMER = 20
LIMITS = {"name": (2, 80), "email": (5, 254), "subject": (4, 120), "description": (10, 4000), "body": (1, 4000)}
EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[A-Za-z]{2,}$")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SupportError(ValueError):
    def __init__(self, message: str, fields: dict | None = None, status: int = 400):
        super().__init__(message)
        self.message, self.fields, self.status = message, fields or {}, status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(text, single_line: bool = False) -> str:
    text = CONTROL.sub("", str(text or "")).replace("\r\n", "\n").replace("\r", "\n").strip()
    return " ".join(text.split()) if single_line else re.sub(r"\n{3,}", "\n\n", text)


NAMES = {"name": ("your name", "Your name"), "email": ("your email address", "Your email address"),
         "subject": ("a subject", "The subject"), "description": ("a description of the problem", "The description"),
         "body": ("a message", "The message")}


def _check_len(fields: dict, key: str, value: str) -> None:
    lo, hi = LIMITS[key]
    ask, label = NAMES[key]
    if not value:
        fields[key] = f"Enter {ask}."
    elif len(value) < lo:
        fields[key] = f"{label} must be at least {lo} characters."
    elif len(value) > hi:
        fields[key] = f"{label} must be {hi} characters or fewer."


def validate_new(data: dict) -> dict:
    out = {"name": clean(data.get("name"), True), "email": clean(data.get("email"), True).lower(),
           "subject": clean(data.get("subject"), True), "category": clean(data.get("category"), True),
           "description": clean(data.get("description"))}
    fields: dict[str, str] = {}
    _check_len(fields, "name", out["name"])
    _check_len(fields, "email", out["email"])
    if out["email"] and len(out["email"]) <= LIMITS["email"][1] and not EMAIL.match(out["email"]):
        fields["email"] = "Enter an email address like name@example.com."
    _check_len(fields, "subject", out["subject"])
    if out["category"] not in CATEGORIES:
        fields["category"] = "Choose a category."
    _check_len(fields, "description", out["description"])
    if fields:
        raise SupportError("Please fix the highlighted fields.", fields, 422)
    return out


def validate_body(text) -> str:
    body = clean(text)
    fields: dict[str, str] = {}
    _check_len(fields, "body", body)
    if fields:
        raise SupportError(fields["body"], fields, 422)
    return body


def public(t: dict, messages: list[dict] | None = None, staff: bool = False) -> dict:
    out = {k: v for k, v in t.items() if k != "owner" or staff}
    out["status_label"] = (STAFF_STATUSES if staff else STATUSES)[t["status"]]
    out["category_label"] = CATEGORIES[t["category"]]
    out["priority_label"] = PRIORITIES[t["priority"]]
    if messages is not None:
        out["messages"] = messages
    return out


class Support:
    def __init__(self, store: Store):
        self.store = store

    def _get(self, tid: str) -> dict:
        t = self.store.get_support_ticket(str(tid).strip().upper())
        if not t:
            raise SupportError("We couldn't find that ticket.", status=404)
        return t

    def _owned(self, tid: str, owner: str) -> dict:
        t = self.store.get_support_ticket(str(tid).strip().upper())
        if not t or t["owner"] != owner.lower():
            raise SupportError("We couldn't find that ticket.", status=404)
        return t

    def create(self, owner: str, data: dict) -> dict:
        v = validate_new(data)
        owner = owner.lower()
        active = [t for t in self.store.list_support_tickets(owner) if t["status"] in ACTIVE]
        if len(active) >= MAX_ACTIVE_PER_CUSTOMER:
            raise SupportError(f"You already have {len(active)} open requests. Please reply on one of those, or close the ones you no longer need.", status=429)
        now = _now()
        t = {"owner": owner, "name": v["name"], "email": v["email"], "subject": v["subject"], "category": v["category"],
             "priority": "normal", "status": "open", "created": now, "updated": now, "assignee": None,
             "unread_customer": False, "unread_staff": True, "replies": 0, "first_response": None}
        t = self.store.create_support_ticket(t, {"role": "customer", "author": v["name"], "body": v["description"], "created": now})
        return public(t, self.store.support_messages(t["id"]))

    def mine(self, owner: str) -> list[dict]:
        return [public(t) for t in self.store.list_support_tickets(owner.lower())]

    def view_customer(self, tid: str, owner: str) -> dict:
        t = self._owned(tid, owner)
        if t["unread_customer"]:
            t["unread_customer"] = False
            self.store.save_support_ticket(t)
        return public(t, self.store.support_messages(t["id"]))

    def customer_reply(self, tid: str, owner: str, author: str, text) -> dict:
        t = self._owned(tid, owner)
        if t["status"] == "closed":
            raise SupportError("This request is closed. Open a new request if you still need help.", status=409)
        body = validate_body(text)
        now = _now()
        self.store.add_support_message(t["id"], "customer", author, body, now)
        if t["status"] in ("waiting_customer", "resolved"):
            self._status_note(t, "open", "Reopened by your reply" if t["status"] == "resolved" else None, now)
        t.update(updated=now, unread_staff=True, replies=t["replies"] + 1)
        self.store.save_support_ticket(t)
        return public(t, self.store.support_messages(t["id"]))

    def customer_close(self, tid: str, owner: str) -> dict:
        t = self._owned(tid, owner)
        if t["status"] == "closed":
            raise SupportError("This request is already closed.", status=409)
        now = _now()
        self._status_note(t, "closed", "Closed by the customer", now)
        t.update(updated=now, unread_staff=True)
        self.store.save_support_ticket(t)
        return public(t, self.store.support_messages(t["id"]))

    def all(self, status: str = "all", category: str = "all", q: str = "") -> dict:
        tickets = self.store.list_support_tickets()
        counts = {k: 0 for k in STATUSES}
        for t in tickets:
            counts[t["status"]] += 1
        if status == "active":
            tickets = [t for t in tickets if t["status"] in ACTIVE]
        elif status != "all":
            if status not in STATUSES:
                raise SupportError("Unknown status filter.", status=400)
            tickets = [t for t in tickets if t["status"] == status]
        if category != "all":
            if category not in CATEGORIES:
                raise SupportError("Unknown category filter.", status=400)
            tickets = [t for t in tickets if t["category"] == category]
        q = clean(q, True).lower()[:120]
        if q:
            hits = []
            for t in tickets:
                hay = " ".join([t["id"], t["subject"], t["name"], t["email"]]).lower()
                if q in hay or any(q in m["body"].lower() for m in self.store.support_messages(t["id"])):
                    hits.append(t)
            tickets = hits
        return {"tickets": [public(t, staff=True) for t in tickets], "counts": counts,
                "unread": sum(1 for t in self.store.list_support_tickets() if t["unread_staff"] and t["status"] != "closed")}

    def view_staff(self, tid: str) -> dict:
        t = self._get(tid)
        if t["unread_staff"]:
            t["unread_staff"] = False
            self.store.save_support_ticket(t)
        return public(t, self.store.support_messages(t["id"]), staff=True)

    def staff_reply(self, tid: str, agent: str, text, status: str | None = "waiting_customer") -> dict:
        t = self._get(tid)
        if t["status"] == "closed":
            raise SupportError("This ticket is closed. Reopen it before replying.", status=409)
        if status is not None and status not in STATUSES:
            raise SupportError("Unknown status.", {"status": "Choose a status."}, 422)
        body = validate_body(text)
        now = _now()
        self.store.add_support_message(t["id"], "agent", agent, body, now)
        if status and status != t["status"]:
            self._status_note(t, status, None, now, agent)
        t.update(updated=now, unread_customer=True, assignee=t["assignee"] or agent, first_response=t["first_response"] or now)
        self.store.save_support_ticket(t)
        return public(t, self.store.support_messages(t["id"]), staff=True)

    def staff_update(self, tid: str, agent: str, status: str | None = None, priority: str | None = None) -> dict:
        t = self._get(tid)
        if status is None and priority is None:
            raise SupportError("Nothing to change.", status=400)
        if status is not None and status not in STATUSES:
            raise SupportError("Unknown status.", {"status": "Choose a status."}, 422)
        if priority is not None and priority not in PRIORITIES:
            raise SupportError("Unknown priority.", {"priority": "Choose a priority."}, 422)
        now = _now()
        changed = False
        if status and status != t["status"]:
            self._status_note(t, status, None, now, agent)
            t["unread_customer"] = True
            changed = True
        if priority and priority != t["priority"]:
            self.store.add_support_message(t["id"], "system", agent, f"Priority set to {PRIORITIES[priority]} by {agent}", now)
            t["priority"] = priority
            changed = True
        if changed:
            t.update(updated=now, assignee=t["assignee"] or agent)
            self.store.save_support_ticket(t)
        return public(t, self.store.support_messages(t["id"]), staff=True)

    def _status_note(self, t: dict, status: str, note: str | None, now: str, agent: str | None = None) -> None:
        text = note or f"Status changed to {STAFF_STATUSES[status]}" + (f" by {agent}" if agent else "")
        self.store.add_support_message(t["id"], "system", agent or "Northstar Connect", text, now)
        t["status"] = status


A = "/connect/help/"
ARTICLES = [
    {"id": "outage-check", "category": "network", "title": "Is there a problem with the network where I am?",
     "summary": "Check the live status for Home, Work, Gym and every Seattle neighborhood before you troubleshoot your phone.",
     "keywords": "outage down status area neighborhood zip no signal",
     "body": ["The Home screen shows a card for each of your places. A green card means the network there is normal. An amber or red card means our engineers are already working on a problem, and the card shows the stage of the repair and when we expect service back.",
              "For any other part of Seattle, open the Network tab. It lists every neighborhood with its current status, and you can tap one of your places to see the signal check and the map of nearby cells."],
     "steps": ["Open the Home tab and look at the cards for Home, Work and Gym.", "If a card is amber or red, tap See details to read the latest update and the recovery estimate.",
               "For another area, open the Network tab and find the neighborhood or ZIP code."],
     "image": {"src": A + "network.png", "alt": "Network tab showing the status of the customer's places and Seattle neighborhoods",
               "caption": "The Network tab: your places at the top, then every neighborhood with its current status."},
     "links": [["Open network status", "#/network"]]},
    {"id": "no-service", "category": "network", "title": "No service, or calls keep dropping",
     "summary": "A short checklist that fixes most connection problems on the phone itself.",
     "keywords": "no service sos calls drop dropping signal bars airplane restart sim",
     "body": ["First check whether there is a known problem at your place (see the article on network status). If engineers are already on it, there is nothing to fix on your phone and the recovery estimate tells you when to expect service back.",
              "If the network is normal at your place, the problem is usually on the phone. Work through the steps in order and test after each one."],
     "steps": ["Turn Airplane mode on, wait ten seconds, then turn it off again.", "Restart the phone.", "Check that mobile data is on and that the phone is not set to a network mode that excludes LTE.",
               "If the phone says No SIM, take the SIM out, check it for damage and put it back in.", "Indoors, turn on Wi-Fi Calling so calls use your Wi-Fi when the signal is weak.",
               "Still not working? Use Report a problem so engineers can compare your report with what the network sees."],
     "links": [["Report a problem", "#/report"], ["Turn on Wi-Fi Calling", "#/account"]]},
    {"id": "slow-data", "category": "network", "title": "Mobile data is slow",
     "summary": "Why data slows down, how to check whether the cell is busy, and what helps right away.",
     "keywords": "slow data speed buffering video congestion busy data saver",
     "body": ["Data usually slows down for one of three reasons: the cell near you is busy (for example during an event), the signal is weak where you are standing, or there is a fault the engineers are fixing.",
              "The signal check on the Network page tells you which one it is. It shows the signal quality at your place and explains it in plain words. If the cell is busy, Data Saver makes streaming smoother until the crowd clears."],
     "steps": ["Open the Network tab and choose the place where data is slow.", "Read the signal check and the explanation under it.", "If the cell is busy, turn on Data Saver in Account settings.",
               "If the signal is weak, move closer to a window or switch to Wi-Fi."],
     "links": [["Check my signal", "#/network/home"]]},
    {"id": "report-problem", "category": "network", "title": "How to report a network problem",
     "summary": "Tell us where and what is wrong. If it matches a repair, your report goes to the engineers as evidence.",
     "keywords": "report problem engineers evidence complaint",
     "body": ["A report tells our engineers what customers are seeing. We check the network at the place you choose first. If engineers are already fixing a problem there, your report is added to that repair. If not, the app suggests checks for your phone.",
              "A report is not a support request. If you need a person to look at something, or the problem is with billing or your account, contact support instead."],
     "steps": ["Open Network and tap Report a problem, or go to Help and choose Report a network problem.", "Choose the place and what is wrong.", "Add any detail, such as when it started or whether it is only indoors.", "Tap Send report and read the result."],
     "image": {"src": A + "report.png", "alt": "Report a problem form with place and symptom choices",
               "caption": "The report form: choose a place and a symptom, add a short note, and send."},
     "links": [["Report a problem", "#/report"]]},
    {"id": "recovery-estimate", "category": "network", "title": "When will service be back?",
     "summary": "How the recovery estimate is worked out and why it can change.",
     "keywords": "eta estimate when back fixed recovery time repair",
     "body": ["When engineers are working on a problem, the card for that place shows a recovery estimate and a confidence level. The estimate comes from fixed rules, not from the AI: it uses the current repair stage and how long that kind of repair normally takes.",
              "The estimate moves as the repair moves. If a field team has to visit a site it gets longer; once the fix is applied and service is being watched it gets shorter. If you turned on recovery updates in Account settings, you get a notification each time the stage changes."],
     "links": [["See my places", "#/home"]]},
    {"id": "outage-credit", "category": "billing", "title": "Outage credits",
     "summary": "If service at one of your places is down for 30 minutes or more, you can apply a $5 credit.",
     "keywords": "credit refund compensation outage money bill discount",
     "body": ["When an outage at Home, Work or Gym lasts 30 minutes or more, a $5 credit is offered automatically on the Bill tab. A fixed rule decides whether you qualify, not the AI, so the answer is the same every time.",
              "You can apply each credit once. It comes off the balance shown on the Bill tab straight away."],
     "steps": ["Open the Bill tab.", "Look for the outage credit card near the top.", "Tap Apply. The credit appears in the bill lines and the total updates."],
     "image": {"src": A + "bill.png", "alt": "Bill tab with balance, bill lines and outage credit policy",
               "caption": "The Bill tab shows the balance, the bill lines and any credit you can apply."},
     "links": [["Open my bill", "#/bill"]]},
    {"id": "understand-bill", "category": "billing", "title": "Understanding your bill",
     "summary": "What each line on the Bill tab means.",
     "keywords": "bill charges lines total balance due autopay history",
     "body": ["The Bill tab shows the balance due, the due date and whether AutoPay is on. Under This bill you see each charge: your plan, any device payments, taxes and fees, and any outage credit you applied.",
              "Payment history lists your recent payments. This is a demo account for a fictional carrier, so no real payment is ever taken. If something on the bill looks wrong, contact support and choose Billing and credits."],
     "links": [["Open my bill", "#/bill"], ["Contact support", "#/support/new"]]},
    {"id": "wifi-calling", "category": "account", "title": "Turn on Wi-Fi Calling or Data Saver",
     "summary": "Settings that help when the signal is weak or the network is busy.",
     "keywords": "wifi wi-fi calling data saver settings toggle indoor",
     "body": ["Wi-Fi Calling sends calls and texts over your Wi-Fi when the mobile signal is weak, which helps a lot indoors. Data Saver lowers video quality slightly so streaming stays smooth when the network is busy.",
              "You can also ask the assistant to change either setting. It prepares the change and waits for you to confirm it."],
     "steps": ["Open the Account tab.", "Under Settings, switch Wi-Fi Calling or Data Saver on.", "A short message confirms the change."],
     "image": {"src": A + "account.png", "alt": "Account tab showing lines, plan and settings toggles",
               "caption": "Settings are on the Account tab, below your lines and plan."},
     "links": [["Open settings", "#/account"]]},
    {"id": "my-places", "category": "account", "title": "Change your Home, Work or Gym neighborhood",
     "summary": "We watch the network at your places. Keep them up to date so alerts are about you.",
     "keywords": "places home work gym neighborhood zip move address",
     "body": ["Your places decide which network problems we tell you about first. If you move or change jobs, update the neighborhood for that place.",
              "The change takes effect right away: the Home screen and your alerts switch to the new neighborhood."],
     "steps": ["Open the Account tab and scroll to My places.", "Choose the new neighborhood for Home, Work or Gym from the list."],
     "links": [["Edit my places", "#/account"]]},
    {"id": "alerts", "category": "account", "title": "Network alerts and notifications",
     "summary": "What the bell shows, and how to choose which updates you get.",
     "keywords": "notifications alerts bell updates messages",
     "body": ["The bell at the top of every screen opens your notifications. You get an alert when a problem starts at one of your places, progress updates while it is being fixed, a message when it is restored, and a note when a credit is ready. Replies to your support requests also appear on the Help tab.",
              "You can turn network alerts and recovery updates on or off in Account settings."],
     "links": [["Open notifications", "#/notifications"]]},
    {"id": "no-sim", "category": "device", "title": "The phone says No SIM or SOS only",
     "summary": "What these messages mean and how to fix them.",
     "keywords": "no sim sos only emergency calls only esim",
     "body": ["SOS only means the phone can't register on the network but can still make emergency calls. If there is no known problem at your place, the cause is usually the phone or the SIM.",
              "No SIM means the phone can't read the SIM card or eSIM profile."],
     "steps": ["Restart the phone.", "For a physical SIM, take it out, check it, and put it back.", "For an eSIM, check that the line is turned on in the phone's mobile network settings.",
               "If it still shows No SIM, contact support and choose Phone and device."],
     "links": [["Contact support", "#/support/new"]]},
    {"id": "indoor-calls", "category": "device", "title": "Calls fail indoors but work outside",
     "summary": "Walls and glass weaken the signal. Wi-Fi Calling is the quickest fix.",
     "keywords": "indoor inside building calls fail basement",
     "body": ["Thick walls, coated glass and basements all weaken the mobile signal. If calls work outside but not inside, the network is usually fine and the building is the problem.",
              "Turn on Wi-Fi Calling so calls go over your Wi-Fi. If the problem started suddenly at a place where indoor calls used to work, send a report so engineers can check the cell."],
     "links": [["Turn on Wi-Fi Calling", "#/account"], ["Report a problem", "#/report"]]},
    {"id": "assistant", "category": "app", "title": "Using the AI assistant",
     "summary": "Ask about your places, your bill or your settings in plain words.",
     "keywords": "assistant ai chat ask question concierge",
     "body": ["The assistant can check the network at your places, explain what is happening and when it should be fixed, change settings and apply outage credits. It shows the steps it took under each answer, and it never changes anything until you tap Confirm.",
              "When the Meta key is not set, the assistant still answers with fixed rules, and it says so under the answer."],
     "steps": ["Open Help and tap Ask the assistant.", "Type a question or tap one of the suggestions.", "If the answer includes a change, read it and tap Confirm or Not now."],
     "image": {"src": A + "assistant.png", "alt": "Assistant chat answering a question about service at home",
               "caption": "The assistant answers from your own account and the network team's published updates."},
     "links": [["Ask the assistant", "#/assistant"]]},
    {"id": "voice", "category": "app", "title": "Talking to the voice assistant",
     "summary": "Hands-free help: speak, listen, and let it open the right page for you.",
     "keywords": "voice speak talk microphone mic listen",
     "body": ["Tap the Ask button with the glowing orb, above the tab bar on any screen, to start a voice conversation. The assistant listens, answers aloud and can open pages in the app for you. You can type instead of speaking at any time.",
              "Your browser asks for microphone permission the first time. Answers are read aloud with Gemini voices when that key is set, and with your browser's own voice otherwise."],
     "image": {"src": A + "voice.png", "alt": "Voice assistant sheet with the animated orb and a spoken answer",
               "caption": "The voice assistant sheet. It shows what it heard and each step it takes."}},
    {"id": "ai-privacy", "category": "app", "title": "What the AI can and can't see",
     "summary": "The assistant only reads your own account and updates the network team has published.",
     "keywords": "privacy data ai safe secure what see",
     "body": ["The assistant reads your account, your places and the network updates our engineers have approved for customers. It can't see engineering data, other customers or internal notes, and guardrails block technical details from its answers.",
              "Support requests are read by the care team, not by the AI. Only you and the care team can see your requests."]},
    {"id": "contact-support", "category": "other", "title": "Contact support and follow your request",
     "summary": "Send a request to the care team, get a reference number, and read their replies in the app.",
     "keywords": "contact support ticket person human agent help request email callback",
     "body": ["If the articles and the assistant haven't solved it, send a support request. Choose a category, write a short subject and describe the problem. You get a reference number such as CS-100001 straight away.",
              "Your requests are listed under My support requests. When the care team replies, the request shows a new-reply marker and the status changes to Waiting for your reply. You can reply in the same conversation, and close the request when you are done."],
     "steps": ["Open Help and tap Contact support.", "Fill in the form and tap Send request.", "Open My support requests to read replies and answer them."],
     "image": {"src": A + "ticket.png", "alt": "A support request with the customer's message, a reply from the care team and a reply box",
               "caption": "A support request: your message, the care team's reply and the status history in one conversation."},
     "links": [["Contact support", "#/support/new"], ["My support requests", "#/support"]]},
    {"id": "ticket-status", "category": "other", "title": "What the request statuses mean",
     "summary": "Open, In progress, Waiting for your reply, Resolved and Closed.",
     "keywords": "status open in progress waiting resolved closed ticket",
     "body": ["Open means the care team has your request but has not started on it yet. In progress means someone is working on it. Waiting for your reply means the care team asked you something.",
              "Resolved means the care team believes it is fixed. If it isn't, reply and the request opens again. Closed means the conversation has ended; open a new request if you need more help."],
     "links": [["My support requests", "#/support"]]},
]
BY_ID = {a["id"]: a for a in ARTICLES}
POPULAR = ["outage-check", "no-service", "outage-credit", "contact-support"]


def search(q: str, category: str | None = None) -> list[dict]:
    words = [w for w in re.findall(r"[a-z0-9]+", clean(q, True).lower()[:120]) if len(w) > 1]
    pool = [a for a in ARTICLES if not category or a["category"] == category]
    if not words:
        return pool
    scored = []
    for a in pool:
        title, summary = a["title"].lower(), a["summary"].lower()
        rest = (a["keywords"] + " " + " ".join(a["body"]) + " " + " ".join(a.get("steps", []))).lower()
        score = 0
        for w in words:
            if w in title:
                score += 5
            if w in a["keywords"]:
                score += 4
            if w in summary:
                score += 2
            if w in rest:
                score += 1
        if score and all(w in title + summary + rest for w in words):
            scored.append((score, a))
    return [a for _, a in sorted(scored, key=lambda x: -x[0])]
