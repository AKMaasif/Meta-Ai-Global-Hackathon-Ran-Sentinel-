const { api, esc } = UI;
const app = document.getElementById("app");
let toastTimer = null, lastTop = null, supportUnread = 0;
const chat = [];
const ui = { place: "home", report: { place: "home", symptom: "no_service" } };

const I = {
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  net: '<path d="M2 20h2M6 20v-4M10 20v-8M14 20v-12M18 20V4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
  bill: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  help: '<path d="M4 5h16v11H9l-5 4z"/><path d="M9 10h.01M12 10h.01M15 10h.01"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  wifi: '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1"/>',
  msg: '<path d="M4 5h16v11H9l-5 4z"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  card: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
  pin: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
  bag: '<path d="M5 8h14l-1 13H6z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>',
  check: '<path d="M5 12l5 5 9-10"/>',
  down: '<path d="M12 4v12M6 11l6 6 6-6M5 20h14"/>',
  gift: '<rect x="3" y="9" width="18" height="12" rx="1"/><path d="M3 13h18M12 9v12M12 9c-2-4-6-4-6-1s6 1 6 1 6 2 6-1-4-3-6 1"/>',
  phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  watch: '<rect x="7" y="6" width="10" height="12" rx="3"/><path d="M9 6l1-4h4l1 4M9 18l1 4h4l1-4"/>',
  router: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 17h.01M11 17h.01M8 9a6 6 0 0 1 8 0M5.5 6.5a10 10 0 0 1 13 0"/>',
  send: '<path d="M4 12l16-8-6 16-2-7z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
};
const ic = (k, s = 20) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[k]}</svg>`;
const clock = (iso) => { if (!iso) return ""; const h = +iso.slice(11, 13), m = iso.slice(14, 16); return `${h % 12 || 12}:${m} ${h < 12 ? "AM" : "PM"}`; };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const date = (iso) => (iso ? `${MONTHS[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}` : "");
const money = (n) => `$${Number(n).toFixed(2)}`;
const KIND = { normal: ["ok", "Normal"], degraded: ["warn", "Slower service"], outage: ["bad", "Service problem"], restored: ["ok", "Restored"] };
const pill = (k) => `<span class="pill ${KIND[k][0]}">${KIND[k][1]}</span>`;
const sig = (k) => `<span class="sig ${k}" aria-hidden="true"><i></i><i></i><i></i><i></i></span>`;
const conf = (c) => `<span class="conf" title="Confidence: ${c}">${[1, 2, 3].map((i) => `<i class="${i <= { low: 1, medium: 2, high: 3 }[c] ? "on" : ""}"></i>`).join("")}</span>`;
function guard(fn) { return fn().catch((e) => { if (e.status === 401) location.hash = "#/login"; else { console.error(e); toast("Something went wrong", e.message); } }); }
function toast(title, body) {
  document.querySelector(".toast")?.remove();
  const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status");
  t.innerHTML = `<b>${esc(title)}</b>${body ? `<span>${esc(body)}</span>` : ""}`;
  document.body.appendChild(t); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.remove(), 4500);
}
function keepScroll(render) { const y = window.scrollY; render(); window.scrollTo(0, y); }

function shell(active, inner, head) {
  const h = head || {};
  return `<div class="app">
    <header class="topbar">${h.back ? `<a class="back" href="${h.back}" aria-label="Back">‹</a>` : `<a class="avatar" href="#/account" aria-label="Account">JR</a>`}
      <div class="who"><b>${esc(h.title || "Northstar Connect")}</b>${h.sub ? `<span>${esc(h.sub)}</span>` : ""}</div>
      <a class="iconbtn" href="#/notifications" aria-label="Notifications">${ic("bell", 22)}<span id="badge"></span></a></header>
    ${inner}
    <nav class="tabbar" aria-label="Main">${[["home", "Home", "home"], ["network", "Network", "net"], ["account", "Account", "user"], ["bill", "Bill", "bill"], ["help", "Help", "help"]]
      .map(([r, l, k]) => `<a href="#/${r}" class="${active === r ? "on" : ""}" ${active === r ? 'aria-current="page"' : ""}>${ic(k, 22)}${l}${r === "help" && supportUnread ? `<span class="dot" aria-label="New reply from the care team"></span>` : ""}</a>`).join("")}</nav></div>`;
}
function badge(n) { const b = document.getElementById("badge"); if (b) b.outerHTML = `<span id="badge">${n ? `<span class="badge">${n > 9 ? "9+" : n}</span>` : ""}</span>`; }
function notice(home) {
  const top = home.notifications[0];
  if (top && lastTop && top.id !== lastTop) toast(top.title, top.body);
  if (top) lastTop = top.id;
  badge(home.unread);
  if ((home.support_unread || 0) !== supportUnread) {
    supportUnread = home.support_unread || 0;
    const a = document.querySelector('.tabbar a[href="#/help"]');
    if (a) { a.querySelector(".dot")?.remove(); if (supportUnread) a.insertAdjacentHTML("beforeend", '<span class="dot" aria-label="New reply from the care team"></span>'); }
  }
}

const view = { set html(h) { if (app.querySelector(".app")) UI.morph(app, h); else app.innerHTML = h; } };
let offline = false;
const poll = UI.poller({ onState: (s) => {
  if (!s.ok) console.error("refresh failed:", s.error);
  if (!s.ok && !offline) { offline = true; toast("Connection lost", "Showing the last update. Retrying…"); }
  if (s.ok && offline) { offline = false; toast("Back online", "Your network status is up to date."); }
} });
const fatal = (e) => { if (e.status === 401) location.hash = "#/login"; else console.error(e); };
function route() {
  const [p, arg] = (location.hash.replace(/^#\/?/, "") || "home").split("/");
  const pages = { home, network: () => network(arg), account, bill, help: () => (arg ? article(arg) : help()), assistant, support: () => (arg === "new" ? supportNew() : arg ? supportTicket(arg) : supportList()), notifications, report, shop };
  voice.show(p !== "login");
  if (p === "login") { poll.stop(); voice.clearLocal(); return login(); }
  const fn = pages[p] || home;
  if (["home", "network", "notifications", "bill"].includes(p) || (p === "support" && arg && arg !== "new") || !pages[p]) return poll.start(fn, 5000, fatal);
  guard(fn);
  poll.start(async () => notice(await api("/api/care/home")), 8000, fatal);
}
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });
function login() {
  app.innerHTML = `<div class="login"><div class="brandmark"><span class="mk">NC</span>Northstar Connect</div>
    <p class="muted" style="text-align:center">Your account, your network and an AI care team, in one app.</p>
    <form id="f" class="grid" style="gap:12px"><div class="field"><label for="em">Email</label><input id="em" type="email" value="customer@northstar.demo" autocomplete="username" required></div>
    <div class="field"><label for="pw">Password</label><input id="pw" type="password" placeholder="CUSTOMER_PASSWORD from your .env file" autocomplete="current-password" required></div>
    <p id="err" class="err" hidden></p><button class="b block">Sign in</button></form>
    <p class="muted-note">Demo app for a fictional carrier. No real account, payment or network.<br>Engineers: <a href="/ops/">RAN Sentinel Operations</a></p></div>`;
  document.getElementById("f").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/login", { body: { email: document.getElementById("em").value, password: document.getElementById("pw").value, portal: "connect" } }); location.hash = "#/home"; }
    catch (x) { const err = document.getElementById("err"); err.hidden = false; err.innerHTML = esc(x.message) + (x.portal === "ops" ? ` <a href="/ops/">Open RAN Sentinel Operations</a>` : ""); }
  };
}

function worstPlace(places) {
  const rank = { outage: 3, degraded: 2, normal: 0 };
  return [...places].sort((a, b) => rank[b.status] - rank[a.status] || (b.recently_restored ? 1 : 0) - (a.recently_restored ? 1 : 0))[0];
}
function heroCard(p) {
  const i = p.issue || p.recently_restored;
  if (!i) return `<section class="hero normal"><div class="row" style="display:flex;gap:10px;align-items:center">${sig("normal")}<span class="t">All good at your places</span></div>
    <p class="muted">No known network problems at Home, Work or Gym. We'll tell you first if that changes.</p></section>`;
  const k = p.issue ? p.status : "restored";
  const cur = i.journey.find((j) => j.state === "current");
  return `<section class="hero ${k}" aria-live="polite"><div style="display:flex;justify-content:space-between;gap:10px;align-items:center">${pill(k)}<span class="small muted">Updated ${clock(i.updated)} PT</span></div>
    <div class="t">${k === "restored" ? `Service is back at ${esc(p.label)}` : `${k === "outage" ? "Service problem" : "Slower service"} at ${esc(p.label)}`}</div>
    <p>${esc(k === "restored" ? "Thanks for your patience. If your phone still has trouble, turn Airplane mode on and off." : `${i.cause} ${i.impact}`)}</p>
    ${k !== "restored" ? `<div class="progress" aria-label="Progress: ${esc(cur ? cur.label : "")}">${i.journey.map((j) => `<i class="${j.state}"></i>`).join("")}</div>
    <div class="small"><b>${esc(cur ? cur.label : "")}</b> · step ${i.stage + 1} of 6</div>
    <div class="eta">${ic("clock", 22)}<div><b>${esc(i.eta.text || "")}</b><div class="small muted">Estimate ${conf(i.eta.confidence)} ${esc(i.eta.confidence)} confidence</div></div></div>` : ""}
    <div class="btns"><a class="b sm" href="#/network/${p.id}">See details</a><a class="b sm ghost" href="#/assistant">Ask the assistant</a></div></section>`;
}
function suggList(list, limit = 3) {
  if (!list.length) return "";
  return `<div class="sugg-list">${list.slice(0, limit).map((s) => `<div class="sugg"><span class="ic">${ic(s.id === "wifi_calling" ? "wifi" : s.id === "texts" ? "msg" : s.id === "offline" ? "down" : "bolt", 18)}</span>
    <b>${esc(s.title)}</b><p>${esc(s.text)}</p>${s.action ? `<div class="btns"><button class="b sm soft" data-set="${esc(s.action.setting)}">Turn on</button></div>` : ""}</div>`).join("")}</div>`;
}
function bindSugg(after) {
  document.querySelectorAll("[data-set]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    await api("/api/care/prefs", { body: { key: b.dataset.set, value: true } });
    toast("Done", b.dataset.set === "wifi_calling" ? "Wi-Fi Calling is on." : "Data Saver is on.");
    after();
  }));
}
async function home() {
  const h = await api("/api/care/home");
  const a = h.account, w = worstPlace(h.places);
  const used = a.lines.reduce((s, l) => s + l.data_used_gb, 0);
  const credit = h.credits.find((c) => c.eligible);
  keepScroll(() => {
    view.html = shell("home", `<div class="hero-band"></div><div class="page" style="padding-top:12px">
      ${heroCard(w)}
      ${credit ? `<section class="card" style="background:#fff8e6;border-color:#f1d6a6"><div class="row"><div><b>A ${money(credit.amount)} credit is ready</b><p class="small">For the outage at your ${esc(credit.place)}. No call needed.</p></div><a class="b sm" href="#/bill">Apply</a></div></section>` : ""}
      <div class="sect"><h2>Your places</h2><a href="#/account">Edit</a></div>
      <div class="places">${h.places.map((p) => `<a class="place" href="#/network/${p.id}"><div style="display:flex;justify-content:space-between;align-items:center"><b>${esc(p.label)}</b>${sig(p.status)}</div>
        <span>${esc(p.area)}</span><span style="color:var(--${KIND[p.status][0] === "ok" ? "ok" : KIND[p.status][0]})">${KIND[p.status][1]}</span></a>`).join("")}</div>
      <div class="duo"><a class="card" href="#/bill" style="text-decoration:none;color:inherit"><span class="label">Balance due</span><span class="big">${money(a.bill.balance_after_credits)}</span>
        <span class="small muted">Due ${date(a.bill.due)} · AutoPay ${a.bill.autopay ? "on" : "off"}</span></a>
        <a class="card" href="#/account" style="text-decoration:none;color:inherit"><span class="label">Data this cycle</span><span class="big">${used.toFixed(1)} <span style="font-size:15px">GB</span></span>
        <span class="small muted">Unlimited · ${a.lines.length} lines</span></a></div>
      <div class="quick">
        <a href="#/bill"><span class="ic">${ic("card")}</span>Pay bill</a>
        <a href="#/network"><span class="ic">${ic("net")}</span>Network</a>
        <a href="#/report"><span class="ic">${ic("flag")}</span>Report a problem</a>
        <button id="q-wifi"><span class="ic">${ic("wifi")}</span>Wi-Fi Calling ${h.prefs.wifi_calling ? "on" : "off"}</button>
        <a href="#/assistant"><span class="ic">${ic("spark")}</span>Ask AI</a>
        <a href="#/shop"><span class="ic">${ic("bag")}</span>Shop</a></div>
      ${w.suggestions.length ? `<div class="sect"><h2>For you right now</h2></div><section class="card">${suggList(w.suggestions)}</section>` : ""}
      <a class="aistrip" href="#/assistant">${ic("spark", 26)}<div><b>Your AI care team</b><span>Watching ${h.places.length} places · ${h.engine === "meta" ? "Meta Muse models" : "offline rules (no Meta key)"}</span></div><span class="go">›</span></a>
      ${h.notifications.length ? `<div class="sect"><h2>Latest from us</h2><a href="#/notifications">See all</a></div><section class="card">${h.notifications.slice(0, 2).map(noteItem).join("")}</section>` : ""}
      <section class="perk"><b>Northstar Perks</b><span>Thanks for being with us since ${esc(a.member_since)}. New member perks every Thursday.</span></section>
      <p class="muted-note">Demo app for a fictional carrier. Network times are simulated, in ${esc(h.timezone)}.</p></div>`,
      { title: `Hi, ${a.first_name}`, sub: `Account ${a.account}` });
  });
  notice(h);
  bindSugg(() => poll.now());
  document.getElementById("q-wifi").onclick = async () => {
    await api("/api/care/prefs", { body: { key: "wifi_calling", value: !h.prefs.wifi_calling } });
    toast(`Wi-Fi Calling ${h.prefs.wifi_calling ? "off" : "on"}`); poll.now();
  };
}

function issueDetail(p) {
  const i = p.issue || p.recently_restored;
  if (!i) return `<section class="card"><div class="row"><h2>${esc(p.label)} · ${esc(p.area)}</h2>${pill("normal")}</div>
    <p>No known network problems here. If your phone isn't working well, tell us and we'll check your line and the network together.</p>
    <a class="b ghost block" href="#/report">Report a problem here</a></section>`;
  const k = p.issue ? p.status : "restored";
  return `<section class="card"><div class="row"><h2>${esc(p.label)} · ${esc(p.area)}</h2>${pill(k)}</div>
      <p><b>${esc(i.headline)}</b></p>
      <div class="kv"><span class="muted">What's happening</span><span></span></div><p style="margin-top:-6px">${esc(i.cause)}</p>
      <div class="kv"><span class="muted">What you may notice</span><span></span></div><p style="margin-top:-6px">${esc(i.impact)}</p>
      ${k !== "restored" ? `<div class="etabox"><span class="label">Estimated back to normal</span><span class="when">${clock(i.eta.from)} to ${clock(i.eta.to)} PT</span>
        <span class="small">${conf(i.eta.confidence)} ${esc(i.eta.confidence)} confidence · ${esc(i.eta.basis)}</span></div>` : ""}
      <span class="label">Progress</span>
      <div class="journey">${i.journey.map((j) => `<div class="step ${j.state}"><span class="k">${j.state === "done" ? ic("check", 12) : ""}</span><span>${esc(j.label)}</span></div>`).join("")}</div>
      <div class="small muted">Reference ${esc(i.reference)} · started ${clock(i.started)} PT</div>
      <a class="b ghost block" href="#/report">I'm affected: tell engineers</a></section>
    ${p.suggestions.length ? `<section class="card"><h2>What you can do now</h2>${suggList(p.suggestions, 4)}</section>` : ""}
    ${i.history.length ? `<section class="card"><h2>Updates from our engineers</h2><div class="list">${i.history.map((u) => `<div class="li"><span>${esc(u.text)}</span><span class="small muted">${clock(u.at)}</span></div>`).join("")}</div></section>` : ""}`;
}
async function network(arg) {
  if (arg) ui.place = arg;
  const pid = ui.place;
  const [n, mp, sg] = await Promise.all([api("/api/care/network"), api("/api/care/map?place=" + encodeURIComponent(pid)).catch(() => null),
    api("/api/care/signal?place=" + encodeURIComponent(pid)).catch(() => null)]);
  const p = n.places.find((x) => x.id === ui.place) || n.places[0];
  keepScroll(() => {
    view.html = shell("network", `<div class="page" style="padding-top:12px">
      <div class="places">${n.places.map((x) => `<a class="place ${x.id === p.id ? "on" : ""}" href="#/network/${x.id}"><div style="display:flex;justify-content:space-between;align-items:center"><b>${esc(x.label)}</b>${sig(x.status)}</div><span>${esc(x.area)} ${esc(x.zip)}</span></a>`).join("")}</div>
      ${issueDetail(p)}
      ${signalCard(sg, p)}
      <div class="sect"><h2>Towers near your ${esc(p.label)}</h2></div>
      <div class="mapwrap"><div id="cgeoslot" class="cgeoslot" data-keep></div>
        <div class="legend"><span><i style="background:#0d5257;box-shadow:0 0 0 2px #9fd3d3"></i>Connected</span><span><i style="background:var(--ok)"></i>Available</span><span><i style="background:var(--warn)"></i>Problem</span><span><i style="background:var(--bad)"></i>Unavailable</span><span><i style="background:#fff;box-shadow:inset 0 0 0 2px #0d5257"></i>Your phone</span></div>
        <p class="small muted" style="padding:0 14px 12px">${mp ? `Only towers within ${mp.radius_km} km of your ${esc(p.label)}. Drag your phone to see how the signal changes nearby. ${esc(mp.source.label)}` : "Map unavailable right now."}</p></div>
      <section class="card"><h2>All neighborhoods</h2><div class="list">${n.areas.map((a) => `<div class="li"><span><b>${esc(a.area)}</b> <span class="small muted mono">${esc(a.zip)}</span>${a.issue ? `<div class="sub">${esc(a.issue.eta.text || "")}</div>` : ""}</span>${pill(a.status)}</div>`).join("")}</div></section>
      ${n.reports.length ? `<section class="card"><h2>Your reports</h2><div class="list">${n.reports.map((r) => `<div class="li"><span><b>${esc(r.symptom)} · ${esc(r.place)}</b><div class="sub">${esc(r.outcome === "linked" ? "Added to the engineers' open repair" : "Checked: no network problem found")}</div></span><span class="small muted mono">${esc(r.id)}</span></div>`).join("")}</div></section>` : ""}
      </div>`, { title: "Network", sub: "Live status for your places" });
  });
  bindSugg(() => poll.now());
  bindSignal(p);
  customerMap(mp);
  guard(async () => notice(await api("/api/care/home")));
}

const QCOL = { excellent: "ok", good: "ok", fair: "warn", poor: "bad", disconnected: "bad", unknown: "info" };
const QTEXT = { excellent: "Excellent", good: "Good", fair: "Fair", poor: "Poor", disconnected: "Disconnected", unknown: "Unknown" };
const QBARS = { excellent: 4, good: 3, fair: 2, poor: 1, disconnected: 0, unknown: 0 };
function spark(vals, lowerBetter) {
  const v = vals.filter((x) => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), W = 90, H = 24;
  const pts = vals.map((x, i) => x == null ? null : `${(i / (vals.length - 1)) * W},${H - 2 - ((x - lo) / (hi - lo || 1)) * (H - 4)}`).filter(Boolean).join(" ");
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.6"/></svg>`;
}
function browserNet() {
  const c = navigator.connection;
  if (!c || c.effectiveType == null) return `<span class="muted">Your browser doesn't report network details.</span>`;
  return `<span>${esc(String(c.effectiveType).toUpperCase())}-class link · about ${c.downlink ?? "?"} Mbps · ${c.rtt ?? "?"} ms round trip</span><span class="small muted">Reported by your browser for whatever connection this device is using (often Wi-Fi). It is not a cellular measurement.</span>`;
}
function signalCard(sg, p) {
  if (!sg) return `<section class="card"><h2>Your connection</h2><p class="muted">Signal measurements are unavailable right now.</p></section>`;
  const q = sg.quality, ex = (ui.explain || {})[p.id];
  const m = sg.metrics;
  return `<section class="card" aria-live="polite"><div class="row"><h2>Your connection at ${esc(sg.place)}</h2><span class="pill plain info">Simulated</span></div>
    <div class="qhead"><div class="qbars ${QCOL[q]}" aria-hidden="true">${[1, 2, 3, 4].map((i) => `<i class="${i <= QBARS[q] ? "on" : ""}"></i>`).join("")}</div>
      <div><span class="qlabel ${QCOL[q]}">${QTEXT[q]}</span><div class="small muted">${esc(sg.connection === "disconnected" ? "No usable signal" : `${sg.technology} · ${sg.band}`)}${sg.drivers.length && !["excellent", "good"].includes(q) ? ` · limited by ${esc(sg.drivers.join(", "))}` : ""}</div></div></div>
    ${sg.serving ? `<div class="kv"><span class="muted">Serving tower</span><span>${esc(sg.serving.name)}</span><span class="muted">Distance</span><span>${sg.serving.distance_km} km</span>
      ${sg.alternatives.length ? `<span class="muted">Other towers in range</span><span>${sg.alternatives.map((a) => esc(a.name.replace("Northstar tower · ", ""))).join(", ")}</span>` : ""}
      <span class="muted">Tower changes, last 3 h</span><span>${sg.tower_changes}</span><span class="muted">Updated</span><span>${clock(sg.at)} PT</span></div>` : ""}
    <div class="metrics">${Object.entries(m).map(([k, v]) => `<div class="metric"><span class="small muted">${esc(v.name)}</span>
      <span class="mv">${v.value == null ? `<span class="muted">Unavailable</span>` : `${v.value} <small>${esc(v.unit)}</small>`}</span>
      <span class="pill plain ${QCOL[v.rating]}">${QTEXT[v.rating]}</span>${spark(sg.series.map((x) => x[k] ?? null))}</div>`).join("")}</div>
    ${sg.issue ? `<p class="small"><b>Known problem nearby:</b> ${esc(sg.issue.cause)} ${esc(sg.issue.eta || "")}</p>` : ""}
    <div class="sugg-list">${sg.guidance.map((g) => `<div class="sugg"><span class="ic">${ic("bolt", 18)}</span><p style="grid-row:span 3;align-self:center">${esc(g)}</p></div>`).join("")}</div>
    <div class="ai-box">${ex ? explainBlock(ex) : `<div class="row"><span><b>Signal intelligence</b><div class="small muted">Meta Muse Spark reads these measurements and explains them</div></span><button class="b sm" id="explain" ${ui.reading && ui.reading === p.id ? "disabled" : ""}>${ui.reading && ui.reading === p.id ? "Reading…" : "Explain"}</button></div>`}</div>
    <details class="how"><summary>About these numbers</summary><p class="small">${esc(sg.source.label)} Model: ${esc(sg.source.model)}. Ratings use a separate scale per metric (for example RSRP excellent at -80 dBm or better, SINR excellent at 20 dB or better, latency excellent under 50 ms).</p>
      <p class="small" style="margin-top:6px"><b>This device:</b> ${browserNet()}</p></details></section>`;
}
function explainBlock(e) {
  const list = (t, xs) => xs && xs.length ? `<div><span class="label">${t}</span><ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
  return `<div class="row"><b>Signal intelligence</b><span class="by">${esc(e.by.startsWith("muse") ? e.by.replace("muse-spark-", "Muse Spark ") : e.by === "template" ? "fixed rules (no Meta key set)" : "fixed rules (AI unavailable)")}</span></div>
    <p>${esc(e.summary)}</p>${list("Confirmed by the measurements", e.confirmed)}${list("Probable", e.probable)}${list("Not verified", e.unverified)}${list("What to try", e.steps)}
    <span class="small muted">An interpretation, not a measurement. The numbers above are the source of truth.</span>`;
}
function bindSignal(p) {
  const b = document.getElementById("explain");
  if (!b) return;
  b.onclick = async () => {
    if (ui.reading) return;
    ui.reading = p.id; b.disabled = true; b.textContent = "Reading…";
    try { const e = await api("/api/care/signal/explain", { body: { place: p.id } }); ui.explain = { ...(ui.explain || {}), [p.id]: e }; }
    catch (e) { toast("Couldn't explain", e.message); }
    finally { ui.reading = null; }
    poll.now();
  };
}

let cm = null, cmSig = "", cmLayer = null, cmPlace = null;
const TCOL = { connected: "#0d5257", available: "#1d7a46", problem: "#c27a00", unavailable: "#b42318" };
function customerMap(mp) {
  const slot = document.getElementById("cgeoslot");
  if (!slot) return;
  if (!window.L) { slot.innerHTML = `<p class="muted" style="padding:16px">The map couldn't load.</p>`; return; }
  if (!mp || !mp.towers.length) { slot.innerHTML = `<p class="muted" style="padding:16px">No Northstar towers found near this place.</p>`; return; }
  if (!cm) { cm = GeoMap.create({ label: "Towers near your place", minZoom: 12 }); cmLayer = L.layerGroup().addTo(cm.map); }
  GeoMap.mount(cm, slot);
  const b = L.latLngBounds(mp.bounds);
  cm.map.setMaxBounds(b.pad(0.1));
  if (cmPlace !== mp.place.id + mp.place.zip) { cmPlace = mp.place.id + mp.place.zip; cm.map.fitBounds(b.pad(-0.25)); cmSig = ""; }
  const sig = JSON.stringify([mp.place.lat, mp.place.lon, mp.towers.map((t) => [t.key, t.status, t.coverage_km])]);
  if (sig === cmSig) return;
  cmSig = sig;
  cmLayer.clearLayers();
  for (const t of mp.towers) L.circle([t.lat, t.lon], { radius: t.coverage_km * 1000, stroke: false, fillColor: t.status === "unavailable" ? "#b42318" : t.status === "problem" ? "#c27a00" : "#0f7a4d", fillOpacity: .06, interactive: false }).addTo(cmLayer);
  const serving = mp.towers.find((t) => t.serving);
  if (serving) L.polyline([[mp.place.lat, mp.place.lon], [serving.lat, serving.lon]], { color: "#0d5257", weight: 2.5, dashArray: "6 6" }).addTo(cmLayer);
  L.circle(mp.place.center, { radius: mp.place.move_radius_km * 1000, color: "#0d5257", weight: 1, dashArray: "3 5", fill: false, interactive: false }).addTo(cmLayer);
  for (const t of mp.towers) {
    const label = { connected: "Connected (your phone uses this tower)", available: "Available", problem: "Service problem reported", unavailable: "Unavailable: repair underway" }[t.status];
    L.circleMarker([t.lat, t.lon], { radius: t.serving ? 10 : 7, color: t.serving ? "#9fd3d3" : "#fff", weight: t.serving ? 4 : 2, fillColor: TCOL[t.status], fillOpacity: 1, dashArray: t.alternative ? "3 3" : null })
      .bindTooltip(`${esc(t.name)}<br>${esc(label)}`, { direction: "top" })
      .bindPopup(`<div class="sitepop"><b>${esc(t.name)}</b><span>${esc(label)}${t.alternative ? " · backup tower in range" : ""}</span><span class="small">${esc(t.technology)} · ${esc(t.bands.join(", "))}</span><span class="small muted">${t.distance_km} km from your phone · modelled reach ${t.coverage_km} km</span></div>`)
      .addTo(cmLayer);
  }
  const phone = L.marker([mp.place.lat, mp.place.lon], { draggable: true, keyboard: true, title: "Your phone (drag to move)", alt: "Your phone",
    icon: L.divIcon({ className: "", iconSize: [34, 34], iconAnchor: [17, 17], html: `<div class="phonemk">${ic("phone", 16)}</div>` }) }).addTo(cmLayer);
  phone.bindTooltip("Your phone · drag to move", { direction: "bottom" });
  phone.on("dragend", async () => {
    const ll = phone.getLatLng();
    try { await api("/api/care/phone", { body: { place: mp.place.id, lat: ll.lat, lon: ll.lng } }); }
    catch (e) { toast("Can't move there", e.message); }
    cmSig = ""; poll.now();
  });
}

async function report() {
  const n = await api("/api/care/network");
  const r = ui.report;
  view.html = shell("network", `<div class="page" style="padding-top:12px">
    <section class="card"><h2>Report a problem</h2><p class="small muted">We check the network at that place first. If engineers are already fixing it, your report is added to their repair as evidence. If not, we help you check your phone.</p>
      <form id="rf" class="grid" style="gap:14px">
        <div><span class="label">Where?</span><div class="chips" style="margin-top:6px">${n.places.map((p) => `<label><input type="radio" name="place" value="${p.id}" ${p.id === r.place ? "checked" : ""}><span>${esc(p.label)} · ${esc(p.area)}</span></label>`).join("")}</div></div>
        <div><span class="label">What's wrong?</span><div class="chips" style="margin-top:6px">${Object.entries(n.symptoms).map(([k, v]) => `<label><input type="radio" name="sym" value="${k}" ${k === r.symptom ? "checked" : ""}><span>${esc(v)}</span></label>`).join("")}</div></div>
        <div class="field"><label for="det">Anything else? (optional)</label><textarea id="det" class="ta" maxlength="300" placeholder="For example: no signal indoors since noon">${esc(r.details || "")}</textarea></div>
        <button class="b block">Send report</button></form></section>
    <div id="rres"></div></div>`, { title: "Report a problem", back: "#/network" });
  badge(0);
  document.getElementById("rf").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    if (ui.report.actionId) {
      voice.end();
      await api("/api/care/voice/cancel", { body: { action_id: ui.report.actionId } });
    }
    ui.report = { place: f.get("place"), symptom: f.get("sym") };
    const res = await api("/api/care/report", { body: { place: ui.report.place, symptom: ui.report.symptom, details: document.getElementById("det").value } });
    document.getElementById("rres").innerHTML = `<section class="card" style="border-color:var(--brand)"><div class="row"><h2>${res.outcome === "linked" ? "Added to the repair" : "Let's check your phone"}</h2><span class="pill plain info mono">${esc(res.id)}</span></div>
      <p>${esc(res.text)}</p>${suggList(res.suggestions, 4)}</section>`;
    bindSugg(() => {});
    document.getElementById("rres").scrollIntoView({ behavior: "smooth" });
  };
}

async function account() {
  const d = await api("/api/care/account");
  const a = d.account;
  view.html = shell("account", `<div class="page" style="padding-top:12px">
    <section class="card"><div class="row"><div style="display:flex;gap:12px;align-items:center"><span class="avatar" style="background:var(--brand);color:#fff;width:48px;height:48px;font-size:17px">JR</span>
      <div><b style="font-size:17px">${esc(a.name)}</b><div class="small muted">Account ${esc(a.account)} · member since ${esc(a.member_since)}</div></div></div></div></section>
    <div class="sect"><h2>Lines and devices</h2></div>
    <section class="card"><div class="list">${a.lines.map((l) => `<div class="li"><span style="display:flex;gap:12px;align-items:center"><span class="quick" style="display:block"><span class="ic" style="width:38px;height:38px;border-radius:50%;background:var(--brand-soft);color:var(--brand);display:grid;place-items:center">${ic(l.kind === "watch" ? "watch" : "phone")}</span></span>
      <span><b>${esc(l.name)}</b><div class="sub">${esc(l.number)} · ${esc(l.device)}</div></span></span><span class="small mono">${l.data_used_gb} GB</span></div>`).join("")}</div>
      <span class="small muted">Billing cycle ${date(a.cycle.start)} to ${date(a.cycle.end)} · hotspot ${a.lines.reduce((s, l) => s + l.hotspot_used_gb, 0).toFixed(1)} of ${a.plan.hotspot_gb} GB</span>
      <div class="bar"><i style="width:${Math.min(100, a.lines.reduce((s, l) => s + l.hotspot_used_gb, 0) / a.plan.hotspot_gb * 100)}%"></i></div></section>
    <div class="sect"><h2>Your plan</h2><a href="#/shop">Change plan</a></div>
    <section class="card"><div class="row"><b>${esc(a.plan.name)}</b><span class="mono">${money(a.plan.price)}/mo</span></div>
      <ul style="margin:0;padding-left:18px;font-size:14px">${a.plan.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></section>
    <div class="sect"><h2>Settings</h2></div>
    <section class="card"><div class="list">${Object.entries(d.settings).map(([k, v]) => `<label class="li" style="cursor:pointer"><span><b>${esc(v)}</b><div class="sub">${esc({ wifi_calling: "Calls and texts over Wi-Fi when the signal is weak", data_saver: "Smoother streaming when the network is busy", network_alerts: "Tell me first about problems at my places", eta_updates: "Send progress and recovery-time updates" }[k])}</div></span>
      <input type="checkbox" class="toggle" data-pref="${k}" ${d.prefs[k] ? "checked" : ""}></label>`).join("")}</div></section>
    <div class="sect"><h2>My places</h2></div>
    <section class="card"><p class="small muted">We watch the network at these places and tell you first when something is wrong.</p><div class="list">${d.places.map((p) => `<div class="li"><span><b>${esc(p.label)}</b></span>
      <select class="sel" data-place="${p.id}" aria-label="${esc(p.label)} neighborhood">${d.areas.map((x) => `<option value="${x.zip}" ${x.zip === p.zip ? "selected" : ""}>${esc(x.area)} ${x.zip}</option>`).join("")}</select></div>`).join("")}</div></section>
    <section class="card"><h2>AI and your data</h2><p class="small">Northstar's AI care team runs on Meta's Muse models. It only reads your own account and the network updates our engineers have published. It suggests; you confirm every change. We don't send your data to model versions that train on it.</p></section>
    <button class="b ghost block" id="out">Sign out</button>
    <p class="muted-note">Demo account for a fictional carrier.</p></div>`, { title: "Account" });
  guard(async () => notice(await api("/api/care/home")));
  document.querySelectorAll("[data-pref]").forEach((t) => (t.onchange = async () => { await api("/api/care/prefs", { body: { key: t.dataset.pref, value: t.checked } }); toast("Saved", `${d.settings[t.dataset.pref]} ${t.checked ? "on" : "off"}.`); }));
  document.querySelectorAll("[data-place]").forEach((s) => (s.onchange = async () => { await api("/api/care/places", { body: { place: s.dataset.place, zip: s.value } }); toast("Place updated", "We'll watch the network there for you."); }));
  document.getElementById("out").onclick = async () => { await api("/api/logout", { body: {} }); location.hash = "#/login"; };
}

async function bill() {
  const d = await api("/api/care/account");
  const b = d.account.bill;
  const eligible = d.credits.filter((c) => c.eligible);
  keepScroll(() => {
    view.html = shell("bill", `<div class="page" style="padding-top:12px">
      <section class="card"><span class="label">Balance due</span><span class="big" style="font-size:36px">${money(b.balance_after_credits)}</span>
        <span class="small muted">Due ${date(b.due)} · AutoPay ${b.autopay ? `on with ${esc(b.card)}` : "off"}</span>
        <div class="btns"><button class="b" id="pay">Pay now</button><button class="b ghost" id="ap">AutoPay settings</button></div></section>
      ${eligible.map((c) => `<section class="card" style="background:#fff8e6;border-color:#f1d6a6"><div class="row"><div><b>${money(c.amount)} outage credit</b><p class="small">${esc(c.place)} · ${esc(c.area)} · ${c.outage_minutes} min outage. ${esc(c.rule)}.</p></div><button class="b sm" data-credit="${esc(c.reference)}">Apply</button></div></section>`).join("")}
      <div class="sect"><h2>This bill</h2></div>
      <section class="card"><div class="kv">${b.items.map((i) => `<span>${esc(i.label)}</span><span>${money(i.amount)}</span>`).join("")}
        ${d.applied.map((c) => `<span>Outage credit (${esc(c.place)})</span><span style="color:var(--ok)">−${money(c.amount)}</span>`).join("")}</div>
        <div class="divider"></div><div class="kv"><b>Total</b><b style="text-align:right">${money(b.balance_after_credits)}</b></div></section>
      <div class="sect"><h2>Outage credits</h2></div>
      <section class="card"><p class="small">If service at one of your places is down for ${d.credit_policy.minutes} minutes or more, you get a ${money(d.credit_policy.amount)} credit for it, offered automatically. A fixed rule decides this, not the AI.</p>
        ${d.applied.length ? `<div class="list">${d.applied.map((c) => `<div class="li"><span><b>${money(c.amount)} applied</b><div class="sub">${esc(c.place)} · ${esc(c.reference)}</div></span><span class="pill ok">Applied</span></div>`).join("")}</div>` : ""}</section>
      <div class="sect"><h2>Payment history</h2></div>
      <section class="card"><div class="list">${b.history.map((h) => `<div class="li"><span><b>${date(h.date)}</b><div class="sub">${esc(h.status)}</div></span><span class="mono">${money(h.amount)}</span></div>`).join("")}</div></section>
      <p class="muted-note">Demo app: no payments are taken.</p></div>`, { title: "Bill" });
  });
  guard(async () => notice(await api("/api/care/home")));
  document.getElementById("pay").onclick = () => toast("Demo app", "No payments are taken in this demo.");
  document.getElementById("ap").onclick = () => toast("Demo app", "AutoPay is on with the card on file.");
  document.querySelectorAll("[data-credit]").forEach((x) => (x.onclick = async () => {
    x.disabled = true;
    const r = await api("/api/care/credit", { body: { reference: x.dataset.credit } });
    toast("Credit applied", `${money(r.amount)} comes off your next bill.`); poll.now();
  }));
}

function noteItem(n) {
  const k = { alert: "net", progress: "clock", restored: "check", credit: "gift" }[n.kind] || "bell";
  return `<a class="note ${n.kind} ${n.read ? "" : "unread"}" href="${n.kind === "credit" ? "#/bill" : "#/network"}"><span class="ic">${ic(k, 18)}</span>
    <b>${esc(n.title)}</b><p>${esc(n.body)}</p><time>${date(n.at)}, ${clock(n.at)} PT</time></a>`;
}
async function notifications() {
  const d = await api("/api/care/notifications");
  keepScroll(() => {
    view.html = shell("", `<div class="page" style="padding-top:12px"><section class="card">${d.items.length ? d.items.map(noteItem).join("") :
      `<p class="muted">Nothing yet. We'll tell you here first when there's a network problem at your places, how the repair is going, and when it's fixed.</p>`}</section>
      <p class="muted-note">Alerts come from the network team's published updates for Home, Work and Gym.</p></div>`, { title: "Notifications", back: "#/home" });
  });
  if (d.items.some((n) => !n.read)) await api("/api/care/notifications/read", { body: {} });
  badge(0);
}

const LAYERS = [
  ["Listen", "Muse Voice Transcribe", "Turns a spoken question into text. You check it before it's sent."],
  ["Care Concierge", "Muse Spark 1.3 (1.2, 1.1 as backup)", "Plans the answer and calls tools that see only your account and your places. In a voice conversation it also runs the app for you."],
  ["Speak", "Gemini TTS (your browser's voice as backup)", "Reads answers aloud in a natural voice. It only gets the answer text, never your account."],
  ["Network Explainer", "Muse Spark 1.3", "Writes updates in plain words from facts engineers have approved."],
  ["Recovery Estimator", "Fixed rules, no AI", "Estimates when service is back from the repair stage and typical repair times."],
  ["Personal Advisor", "Fixed rules, no AI", "Suggests what helps you now, like Wi-Fi Calling or Data Saver."],
  ["Guardrails", "Fixed rules, no AI", "Blocks technical or internal details, applies the credit rule, and waits for you to confirm any change."],
];
const byLabel = (b) => b === "instant" ? "Done instantly (a simple command, no AI needed)" : b.startsWith("muse") ? `Answered by ${b.replace("muse-spark-", "Muse Spark ")}` :
  b === "rules" ? "Answered by fixed rules (no Meta key set)" : "Answered by fixed rules (AI unavailable right now)";
function bubble(m, i) {
  if (m.who === "me") return `<div class="bubble me">${esc(m.text)}</div>`;
  return `<div class="bubble bot"><span>${esc(m.text)}</span>
    ${(m.actions || []).length ? `<div class="acts">${m.actions.map((a) => `<div class="act"><b>${esc(a.label)}</b>${a.done ? `<span class="pill ok">${esc(a.done)}</span>` :
      `<div class="btns"><button class="b sm" data-confirm="${esc(a.id)}" data-m="${i}">Confirm</button><button class="b sm ghost" data-skip="${esc(a.id)}" data-m="${i}">Not now</button></div>`}</div>`).join("")}</div>` : ""}
    ${(m.steps || []).length ? `<details class="how"><summary>How I answered (${m.steps.length} steps)</summary><ol>${m.steps.map((s) => `<li>${esc(s.label)}</li>`).join("")}</ol></details>` : ""}
    ${m.by ? `<span class="by">${esc(byLabel(m.by))}</span>` : ""}</div>`;
}
async function assistant() {
  const h = await api("/api/care/home");
  view.html = shell("help", `<div class="page" style="padding-top:12px">
    <section class="card"><div style="display:flex;gap:12px;align-items:center"><span class="avatar" style="background:var(--brand);color:#fff">${ic("spark", 18)}</span>
      <div><b>Northstar assistant</b><div class="small muted">${h.engine === "meta" ? "Powered by Meta Muse models" : "Offline rules (no Meta key set)"} · sees only your account and published network updates</div></div></div></section>
    <div class="prompts">${["When will service be back at home?", "Why is my data slow at work?", "Can I get a credit for the outage?", "Turn on Wi-Fi Calling", "Is there an issue in 98119?", "What's my bill this month?"].map((q) => `<button>${esc(q)}</button>`).join("")}</div>
    <div class="chatlog" id="log">${chat.map(bubble).join("") || `<div class="bubble bot"><span>Hi ${esc(h.account.first_name)}, I can check the network at your places, explain what's happening and when it should be fixed, change settings for you, and apply outage credits. What can I help with?</span></div>`}</div>
    <form class="composer" id="ask"><input id="q" type="text" placeholder="Ask anything, or tap the mic" aria-label="Your question" autocomplete="off">
      <button class="round" type="button" id="mic" title="Ask by voice" aria-label="Ask by voice">${UI.MIC}</button><button class="round send" aria-label="Send">${ic("send", 18)}</button></form>
    <p class="small muted" id="vmsg" hidden></p>
    <div class="sect"><h2>Your AI care team</h2></div>
    <section class="card"><p class="small">Seven layers work on your question. Only the first four use AI; the rest are fixed rules, so estimates, credits and changes stay predictable.</p>
      <div class="team">${LAYERS.map((l, i) => `<div class="layer"><span class="n">${i + 1}</span><div><b>${esc(l[0])}</b> <span class="m">${esc(l[1])}</span></div><p>${esc(l[2])}</p></div>`).join("")}</div></section>
    <section class="card"><h2>Other help</h2><div class="list">
      <a class="li" href="#/help"><span><b>Help center</b><div class="sub">Articles, troubleshooting and frequently asked questions</div></span><span>›</span></a>
      <a class="li" href="#/support/new"><span><b>Contact support</b><div class="sub">Send a request to the care team and follow it in the app</div></span><span>›</span></a>
      <a class="li" href="#/report"><span><b>Report a network problem</b><div class="sub">Goes to our engineers if it matches a repair</div></span><span>›</span></a></div></section></div>`, { title: "Assistant", back: "#/help" });
  notice(h);
  const log = document.getElementById("log");
  const render = () => { log.innerHTML = chat.map(bubble).join(""); bindActs(); log.lastElementChild?.scrollIntoView({ block: "nearest" }); };
  const bindActs = () => {
    log.querySelectorAll("[data-confirm]").forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      const a = chat[+b.dataset.m].actions.find((x) => x.id === b.dataset.confirm);
      try { const r = await api("/api/care/confirm", { body: { action_id: a.id } }); a.done = "Done"; chat.push({ who: "bot", text: r.done }); }
      catch (e) { a.done = "Expired"; chat.push({ who: "bot", text: e.message }); }
      render();
    }));
    log.querySelectorAll("[data-skip]").forEach((b) => (b.onclick = () => { chat[+b.dataset.m].actions.find((x) => x.id === b.dataset.skip).done = "Skipped"; render(); }));
  };
  const send = async (q) => {
    if (!q.trim()) return;
    const history = chat.filter((m) => m.text).slice(-6).map((m) => ({ who: m.who, text: m.text }));
    chat.push({ who: "me", text: q }, { who: "bot", text: "Checking your places and account…" });
    render();
    try { const r = await api("/api/care/concierge", { body: { question: q, history } }); Object.assign(chat[chat.length - 1], { text: r.answer, actions: r.actions, steps: r.steps, by: r.by }); }
    catch (e) { chat[chat.length - 1].text = e.message; }
    render();
  };
  bindActs();
  document.querySelectorAll(".prompts button").forEach((b) => (b.onclick = () => send(b.textContent)));
  document.getElementById("ask").onsubmit = (e) => { e.preventDefault(); const q = document.getElementById("q"); send(q.value); q.value = ""; };
  const vmsg = document.getElementById("vmsg");
  UI.micButton(document.getElementById("mic"), "/api/public/voice", (r) => {
    const q = document.getElementById("q"); q.value = r.text; q.focus();
    vmsg.hidden = false; vmsg.textContent = r.text ? "Check the text, then tap send." : "We didn't catch that. Please try again or type.";
  }, (e) => { vmsg.hidden = false; vmsg.textContent = e; });
}

const ST = { open: "info", in_progress: "info", waiting_customer: "warn", resolved: "ok", closed: "plain" };
const stPill = (t) => `<span class="pill ${ST[t.status]}${t.status === "closed" ? " plain" : ""}">${esc(t.status_label)}</span>`;
const when = (iso) => (iso ? `${date(iso)}, ${clock(iso)}` : "");
const LIMIT = { name: [2, 80], email: [5, 254], subject: [4, 120], description: [10, 4000] };
const CAT_IC = { network: "net", billing: "bill", account: "user", device: "phone", app: "spark", other: "msg" };
let helpTimer = null, helpSeq = 0;

function faqItem(a) {
  return `<details class="faq" id="faq-${esc(a.id)}"><summary><span><b>${esc(a.title)}</b><span class="sub">${esc(a.summary)}</span></span><span class="chev" aria-hidden="true">›</span></summary>
    <div class="faqbody">${a.body.map((p) => `<p>${esc(p)}</p>`).join("")}<a class="b sm soft" href="#/help/${esc(a.id)}">Read the full article</a></div></details>`;
}
function faqList(list, q) {
  if (!list.length) return `<div class="emptybox" role="status"><b>No articles match “${esc(q)}”.</b><p class="small muted">Try fewer or different words, ask the assistant, or send a request to the care team.</p>
    <div class="btns"><a class="b sm soft" href="#/assistant">Ask the assistant</a><a class="b sm ghost" href="#/support/new">Contact support</a></div></div>`;
  return list.map(faqItem).join("");
}
async function help() {
  const [d, h, s] = await Promise.all([api("/api/care/help"), api("/api/care/home"), api("/api/care/support")]);
  const cat = ui.helpCat || "";
  const active = s.tickets.filter((t) => !["resolved", "closed"].includes(t.status)).length;
  const fresh = s.tickets.filter((t) => t.unread_customer);
  const shown = cat ? d.articles.filter((a) => a.category === cat) : d.popular.map((id) => d.articles.find((a) => a.id === id));
  view.html = shell("help", `<div class="page" style="padding-top:12px">
    <section class="card helphero"><h2>How can we help, ${esc(h.account.first_name)}?</h2>
      <form class="hsearch" id="hs" role="search"><span aria-hidden="true">${ic("search", 18)}</span><input id="hq" type="search" placeholder="Search help, for example “credit” or “slow data”" aria-label="Search help articles" autocomplete="off" value="${esc(ui.helpQ || "")}"></form></section>
    ${fresh.map((t) => `<a class="card replynote" href="#/support/${esc(t.id)}"><span class="ic">${ic("msg", 18)}</span><span><b>The care team replied</b><span class="sub">${esc(t.id)} · ${esc(t.subject)}</span></span><span aria-hidden="true">›</span></a>`).join("")}
    <div id="hres" aria-live="polite"></div>
    <div class="quick six" id="hquick">
      <a href="#/assistant"><span class="ic">${ic("spark")}</span>Ask the assistant</a>
      <a href="#/support/new"><span class="ic">${ic("send")}</span>Contact support</a>
      <a href="#/support"><span class="ic">${ic("msg")}</span>My requests${active ? ` <span class="count">${active}</span>` : ""}</a>
      <a href="#/report"><span class="ic">${ic("flag")}</span>Report a problem</a>
      <a href="#/network"><span class="ic">${ic("net")}</span>Network status</a>
      <a href="#/help/outage-credit"><span class="ic">${ic("gift")}</span>Outage credits</a></div>
    <div id="hbrowse">
    <div class="sect"><h2>Browse by topic</h2>${cat ? `<button class="linkbtn" id="allcats">Show popular</button>` : ""}</div>
    <div class="cats" role="group" aria-label="Help topics">${d.categories.filter((c) => c.count).map((c) => `<button class="cat ${cat === c.id ? "on" : ""}" data-cat="${c.id}" aria-pressed="${cat === c.id}"><span class="ic">${ic(CAT_IC[c.id] || "msg", 18)}</span><b>${esc(c.label)}</b><span class="sub">${c.count} article${c.count === 1 ? "" : "s"}</span></button>`).join("")}</div>
    <div class="sect"><h2>${cat ? esc(d.categories.find((c) => c.id === cat).label) : "Popular questions"}</h2></div>
    <section class="card faqs">${shown.map(faqItem).join("")}</section></div>
    <section class="card stillcard"><h2>Still need help?</h2><p class="small">Send a request to the Northstar care team. You get a reference number straight away and can follow the replies here in the app.</p>
      <div class="btns"><a class="b" href="#/support/new">Contact support</a><a class="b ghost" href="#/support">My support requests</a></div></section>
    <p class="muted-note">Demo app for a fictional carrier. Requests are answered by staff in the RAN Sentinel Operations Support desk.</p></div>`, { title: "Help" });
  notice(h);
  document.querySelectorAll("[data-cat]").forEach((b) => (b.onclick = () => { ui.helpCat = ui.helpCat === b.dataset.cat ? "" : b.dataset.cat; guard(help); }));
  const all = document.getElementById("allcats"); if (all) all.onclick = () => { ui.helpCat = ""; guard(help); };
  const q = document.getElementById("hq"), res = document.getElementById("hres"), browse = document.getElementById("hbrowse"), quick = document.getElementById("hquick");
  const run = async () => {
    const text = q.value.trim(); ui.helpQ = q.value;
    const seq = ++helpSeq;
    if (!text) { res.innerHTML = ""; browse.hidden = false; quick.hidden = false; return; }
    browse.hidden = true; quick.hidden = true;
    res.innerHTML = `<p class="small muted" role="status"><span class="spin" aria-hidden="true"></span> Searching…</p>`;
    try {
      const r = await api("/api/care/help?q=" + encodeURIComponent(text));
      if (seq !== helpSeq) return;
      res.innerHTML = `<div class="sect"><h2>${r.articles.length ? `${r.articles.length} result${r.articles.length === 1 ? "" : "s"}` : "No results"}</h2><button class="linkbtn" id="hclear">Clear search</button></div>
        <section class="card faqs">${faqList(r.articles, text)}</section>`;
      document.getElementById("hclear").onclick = () => { q.value = ""; run(); q.focus(); };
      const first = res.querySelector("details.faq"); if (first && r.articles.length <= 2) first.open = true;
    } catch (e) {
      if (seq !== helpSeq) return;
      res.innerHTML = `<div class="emptybox err" role="alert"><b>Search isn't working right now.</b><p class="small">${esc(e.message)}</p><button class="b sm ghost" id="hretry">Try again</button></div>`;
      document.getElementById("hretry").onclick = run;
    }
  };
  q.oninput = () => { clearTimeout(helpTimer); helpTimer = setTimeout(run, 220); };
  document.getElementById("hs").onsubmit = (e) => { e.preventDefault(); clearTimeout(helpTimer); run(); };
  if (q.value.trim()) run();
}

async function article(id) {
  let a;
  try { a = await api("/api/care/help/" + encodeURIComponent(id)); }
  catch (e) {
    if (e.status === 401) throw e;
    view.html = shell("help", `<div class="page" style="padding-top:12px"><section class="card"><h2>We couldn't find that article</h2><p class="small muted">${esc(e.message)}</p><a class="b sm" href="#/help">Back to Help</a></section></div>`, { title: "Help", back: "#/help" });
    return;
  }
  view.html = shell("help", `<div class="page" style="padding-top:12px">
    <article class="card art"><span class="pill plain info">${esc(a.category_label)}</span><h1>${esc(a.title)}</h1><p class="lede">${esc(a.summary)}</p>
      ${a.body.map((p) => `<p>${esc(p)}</p>`).join("")}
      ${a.steps ? `<h2>Step by step</h2><ol class="steps">${a.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>` : ""}
      ${a.image ? `<figure class="shot"><img src="${esc(a.image.src)}" alt="${esc(a.image.alt)}" loading="lazy" width="585" height="1080"><figcaption>${esc(a.image.caption)}</figcaption></figure>` : ""}
      ${(a.links || []).length ? `<div class="btns">${a.links.map(([l, href], i) => `<a class="b sm ${i ? "ghost" : ""}" href="${esc(href)}">${esc(l)}</a>`).join("")}</div>` : ""}</article>
    ${a.related.length ? `<div class="sect"><h2>Related</h2></div><section class="card"><div class="list">${a.related.map((r) => `<a class="li" href="#/help/${esc(r.id)}"><span><b>${esc(r.title)}</b><div class="sub">${esc(r.summary)}</div></span><span>›</span></a>`).join("")}</div></section>` : ""}
    <section class="card stillcard"><h2>Didn't solve it?</h2><p class="small">Send a request and the care team will look at it with you.</p><div class="btns"><a class="b sm" href="#/support/new" data-newcat="${esc(a.category)}">Contact support</a><a class="b sm ghost" href="#/assistant">Ask the assistant</a></div></section></div>`, { title: "Help article", back: "#/help" });
  document.querySelectorAll("[data-newcat]").forEach((x) => (x.onclick = () => { ui.supportDraft = { ...(ui.supportDraft || {}), category: x.dataset.newcat }; }));
  guard(async () => notice(await api("/api/care/home")));
}

function ticketRow(t) {
  return `<a class="li tk ${t.unread_customer ? "new" : ""}" href="#/support/${esc(t.id)}"><span><b>${esc(t.subject)}</b><div class="sub"><span class="mono">${esc(t.id)}</span> · ${esc(t.category_label)} · updated ${esc(when(t.updated))}</div></span>
    <span class="tkr">${t.unread_customer ? `<span class="newdot">New reply</span>` : ""}${stPill(t)}</span></a>`;
}
async function supportList() {
  const d = await api("/api/care/support");
  const act = d.tickets.filter((t) => !["resolved", "closed"].includes(t.status)), done = d.tickets.filter((t) => ["resolved", "closed"].includes(t.status));
  view.html = shell("help", `<div class="page" style="padding-top:12px">
    <div class="row between"><p class="small muted">Requests you sent to the Northstar care team.</p><a class="b sm" href="#/support/new">New request</a></div>
    ${d.tickets.length ? `${act.length ? `<div class="sect"><h2>Active</h2></div><section class="card"><div class="list">${act.map(ticketRow).join("")}</div></section>` : ""}
      ${done.length ? `<div class="sect"><h2>Resolved and closed</h2></div><section class="card"><div class="list">${done.map(ticketRow).join("")}</div></section>` : ""}`
      : `<section class="card emptybox"><span class="ic big">${ic("msg", 26)}</span><b>You have no support requests yet.</b><p class="small muted">If something isn't working and the help articles don't solve it, send us a request. You'll see the care team's replies here.</p><a class="b" href="#/support/new">Contact support</a></section>`}
    <p class="muted-note">Only you and the Northstar care team can see these requests.</p></div>`, { title: "My support requests", back: "#/help" });
  guard(async () => notice(await api("/api/care/home")));
}

function fieldErr(form, fields) {
  form.querySelectorAll(".ferr").forEach((e) => { e.textContent = ""; e.hidden = true; });
  form.querySelectorAll("[aria-invalid]").forEach((e) => e.removeAttribute("aria-invalid"));
  let first = null;
  for (const [k, msg] of Object.entries(fields)) {
    const inp = form.querySelector(`[name="${k}"]`), out = form.querySelector(`#err-${k}`);
    if (inp) { inp.setAttribute("aria-invalid", "true"); first = first || inp; }
    if (out) { out.textContent = msg; out.hidden = false; }
  }
  if (first) first.focus();
}
function checkTicket(v) {
  const f = {}, say = { name: ["your name", "Your name"], email: ["your email address", "Your email address"], subject: ["a subject", "The subject"], description: ["a description of the problem", "The description"] };
  for (const k of ["name", "email", "subject", "description"]) {
    const [lo, hi] = LIMIT[k], x = v[k].trim();
    if (!x) f[k] = `Enter ${say[k][0]}.`; else if (x.length < lo) f[k] = `${say[k][1]} must be at least ${lo} characters.`; else if (x.length > hi) f[k] = `${say[k][1]} must be ${hi} characters or fewer.`;
  }
  const em = v.email.trim();
  if (em && em.length <= 254 && !/^[^@\s<>"']+@[^@\s<>"']+\.[A-Za-z]{2,}$/.test(em)) f.email = "Enter an email address like name@example.com.";
  if (!v.category) f.category = "Choose a category.";
  return f;
}
async function supportNew() {
  const d = await api("/api/care/support");
  const dr = ui.supportDraft = { name: d.contact.name, email: d.contact.email, subject: "", category: "", description: "", ...(ui.supportDraft || {}) };
  const fld = (k, label, input, hint) => `<div class="field"><label for="f-${k}">${label}</label>${input}${hint ? `<span class="hint" id="hint-${k}">${hint}</span>` : ""}<span class="ferr" id="err-${k}" hidden></span></div>`;
  view.html = shell("help", `<div class="page" style="padding-top:12px">
    <section class="card" id="newbox"><h2>Contact support</h2><p class="small muted">Tell us what's wrong and the care team will reply here in the app. Fields marked * are required.</p>
      <form id="tf" class="grid tform" novalidate>
        ${fld("name", "Name *", `<input id="f-name" name="name" type="text" autocomplete="name" maxlength="80" required value="${esc(dr.name)}" aria-describedby="err-name">`)}
        ${fld("email", "Email for replies *", `<input id="f-email" name="email" type="email" autocomplete="email" maxlength="254" required value="${esc(dr.email)}" aria-describedby="err-email">`)}
        ${fld("category", "Category *", `<select id="f-category" name="category" required aria-describedby="err-category"><option value="">Choose a category</option>${Object.entries(d.categories).map(([k, l]) => `<option value="${k}" ${dr.category === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`)}
        ${fld("subject", "Subject *", `<input id="f-subject" name="subject" type="text" maxlength="120" required value="${esc(dr.subject)}" placeholder="For example: No signal at home since noon" aria-describedby="hint-subject err-subject">`, "A short summary, 4 to 120 characters.")}
        ${fld("description", "Description *", `<textarea id="f-description" name="description" class="ta" rows="6" maxlength="4000" required placeholder="What happened, where, and since when? Include anything you already tried." aria-describedby="hint-description err-description">${esc(dr.description)}</textarea>`, `<span id="dcount">${dr.description.length}</span> / 4000 characters, at least 10.`)}
        <p class="err" id="tferr" role="alert" hidden></p>
        <button class="b block" type="submit">Send request</button></form></section>
    <p class="muted-note">Please don't include passwords or card numbers. Demo app: requests are answered from the RAN Sentinel Operations Support desk.</p></div>`, { title: "Contact support", back: "#/help" });
  const form = document.getElementById("tf"), err = document.getElementById("tferr");
  form.oninput = (e) => {
    const t = e.target; if (t.name) dr[t.name] = t.value;
    if (t.name === "description") document.getElementById("dcount").textContent = t.value.length;
    if (t.getAttribute("aria-invalid")) { t.removeAttribute("aria-invalid"); const o = document.getElementById("err-" + t.name); if (o) o.hidden = true; }
  };
  form.onsubmit = async (e) => {
    e.preventDefault(); err.hidden = true;
    const v = Object.fromEntries(new FormData(form));
    const bad = checkTicket(v);
    if (Object.keys(bad).length) { fieldErr(form, bad); err.textContent = "Please fix the highlighted fields."; err.hidden = false; return; }
    fieldErr(form, {});
    try {
      const t = await api("/api/care/support", { body: v });
      ui.supportDraft = null;
      document.getElementById("newbox").outerHTML = `<section class="card done" id="newbox" role="status" tabindex="-1"><span class="ic big ok">${ic("check", 26)}</span><h2>Request sent</h2>
        <p>Your reference is <b class="mono">${esc(t.id)}</b>. We saved it to My support requests, where you'll see the care team's reply and can answer it.</p>
        <div class="kv"><span>Subject</span><span>${esc(t.subject)}</span><span>Category</span><span>${esc(t.category_label)}</span><span>Status</span><span>${esc(t.status_label)}</span></div>
        <div class="btns"><a class="b" href="#/support/${esc(t.id)}">View request</a><a class="b ghost" href="#/help">Back to Help</a></div></section>`;
      document.getElementById("newbox").focus();
    } catch (x) {
      if (x.status === 401) throw x;
      if (Object.keys(x.fields || {}).length) fieldErr(form, x.fields);
      err.textContent = x.message; err.hidden = false;
    }
  };
}

function msgItem(m) {
  if (m.role === "system") return `<li class="sys"><span>${esc(m.body)}</span><time>${esc(when(m.created))}</time></li>`;
  const me = m.role === "customer";
  return `<li class="msg ${me ? "me" : "agent"}"><div class="mh"><b>${me ? "You" : esc(m.author)}</b>${me ? "" : `<span class="sub">Northstar care team</span>`}<time>${esc(when(m.created))}</time></div><p>${esc(m.body)}</p></li>`;
}
async function supportTicket(id) {
  let t;
  try { t = await api("/api/care/support/" + encodeURIComponent(id)); }
  catch (e) {
    if (e.status === 401) throw e;
    view.html = shell("help", `<div class="page" style="padding-top:12px"><section class="card emptybox" role="alert"><b>We couldn't open that request</b><p class="small muted">${esc(e.message)} Check the reference number, or open it from your list.</p><a class="b sm" href="#/support">My support requests</a></section></div>`, { title: "Support request", back: "#/support" });
    return;
  }
  const closed = t.status === "closed";
  view.html = shell("help", `<div class="page" style="padding-top:12px">
    <section class="card"><div class="row"><span class="mono small">${esc(t.id)}</span>${stPill(t)}</div><h2>${esc(t.subject)}</h2>
      <span class="small muted">${esc(t.category_label)} · opened ${esc(when(t.created))} · replies go to ${esc(t.email)}</span>
      ${t.status === "waiting_customer" ? `<div class="banner warn">The care team is waiting for your reply.</div>` : t.status === "resolved" ? `<div class="banner ok">The care team marked this resolved. If it isn't, reply below and it opens again.</div>` : ""}</section>
    <section class="card"><h2>Conversation</h2><ol class="thread">${t.messages.map(msgItem).join("")}</ol></section>
    ${closed ? `<section class="card"><p class="small">This request is closed. If you still need help, start a new request.</p><a class="b sm" href="#/support/new">New request</a></section>`
      : `<section class="card" id="rbox-${esc(t.id)}" data-keep><form id="rf" class="grid" style="gap:10px" novalidate><div class="field"><label for="rbody">Your reply</label>
        <textarea id="rbody" name="body" class="ta" rows="4" maxlength="4000" aria-describedby="rerr"></textarea><span class="ferr" id="rerr" hidden></span></div>
        <div class="btns"><button class="b" type="submit">Send reply</button><button class="b ghost" type="button" id="closeq">Close request</button></div>
        <div class="confirmrow" id="closeconf" hidden><span class="small">Close this request? You can't reply to it after that.</span><div class="btns"><button class="b sm" type="button" id="closeyes">Close it</button><button class="b sm ghost" type="button" id="closeno" data-nobusy>Keep it open</button></div></div></form></section>`}
    <p class="muted-note">Only you and the Northstar care team can see this conversation.</p></div>`, { title: "Support request", back: "#/support" });
  guard(async () => notice(await api("/api/care/home")));
  if (closed) return;
  const box = document.getElementById("rbox-" + t.id);
  const f = box.querySelector("#rf"), body = box.querySelector("#rbody"), rerr = box.querySelector("#rerr");
  f.onsubmit = async (e) => {
    e.preventDefault(); rerr.hidden = true; body.removeAttribute("aria-invalid");
    if (!body.value.trim()) { rerr.textContent = "Enter a message."; rerr.hidden = false; body.setAttribute("aria-invalid", "true"); body.focus(); return; }
    try { await api(`/api/care/support/${encodeURIComponent(t.id)}/reply`, { body: { body: body.value } }); body.value = ""; toast("Reply sent", "The care team will see it straight away."); poll.now(); }
    catch (x) { if (x.status === 401) throw x; rerr.textContent = x.message; rerr.hidden = false; }
  };
  box.querySelector("#closeq").onclick = () => { box.querySelector("#closeconf").hidden = false; box.querySelector("#closeyes").focus(); };
  box.querySelector("#closeno").onclick = () => { box.querySelector("#closeconf").hidden = true; };
  box.querySelector("#closeyes").onclick = async () => {
    try { await api(`/api/care/support/${encodeURIComponent(t.id)}/close`, { body: {} }); toast("Request closed", t.id); poll.now(); }
    catch (x) { if (x.status === 401) throw x; rerr.textContent = x.message; rerr.hidden = false; }
  };
}

async function shop() {
  view.html = shell("", `<div class="page" style="padding-top:12px">
    <section class="perk"><b>Upgrade-ready</b><span>See phones and plans that work with your account. Demo store: nothing can be bought here.</span></section>
    <div class="tiles">${[["phone", "Phones", "Latest Android and iPhone models"], ["watch", "Watches and tablets", "Add a connected device line"], ["router", "Home Internet", "Check availability at your Home"], ["gift", "Accessories", "Cases, chargers and more"]]
      .map(([k, t, s]) => `<div class="tilec"><span class="ic">${ic(k)}</span><b>${esc(t)}</b><span class="small muted">${esc(s)}</span></div>`).join("")}</div>
    <section class="card"><h2>Plans</h2><div class="list">
      <div class="li"><span><b>Northstar Unlimited Plus</b><div class="sub">Your current plan</div></span><span class="pill ok plain">Current</span></div>
      <div class="li"><span><b>Northstar Unlimited Max</b><div class="sub">More hotspot and premium data</div></span><span class="small muted">Demo</span></div>
      <div class="li"><span><b>Northstar Essentials</b><div class="sub">Unlimited with a lower price</div></span><span class="small muted">Demo</span></div></div></section></div>`, { title: "Shop", back: "#/home" });
  guard(async () => notice(await api("/api/care/home")));
}

const voice = (() => {
  const S = { open: false, on: false, state: "idle", heard: "", answer: "", actions: [], history: [], flow: [], misses: 0, mic: null, audio: null, by: "" };
  const END = /^(stop|bye|goodbye|that'?s all|that is all|thanks?,? (that'?s all|bye)|nothing else)[.!]?$/i;
  const STATUS = { idle: "Tap the mic and talk, or type below", listening: "Listening…", hearing: "Understanding…", thinking: "Working on it…", speaking: "Speaking… tap the orb to interrupt" };
  const CHIPS = ["Test my connection", "Any problems near me?", "What's my bill?", "Report a problem", "Turn on Wi-Fi Calling"];
  const GUESS = [[/connect|signal|data|speed|internet|slow|test/i, "Testing your connection"], [/report|complain/i, "Preparing your report"],
    [/bill|pay|balance|due|plan/i, "Looking up your bill"], [/credit|refund/i, "Checking your credits"],
    [/outage|down|problem|issue|service|near|area|\b9\d{4}\b/i, "Checking the network at your places"],
    [/open|go to|show|take me/i, "Opening the page"], [/^(yes|yeah|yep|sure|ok|okay|go ahead|do it|confirm|send it)/i, "Doing what you said yes to"],
    [/wi-?fi|data saver|setting/i, "Preparing the setting change"]];
  let root = null;
  const page = () => (location.hash.replace(/^#\/?/, "") || "home").split("/")[0];
  const MIC24 = UI.MIC.replace('width="14" height="14"', 'width="20" height="20"');

  function mount() {
    if (root) return;
    root = document.createElement("div");
    root.className = "va";
    root.innerHTML = `<button class="va-launch" id="valaunch" aria-label="Open the voice assistant"><span class="orb sm"><i></i></span><b>Ask</b></button>
      <div class="va-sheet" id="vasheet" hidden role="dialog" aria-label="Northstar assistant">
        <div class="va-top"><button class="va-ic" id="vaclose" aria-label="Close the assistant">✕</button><span class="va-model" id="vamodel"></span>
          <button class="va-ic" id="vanew" aria-label="Clear conversation and start over" title="New conversation">↺</button><button class="va-ic va-mic" id="vamic" aria-label="Talk">${MIC24}</button></div>
        <button class="va-orbbtn" id="vaorb" aria-label="Talk"><span class="orb" id="vaorbi"><i></i></span></button>
        <div class="va-say" id="vasay" aria-live="polite"></div>
        <div class="va-status" id="vastatus" aria-live="polite"></div>
        <ol class="va-flow" id="vaflow"></ol>
        <div class="va-acts" id="vaacts"></div>
        <form class="va-ask" id="vaask"><span class="va-clip">${ic("spark", 16)}</span><input id="vaq" placeholder="Ask me anything" aria-label="Ask the assistant" autocomplete="off">
          <button class="va-send" aria-label="Send">${ic("send", 16)}</button></form>
        <div class="va-chips" id="vachips">${CHIPS.map((c) => `<button type="button">${esc(c)}</button>`).join("")}</div>
      </div>`;
    document.body.appendChild(root);
    const $ = (id) => root.querySelector("#" + id);
    $("valaunch").onclick = () => { S.open = true; paint(); start(); };
    $("vaclose").onclick = () => { end(); S.open = false; paint(); };
    $("vamic").onclick = $("vaorb").onclick = tap;
    $("vanew").onclick = async () => {
      end();
      try { S.restoring = api("/api/care/voice/memory", { method: "DELETE" }); await S.restoring; S.history = []; S.actions = []; S.heard = ""; S.answer = "Conversation cleared. How can I help?"; }
      catch (e) { S.answer = e.message; }
      paint();
    };
    $("vaask").onsubmit = (e) => { e.preventDefault(); const q = $("vaq").value.trim(); $("vaq").value = ""; if (q) typed(q); };
    $("vachips").querySelectorAll("button").forEach((b) => (b.onclick = () => typed(b.textContent)));
    S.status = () => api("/api/care/voice/status").then((v) => { S.browserVoice = v.speak === "browser"; $("vamodel").textContent = `${v.think === "rules" ? "Offline rules" : "Meta Muse Spark"} · ${v.speak === "browser" ? "browser voice" : "Gemini voice"}`; }).catch(() => {});
  }
  function paint() {
    if (!root) return;
    const $ = (id) => root.querySelector("#" + id);
    $("vasheet").hidden = !S.open;
    $("valaunch").hidden = S.open;
    root.classList.toggle("open", S.open);
    root.classList.toggle("compact", !!(S.heard || S.answer));
    $("vaorbi").className = "orb " + S.state;
    $("vamic").classList.toggle("on", S.state === "listening");
    $("vamic").setAttribute("aria-label", S.on ? "Stop talking" : "Talk");
    $("vasay").innerHTML = S.answer ? `${S.heard ? `<span class="va-heard">“${esc(S.heard)}”</span>` : ""}<span>${esc(S.answer)}</span>`
      : S.heard ? `<span class="va-heard">“${esc(S.heard)}”</span>`
      : `Hi ${esc(S.name || "there")}! I'm your Northstar assistant, <b>ready</b> <span class="fade">to check your network and run the app for you.</span>`;
    $("vastatus").textContent = STATUS[S.state];
    $("vaflow").innerHTML = S.flow.map((f) => `<li class="${f.state}"><span class="dot" aria-hidden="true"></span>${esc(f.label)}</li>`).join("");
    $("vaflow").hidden = !S.flow.length;
    $("vaacts").innerHTML = S.actions.map((a) => `<div class="act"><b>${esc(a.label)}</b>${a.type === "report" ? `<p>${esc(a.details || "No additional details")}</p>` : ""}${a.done ? `<span class="pill ok">${esc(a.done)}</span>` :
      `<div class="btns"><span class="small muted">Say “yes” or</span><button class="b sm" data-vconfirm="${esc(a.id)}">Confirm</button><button class="b sm" data-vcancel="${esc(a.id)}">Cancel</button></div>`}</div>`).join("");
    $("vaacts").querySelectorAll("[data-vconfirm]").forEach((b) => (b.onclick = async () => {
      const a = S.actions.find((x) => x.id === b.dataset.vconfirm);
      end();
      b.disabled = true;
      try { const r = await api("/api/care/confirm", { body: { action_id: a.id } }); a.done = "Done"; S.answer = r.done; if (a.type === "report") { ui.report = { place: "home", symptom: "no_service" }; location.hash = "#/network"; } else route(); }
      catch (e) { a.done = "Expired"; S.answer = e.message; }
      paint();
    }));
    $("vaacts").querySelectorAll("[data-vcancel]").forEach((b) => (b.onclick = async () => {
      end();
      b.disabled = true;
      try {
        await api("/api/care/voice/cancel", { body: { action_id: b.dataset.vcancel } });
        S.actions = S.actions.filter((a) => a.id !== b.dataset.vcancel);
        S.answer = "Cancelled. I haven't made that change.";
      } catch (e) { S.answer = e.message; }
      paint();
    }));
  }
  function set(state) { S.state = state; paint(); }
  function step(label) { S.flow.forEach((f) => f.state === "now" && (f.state = "done")); if (label) S.flow.push({ label, state: "now" }); paint(); }

  async function start() {
    const tok = S.tok;
    S.restoring = api("/api/care/voice/memory").then((m) => {
      if (tok !== S.tok) return;
      S.history = m.messages || []; S.actions = m.actions || [];
      S.heard = S.history.filter((h) => h.who === "me").at(-1)?.text || "";
      S.answer = S.history.filter((h) => h.who === "bot").at(-1)?.text || "";
      const draft = S.actions.find((a) => a.type === "report" && !a.done);
      if (page() === "report" && draft) {
        ui.report = { place: draft.place, symptom: draft.symptom, details: draft.details, actionId: draft.id };
        route();
      } else if (page() === "report" && ui.report.actionId && !draft) {
        ui.report = { place: "home", symptom: "no_service" }; route();
      }
      paint();
    }).catch((e) => { if (tok === S.tok) { S.answer = e.message; paint(); } });
    if (!S.model) { S.model = true; S.status().catch(() => (S.model = false)); }
    if (!S.name) api("/api/care/home").then((h) => { S.name = h.account.first_name; paint(); }).catch(() => {});
    paint();
  }
  async function tap() {
    if (S.restoring) await S.restoring;
    if (S.state === "speaking") { S.tok = (S.tok || 0) + 1; quiet(); S.on = true; return hear(); }
    if (S.state === "listening") { S.mic && S.mic.stop(); return; }
    if (S.on) return end();
    S.on = true; S.misses = 0; S.heard = ""; S.answer = ""; S.actions = []; S.flow = [];
    return hear();
  }
  function end() {
    S.tok = (S.tok || 0) + 1;
    S.on = false; quiet();
    if (S.mic) { S.mic.cancel(); S.mic = null; }
    S.flow.forEach((f) => f.state === "now" && (f.state = "done"));
    set("idle");
  }
  function quiet() {
    S.speech = (S.speech || 0) + 1;
    if (S.ttsRequest) { S.ttsRequest.abort(); S.ttsRequest = null; }
    if (S.finishPlayback) S.finishPlayback();
    if (S.finishBrowser) S.finishBrowser();
    if (S.audio) { S.audio.pause(); S.audio = null; }
    if (window.speechSynthesis) speechSynthesis.cancel();
  }

  async function hear() {
    if (!S.on) return;
    const tok = S.tok, again = () => tok === S.tok && hear();
    if (!S.flow.length) step("Listening");
    set("listening");
    let wav;
    try {
      const mic = await UI.listen({ onLevel: (v) => root.querySelector("#vaorbi").style.setProperty("--lvl", v.toFixed(2)) });
      if (!S.on || tok !== S.tok) { mic.cancel(); return; }
      S.mic = mic;
      wav = await mic.result;
    } catch (e) { if (tok !== S.tok) return; S.answer = e.message || "Microphone not available."; S.flow = []; S.on = false; return set("idle"); }
    if (!S.on || tok !== S.tok) return;
    S.mic = null;
    if (!wav) { S.flow = []; return ++S.misses >= 2 ? end() : (await speak("I'm listening. What can I do for you?"), again()); }
    S.flow = [{ label: "Heard you", state: "done" }]; step("Understanding your words"); set("hearing");
    let text = "";
    try { text = (await UI.upload("/api/public/voice", wav, "audio/wav")).text || ""; }
    catch (e) { if (tok !== S.tok) return; S.answer = e.message; return end(); }
    if (!S.on || tok !== S.tok) return;
    if (!text.trim()) { S.flow = []; return ++S.misses >= 2 ? end() : (await speak("Sorry, I didn't catch that. Could you say it again?"), again()); }
    S.misses = 0;
    if (END.test(text.trim())) { S.heard = text; S.answer = "Okay. Tap the mic whenever you need me."; step(""); await speak(S.answer); return end(); }
    await ask(text);
    again();
  }
  async function typed(q) {
    set("thinking");
    if (S.restoring) await S.restoring;
    S.tok = (S.tok || 0) + 1;
    if (S.state === "listening" && S.mic) { S.mic.cancel(); S.mic = null; }
    quiet();
    const tok = S.tok;
    S.flow = []; await ask(q);
    if (tok !== S.tok) return;
    if (S.on) hear(); else set("idle");
  }
  async function ask(text) {
    const tok = S.tok;
    const actionId = S.actions.filter((a) => !a.done).at(-1)?.id || null;
    S.heard = text; S.answer = ""; S.actions = [];
    step((GUESS.find(([re]) => re.test(text)) || [, "Finding the answer"])[1]); set("thinking");
    try {
      const r = await api("/api/care/voice/turn", { body: { text, action_id: actionId, request_id: crypto.randomUUID(), page: page(), speak: false } });
      if (tok !== S.tok) return;
      S.history = r.memory?.messages || [...S.history, { who: "me", text }, { who: "bot", text: r.answer }];
      chat.push({ who: "me", text }, { who: "bot", text: r.answer, actions: r.actions, steps: r.steps, by: r.by });
      S.flow.pop();
      for (const st of r.steps || []) S.flow.push({ label: st.label, state: "done" });
      S.answer = r.answer; S.actions = r.actions || [];
      S.by = r.by;
      for (const u of r.ui || []) apply(u);
      step("Speaking");
      await speak(r.answer);
      if (tok === S.tok) step("");
    } catch (e) { if (tok !== S.tok) return; S.answer = e.message; step(""); await speak("Sorry, something went wrong. Please try again."); }
  }

  function apply(u) {
    if (u.type === "navigate") {
      if (u.page === "network" && u.place) ui.place = u.place;
      if (u.page === "report" && u.place) ui.report = { ...ui.report, place: u.place, symptom: u.symptom || ui.report.symptom, details: u.details || "", actionId: u.action_id };
      const hash = "#/" + u.page + (u.page === "network" && u.place ? "/" + u.place : "");
      if (location.hash !== hash) location.hash = hash; else route();
    } else if (u.type === "refresh") {
      if (u.done === "report") { ui.report = { place: "home", symptom: "no_service" }; location.hash = "#/network"; }
      else route();
    }
  }

  async function speak(text) {
    set("speaking");
    const id = (S.speech = (S.speech || 0) + 1);
    const current = () => id === S.speech && S.state === "speaking";
    const fallback = () => new Promise((resolve) => browserSay(text, resolve));
    if (S.browserVoice) { await fallback(); return done(id); }
    const controller = new AbortController();
    S.ttsRequest = controller;
    const timeout = setTimeout(() => controller.abort(), 65000);
    try {
      // Generate the complete reply once: sentence clips create repeated endings.
      const r = await fetch("/api/care/voice/speak", { method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "same-origin", signal: controller.signal, body: JSON.stringify({ text }) });
      if (!r.ok) throw new Error("Speech temporarily unavailable");
      const clip = await r.blob();
      if (!current()) return;
      await new Promise((resolve) => {
        const url = URL.createObjectURL(clip), audio = new Audio(url);
        let finished = false;
        const finish = () => {
          if (finished) return;
          finished = true; clearTimeout(guard);
          audio.onended = audio.onerror = null; audio.pause();
          URL.revokeObjectURL(url);
          if (S.audio === audio) S.audio = null;
          if (S.finishPlayback === finish) S.finishPlayback = null;
          resolve();
        };
        const guard = setTimeout(finish, 120000);
        S.audio = audio; S.finishPlayback = finish;
        audio.onended = finish;
        audio.onerror = () => { S.answer = text + " (Audio could not play; you can read the reply.)"; finish(); paint(); };
        audio.play().catch(() => { if (current()) { S.answer = text + " (Tap the microphone to enable audio, or read the reply.)"; paint(); } finish(); });
      });
    } catch (e) {
      if (current()) await fallback();
    } finally {
      clearTimeout(timeout);
      if (S.ttsRequest === controller) S.ttsRequest = null;
    }
    done(id);
  }
  function done(id) { if (id === S.speech && S.state === "speaking") set(S.on ? "listening" : "idle"); }
  function browserSay(text, fin) {
    if (!window.speechSynthesis) return fin();
    let over = false;
    const once = () => { if (!over) { over = true; clearTimeout(guard); if (S.finishBrowser === once) S.finishBrowser = null; fin(); } };
    S.finishBrowser = once;
    const guard = setTimeout(() => { speechSynthesis.cancel(); once(); }, 4000 + text.split(/\s+/).length * 700);
    const u = new SpeechSynthesisUtterance(text);
    const vs = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
    u.voice = vs.find((v) => /natural|online|google us/i.test(v.name)) || vs[0] || null;
    u.rate = 1.02; u.onend = u.onerror = once;
    speechSynthesis.speak(u);
  }

  return { show: (yes) => { mount(); root.hidden = !yes; if (yes && !S.bootstrapped) { S.bootstrapped = true; start(); } },
    end: () => root && (end(), (S.open = false), paint()),
    clearLocal: () => { chat.length = 0; if (!root) return; end(); S.history = []; S.actions = []; S.answer = ""; S.heard = ""; S.open = false; S.bootstrapped = false; ui.report = { place: "home", symptom: "no_service" }; paint(); }
  };
})();

route();
