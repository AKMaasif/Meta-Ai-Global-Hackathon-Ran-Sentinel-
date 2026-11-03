"""Session-scoped voice context. Historical text is never current network evidence."""
from __future__ import annotations

import copy
import json
import re
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager

from .care import SYMPTOMS, is_no, is_yes


class VoiceConversation:
    TTL = 30 * 60
    MAX_MESSAGES = 12

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.care = None
        self.clear()

    def clear(self):
        self.state = {"pending": {}, "turn": 0}
        self.messages = []
        self.summary = ""
        self.issue = {}
        self.last_action = None
        self.completed_actions = []
        self.cache = OrderedDict()
        self.touched = self.clock()

    def _ready(self, care):
        if self.care is not care or self.clock() - self.touched >= self.TTL:
            self.clear()
            self.care = care
        self.touched = self.clock()

    @contextmanager
    def _scope(self, care):
        token = care._voice_context.set(self.state)
        try:
            yield
        finally:
            care._voice_context.reset(token)

    def _remember(self, who, text):
        self.messages.append({"who": who, "text": str(text)[:900]})
        while len(self.messages) > self.MAX_MESSAGES:
            old = self.messages.pop(0)
            # Extractive, bounded notes; not a speculative model-generated summary.
            if old["who"] == "me":
                self.summary = (self.summary + " | Customer previously said: " + old["text"])[-1600:]

    def _snapshot(self):
        return copy.deepcopy({"messages": self.messages, "summary": self.summary,
                              "issue": self.issue, "actions": list(self.state["pending"].values()),
                              "last_action": self.last_action, "completed_actions": self.completed_actions, "idle_timeout_seconds": self.TTL})

    def restore(self, care):
        with self.lock:
            self._ready(care)
            return self._snapshot()

    def reset(self, care):
        with self.lock:
            self.clear()
            self.care = care
            return self._snapshot()

    @staticmethod
    def _reply(answer, actions=None, ui=None, by="conversation", steps=None):
        return {"answer": answer, "actions": actions or [], "ui": ui or [], "steps": steps or [], "by": by}

    def _active(self):
        return next(reversed(self.state["pending"].values()), None)

    def _draft(self, care):
        if not self.issue.get("symptom") or not self.issue.get("place"):
            return self._reply("What problem should I report, and is it at home, work or the gym?")
        # A correction supersedes the previous proposal; its old ID cannot authorize the revision.
        self.state["pending"].clear()
        care._turn += 1
        result = care.tool("propose_action", {"type": "report", **self.issue})
        if result.get("error"):
            return self._reply("I couldn't prepare that report. Please check the problem and location.")
        action = self.state["pending"][result["proposed"]]
        return self._reply(f"I've drafted a report for {SYMPTOMS[action['symptom']].lower()} at {action['place']}. Shall I send it?",
                           [action], [result["ui"]], steps=[{"tool": "propose_action", "label": "Prepared your complaint for review"}])

    def _finish(self, care, action_id, cancel=False):
        action = self.state["pending"].get(action_id)
        if not action:
            raise ValueError("That proposal has expired, was revised, or is already completed. Review the current draft.")
        if cancel:
            del self.state["pending"][action_id]
            result = {"cancelled": action["label"], "done": "Cancelled. No change was made."}
        else:
            result = care.confirm(action_id)
        self.last_action = {"status": "cancelled" if cancel else "completed", "type": action["type"],
                            "label": action["label"], "result": result.get("done", ""),
                            "reference": (result.get("report") or {}).get("id"),
                            "setting": action.get("setting"), "value": action.get("value")}
        self.completed_actions.append(copy.deepcopy(self.last_action))
        self.completed_actions = self.completed_actions[-8:]
        return result

    def action(self, care, action_id, cancel=False):
        with self.lock:
            self._ready(care)
            with self._scope(care):
                result = self._finish(care, action_id, cancel)
                self._remember("bot", result.get("done", "Cancelled."))
                return copy.deepcopy(result)

    def owns(self, care, action_id):
        with self.lock:
            self._ready(care)
            return action_id in self.state["pending"]

    def turn(self, care, text, action_id=None, page="", request_id=None):
        with self.lock:
            self._ready(care)
            fingerprint = (text, action_id, page)
            if request_id in self.cache:
                previous, result = self.cache[request_id]
                if previous != fingerprint:
                    raise ValueError("This request ID was already used for a different turn.")
                return copy.deepcopy(result)
            with self._scope(care):
                result = self._respond(care, text.strip()[:500], action_id, page)
                # Keep proposals visible across unrelated questions and page refreshes.
                actions = self.state["pending"]
                if len(actions) > 1:
                    latest = next(reversed(actions))
                    self.state["pending"] = {latest: actions[latest]}
                result["actions"] = list(self.state["pending"].values())
                self._remember("me", text)
                self._remember("bot", result["answer"])
                result["memory"] = self._snapshot()
                result = copy.deepcopy(result)
                if request_id:
                    self.cache[request_id] = (fingerprint, result)
                    while len(self.cache) > 16:
                        self.cache.popitem(last=False)
                return result

    def _respond(self, care, text, action_id, page):
        q = text.lower().strip(" .!?")
        active = self._active()
        if q in ("forget this conversation", "forget our conversation", "start over", "start a new conversation"):
            self.clear()
            # clear() replaces the scope dictionary; rebind the existing context for this turn.
            care._voice_context.set(self.state)
            return self._reply("I've cleared this conversation and its unconfirmed proposals. What can I help with?")
        named_setting = ("wifi_calling" if re.search(r"wi[ -]?fi calling", q) else
                         "data_saver" if "data saver" in q else None)
        setting_command = bool(re.search(r"\b(turn|switch|enable|disable|set)\b", q))
        value = False if re.search(r"\b(off|disable)\b", q) else True if re.search(r"\b(on|enable)\b", q) else None
        if setting_command and value is not None:
            previous = active if active and active["type"] == "setting" else self.last_action
            setting = named_setting or (previous.get("setting") if previous and previous["type"] == "setting" and
                                        re.search(r"\b(it|that)\b", q) and not (active and active["type"] != "setting") else None)
            if setting:
                self.state["pending"].clear()
                care._turn += 1
                proposed = care.tool("propose_action", {"type": "setting", "setting": setting, "value": value})
                action = self.state["pending"][proposed["proposed"]]
                return self._reply(f"I can {action['label'][0].lower() + action['label'][1:]}. Shall I?",
                                   [action], [proposed["ui"]])
            if re.search(r"\b(it|that)\b", q):
                return self._reply("Which setting should I change: Wi-Fi Calling or Data Saver?")
        if is_yes(text):
            if not active or action_id != active["id"]:
                return self._reply("Please review the current proposal before confirming. No change was made.", by="confirmation guard")
            result = self._finish(care, action_id)
            report = result.get("report")
            answer = f"Done, I've sent report {report['id']}. {result['done']}" if report else f"Done. {result['done']}"
            return self._reply(answer, ui=[{"type": "refresh", "done": active["type"]}])
        if is_no(text):
            if active:
                self._finish(care, active["id"], cancel=True)
                return self._reply("Cancelled. I haven't made that change.")
            return self._reply("There's no unconfirmed action to cancel.")
        if re.fullmatch(r"(?:please )?(?:read|repeat|show)(?: me)? (?:it|that|the draft|the complaint)(?: back)?", q):
            if active:
                return self._reply(f"{active['label']}. {active.get('details', '')} Shall I proceed?")
            return self._reply("There's no draft waiting. " + (self.last_action or {}).get("result", "What would you like to prepare?"))

        locations = []
        for match in re.finditer(r"\b(home|work|gym)\b", q):
            before = q[max(0, match.start() - 18):match.start()]
            if re.search(r"(?:not(?: at)?|from|instead of)\s+(?:my |the )?$", before):
                continue
            locations.append(match.group(1))
        place = locations[-1] if locations else None
        if re.search(r"did you (?:send|submit|cancel)|(?:reference|report) number", q):
            if active and active["type"] == "report" and "number" not in q:
                return self._reply("The current complaint is still a draft. I haven't sent it.")
            outcome = self.last_action
            if re.search(r"send|submit|(?:reference|report) number", q):
                outcome = next((a for a in reversed(self.completed_actions) if a["type"] == "report" and a["status"] == "completed"), None)
            if outcome:
                ref = outcome.get("reference")
                return self._reply(f"That action was {outcome['status']}. " +
                                   (f"Your report reference is {ref}." if ref else outcome["result"]))
            return self._reply("I haven't completed that action in this conversation yet.")
        if re.search(r"is (?:it|that) still|is (?:it|that) fixed|has it improved|check again|what about there", q):
            if self.issue.get("place"):
                return care.concierge(f"Test my connection at {self.issue['place']}", self.messages, True, page)
            return self._reply("Which location should I check: home, work or the gym?")
        symptom = ("slow_data" if re.search(r"slow (?:data|internet)|data (?:is |feels )?slow", q) else
                   "dropped_calls" if re.search(r"dropped calls|calls (?:keep )?dropping", q) else
                   "no_service" if re.search(r"no (?:signal|service)|lost (?:signal|service)", q) else None)
        report_request = bool(re.search(r"\b(report|complaint|complain)\b", q))
        correction = bool(re.search(r"\b(actually|instead|change|update|correct|add)\b", q))
        if symptom:
            self.issue.update(symptom=symptom, details=text)
            if place:
                self.issue["place"] = place
        elif place and (correction or re.search(r"what about|how about|check|test", q)):
            previous = self.issue.get("place")
            self.issue["place"] = place
            if previous:
                self.issue["details"] = re.sub(rf"\b{previous}\b", place, self.issue.get("details", ""), flags=re.I)
        if correction and active and active["type"] == "report":
            if re.search(r"\badd\b", q) and not symptom:
                self.issue["details"] = (self.issue.get("details", "") + "; " + text)[:300]
            if place or symptom or re.search(r"\badd\b", q):
                return self._draft(care)
            return self._reply("What should I change in the complaint: the location, problem or details?")
        if report_request:
            # Report references require a known symptom, never a guessed default fault.
            return self._draft(care)
        if symptom or (place and re.search(r"what about|how about|check there|check|test", q)):
            if not self.issue.get("place"):
                return self._reply("Is that happening at home, work or the gym?")
            return care.concierge(f"Test my connection at {self.issue['place']}", self.messages, True, page)
        if place and re.fullmatch(r"(?:at |the |my )?(?:home|work|gym)", q) and self.issue.get("symptom"):
            self.issue["place"] = place
            return care.concierge(f"Test my connection at {place}", self.messages, True, page)
        context = json.dumps({"current_issue": self.issue, "last_action": self.last_action,
                              "completed_actions": [{k: a.get(k) for k in ("status", "type", "label", "reference", "setting", "value")}
                                                    for a in reversed(self.completed_actions)],
                              "earlier_customer_statements": self.summary}, ensure_ascii=False)
        return care.concierge(text, self.messages, True, page, memory_context=context)
