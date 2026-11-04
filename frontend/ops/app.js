const { api, esc, hhmm, day, nice, chip, statusChip, sevChip, lineChart, clusterMap, upload, micButton, MIC, shrinkImage } = UI;
const app = document.getElementById("app");
let current = null;
let selectedCell = "SEA-RAN-001";
let lastState = null;
let lastAlarms = [];
const drafts = {};
const heard = {};
let busy = false;
const ui = { demoOpen: false, incTab: {}, cellTab: "kpis", treeFilter: "", alarmSev: "all", alarmState: "active", alarmText: "", incFilter: "open", dept: "all", ledgerText: "" };
try { Object.assign(ui, JSON.parse(localStorage.getItem("rs-ui") || "{}")); } catch {}
const saveUi = () => { try { localStorage.setItem("rs-ui", JSON.stringify({ cellTab: ui.cellTab, alarmSev: ui.alarmSev, alarmState: ui.alarmState, incFilter: ui.incFilter, demoOpen: ui.demoOpen })); } catch {} };

const LOGO = `<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><circle cx="13" cy="13" r="2.6" fill="currentColor"/>
<path d="M13 13 L13 2 A11 11 0 0 1 22.5 7.5 Z" fill="currentColor" opacity=".9"/><path d="M13 13 L22.5 18.5 A11 11 0 0 1 3.5 18.5 Z" fill="currentColor" opacity=".55"/>
<path d="M13 13 L3.5 7.5 A11 11 0 0 1 13 2 Z" fill="currentColor" opacity=".3"/></svg>`;
const STAGE_NAMES = { detect: "Detector", investigate: "Investigator", analyse: "Analyst", verify: "Verifier", plan: "Planner", validate: "Safety rules", sandbox: "Twin what-if", second_opinion: "Reviewer", review: "Department", change: "Change", monitor: "Recovery" };
const CAUSE = { capacity_congestion: "Capacity congestion", overshooting_coverage: "Overshooting coverage", external_interference: "External interference", hardware_fault: "Hardware fault" };
const SUPPORT_W = { strong: 100, moderate: 66, weak: 33, none: 4 };
const FAULTS = { capacity_surge: "Capacity surge (event crowd)", interference: "External interference", overshoot: "Overshoot (tilt mis-set)", hardware: "Hardware fault (VSWR)", data_dropout: "KPI data dropout" };
const OPEN = new Set(["DETECTED", "AUTO_REMEDIATION", "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_READY", "PLANNING", "AWAITING_DEPARTMENT", "CHANGE_APPLIED", "FIELD_WORK", "MONITORING", "ESCALATED"]);
const DEPTS = ["RAN Optimisation", "RF Engineering", "Field Operations", "NOC Data Platform", "NOC Shift Lead", "Regulatory Compliance"];
const TRIG = { rules: "threshold rules", isolation_forest: "Isolation Forest", cell_baseline: "cell baseline" };

const ICON = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  alarms: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
  cells: '<path d="M12 13v8"/><path d="M8.5 9.5a5 5 0 0 1 7 0"/><path d="M5.5 6.5a9 9 0 0 1 13 0"/><circle cx="12" cy="12.5" r="1.4"/>',
  incidents: '<path d="M12 3 2 20h20z"/><path d="M12 10v4.5M12 17.5h.01"/>',
  approvals: '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9"/>',
  ledger: '<path d="M5 3h10l4 4v14H5z"/><path d="M9 12h6M9 16h6M9 8h3"/>',
  model: '<path d="M4 19V5M4 19h16"/><path d="M7 15l4-4 3 3 5-6"/>',
  demo: '<path d="M10 2v6L4 20h16L14 8V2"/><path d="M8 2h8"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  support: '<path d="M4 13a8 8 0 0 1 16 0"/><rect x="3" y="13" width="4" height="6" rx="1.5"/><rect x="17" y="13" width="4" height="6" rx="1.5"/><path d="M20 19a3 3 0 0 1-3 3h-3"/>',
};
const ico = (n, s = 18) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;
const NAV = [
  ["Monitor", [["dashboard", "Network overview", "overview"], ["alarms", "Alarm monitor", "alarms"], ["cells", "Cell explorer", "cells"]]],
  ["Operate", [["incidents", "Incidents", "incidents"], ["departments", "Approvals", "approvals"], ["support", "Customer support", "support"]]],
  ["Assure", [["ledger", "Safety ledger", "ledger"], ["model", "Model card", "model"]]],
];

function route() {
  const h = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [page, arg] = h.split("/");
  if (page === "login") { poll.stop(); return renderLogin(); }
  if (page === "incidents" && arg) return live(() => renderIncident(arg));
  if (page === "incidents") return live(renderIncidents);
  if (page === "cells") { if (arg) selectedCell = arg; return live(renderCells, 4000); }
  if (page === "alarms") return live(renderAlarms, 3000);
  if (page === "departments") return live(renderDepartments);
  if (page === "support") return live(arg ? () => renderSupportTicket(arg) : renderSupport, 4000);
  if (page === "ledger") return live(renderLedger, 4000);
  if (page === "model") return live(renderModelCard, 15000);
  return live(renderDashboard);
}
let feed = { ok: true, lastOk: null };
const poll = UI.poller({ paused: () => busy, onState: (s) => { if (!s.ok) console.error("refresh failed:", s.error); feed = s; showFeed(); } });
function live(fn, every = 2000) {
  current = fn;
  poll.start(fn, every, (e) => { if (e.status === 401) location.hash = "#/login"; else console.error(e); });
}
const refresh = () => poll.now();
window.addEventListener("hashchange", route);
function feedText() {
  const t = feed.lastOk ? feed.lastOk.toTimeString().slice(0, 8) : null;
  if (feed.ok) return { cls: "ok", text: t ? `Updated ${t}` : "Connecting…" };
  return { cls: "bad", text: `Connection lost${t ? ` · showing data from ${t}` : ""} · retrying in ${Math.round((feed.retryIn || 0) / 1000)} s` };
}
function showFeed() {
  const el = document.getElementById("feed");
  if (!el) return;
  const f = feedText();
  UI.morph(el, `<i class="led ${f.cls}"></i>${esc(f.text)}`);
  el.classList.toggle("stale", !feed.ok);
  document.getElementById("work")?.classList.toggle("stale", !feed.ok);
}
async function getState() { lastState = await api("/api/state"); return lastState; }

function paint(active, inner) {
  const keep = document.getElementById("demo") ? captureDemo() : null;
  if (app.querySelector(".shell")) UI.morph(app, shell(active, inner));
  else app.innerHTML = shell(active, inner);
  showFeed();
  bindShell(keep);
}
function shell(active, inner) {
  const st = lastState;
  const ac = (st && st.alarm_counts) || {};
  const badge = (k) => {
    if (!st) return "";
    const n = { alarms: st.unacked_alarms, departments: st.summary.pending_tickets, incidents: st.summary.open_incidents, support: st.summary.support_unread }[k];
    return n ? `<em>${n}</em>` : "";
  };
  return `<div class="shell ${ui.demoOpen ? "with-drawer" : ""}">
  <header class="appbar">
    <a class="brandmark" href="#/dashboard">${LOGO}<span>RAN Sentinel</span></a>
    <span class="ctx">${st ? esc(st.market.name) + " · Simulated network" : ""}</span>
    <form class="search" id="gsearch" role="search"><span class="si">${ico("search", 15)}</span><input id="gq" type="search" placeholder="Cell, incident, ZIP or area" aria-label="Search the network" autocomplete="off"></form>
    <a class="sevbar" href="#/alarms" title="Active alarms by severity. Open the alarm monitor">${[["critical", "Crit"], ["major", "Major"], ["minor", "Minor"], ["warning", "Warn"]]
      .map(([k, l]) => `<span class="sev ${k} ${ac[k] ? "on" : ""}"><b>${ac[k] ?? 0}</b>${l}</span>`).join("")}</a>
    <div class="who">${st ? (st.offline ? chip("Offline rules engine", "warn") : chip("Meta Model API", "brand")) : ""}
      <span class="mono clock" title="Simulated network time">${st ? hhmm(st.sim_time) + " " + esc(st.market.tz_label) : ""}</span>
      <span class="user"><span class="av" aria-hidden="true">SC</span><span class="nm">Sarah Chen</span></span><button id="logout" class="ghost">Leave demo</button></div>
  </header>
  <nav class="rail" aria-label="Modules">${NAV.map(([g, items]) => `<div class="grp"><span class="gl">${g}</span>${items.map(([k, l, i]) =>
    `<a href="#/${k}" class="${active === k ? "on" : ""}" ${active === k ? 'aria-current="page"' : ""} title="${l}">${ico(i)}<span class="tx">${l}</span>${badge(k)}</a>`).join("")}</div>`).join("")}
    <button class="demo-toggle ${ui.demoOpen ? "on" : ""}" id="demo-toggle" aria-expanded="${ui.demoOpen}" title="Demo controls">${ico("demo")}<span class="tx">Demo controls</span></button></nav>
  <main class="work fade" id="work">${inner}</main>
  ${ui.demoOpen && st ? `<aside class="drawer" aria-label="Demo controls">${demoPanel(st)}</aside>` : ""}
  <footer class="statusbar">${statusBar(st)}</footer></div>`;
}
function statusBar(st) {
  if (!st) return "";
  const m = st.model_stats || {};
  const demo = [st.flags.red_team && "red-team plan", st.flags.twin_outage && "twin outage", st.flags.diag_outage && "diagnostics outage", st.flags.api_outage !== "none" && nice(st.flags.api_outage).toLowerCase()].filter(Boolean);
  const f = feedText();
  return `<span id="feed" class="${feed.ok ? "" : "stale"}" role="status" aria-live="polite"><i class="led ${f.cls}"></i>${esc(f.text)}</span>
    <span><i class="led ${st.paused ? "warn" : "ok"}"></i>Telemetry ${st.paused ? "paused" : "live"} · 15-min ROP · tick ${st.tick}</span>
    <span><i class="led ${st.offline || m.failed ? "warn" : "ok"}"></i>${st.offline ? "AI: offline rules engine" : `AI: ${esc(st.models.primary)} · ${m.calls} calls${m.failed ? `, ${m.failed} failed` : ""}${m.avg_latency_s != null ? ` · avg ${m.avg_latency_s} s` : ""}`}</span>
    <span><i class="led ${st.flags.twin_outage ? "bad" : "ok"}"></i>Twin: ${esc(st.twin)}</span>
    <span><i class="led ok"></i>M-Plane: NETCONF, simulated RU</span>
    ${demo.length ? `<span class="warnt">Demo switches on: ${esc(demo.join(", "))}</span>` : ""}
    <span class="grow"></span><span class="muted">Simulated network. Not connected to a live operator.</span>`;
}
function bindShell(keep) {
  const b = document.getElementById("logout");
  if (b) b.onclick = async () => { await api("/api/logout", { body: {} }); location.hash = "#/login"; };
  const t = document.getElementById("demo-toggle");
  if (t) t.onclick = () => { ui.demoOpen = !ui.demoOpen; saveUi(); refresh(); };
  const f = document.getElementById("gsearch");
  if (f) f.onsubmit = (e) => { e.preventDefault(); search(document.getElementById("gq").value); };
  if (ui.demoOpen && lastState && document.getElementById("demo")) bindDemo(lastState, keep);
}
function search(q) {
  q = q.trim();
  if (!q) return;
  const u = q.toUpperCase();
  let m;
  const go = (h) => { if (location.hash === h) refresh(); else location.hash = h; };
  if ((m = u.match(/RNS-\d{4}-\d{3}/))) return go("#/incidents/" + m[0]);
  if ((m = u.match(/SEA-RAN-\d{3}/))) return go("#/cells/" + m[0]);
  if (/^\d{1,3}$/.test(q)) return go("#/cells/SEA-RAN-" + q.padStart(3, "0"));
  const cells = lastState ? lastState.cells : [];
  const c = cells.find((c) => c.zip_code === q || c.site.toLowerCase() === q.toLowerCase()) || cells.find((c) => c.site.toLowerCase().includes(q.toLowerCase()));
  if (c) { selectedCell = c.cell_id; ui.treeFilter = c.site; return go("#/cells/" + c.cell_id); }
  const w = document.getElementById("gq");
  w.value = ""; w.placeholder = `No cell, incident or area matches "${q}"`;
}
function tabs(list, on, attr) {
  return `<div class="tabs" role="tablist">${list.filter(Boolean).map(([k, l, n]) => `<button role="tab" class="${k === on ? "on" : ""}" aria-selected="${k === on}" data-${attr}="${k}">${l}${n ? `<span class="n">${n}</span>` : ""}</button>`).join("")}</div>`;
}
function spark(values, color, w = 120, h = 30) {
  const v = values.filter((x) => x != null);
  if (v.length < 2) return `<svg class="spark" viewBox="0 0 ${w} ${h}"></svg>`;
  let lo = Math.min(...v), hi = Math.max(...v);
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const pts = values.map((x, i) => (x == null ? null : [(i * w) / (values.length - 1), h - 2 - ((x - lo) * (h - 4)) / (hi - lo)])).filter(Boolean);
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}
function stageBar(stages) {
  return `<span class="stagebar" title="${(stages || []).map((s, i) => Object.values(STAGE_NAMES)[i] + ": " + s).join(", ")}">${(stages || []).map((s) => `<i class="${s}"></i>`).join("")}</span>`;
}
function ageMin(iso, now) { return Math.max(0, Math.round((new Date(now) - new Date(iso)) / 60000)); }
function ageText(m) { return m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`; }
function legend() {
  return `<div class="legend">${[["ok", "Normal"], ["warn", "Watch or symptom"], ["bad", "Incident"], ["muted", "No data"]].map(([k, v]) => `<span><i style="background:var(--${k})"></i>${v}</span>`).join("")}</div>`;
}

function demoPanel(st) {
  const cells = st.cells.map((c) => `<option value="${c.cell_id}" ${c.cell_id === selectedCell ? "selected" : ""}>${c.cell_id} · ${esc(c.site)}${c.fault ? " (fault: " + c.fault + ")" : ""}</option>`).join("");
  return `<section class="demo" id="demo"><header><h2>Demo controls</h2><span class="small">simulated network only</span></header>
    <div class="body controls">
      <p class="small muted">Create a problem on any cell and watch the detector, the agents and the safety layer handle it.</p>
      <div class="field"><label for="d-cell">Cell</label><select id="d-cell">${cells}</select></div>
      <div class="field"><label for="d-fault">Problem to create</label><select id="d-fault">${Object.entries(FAULTS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
      <div class="field"><label for="d-sev">Severity</label><select id="d-sev"><option value="1">1 · mild</option><option value="2" selected>2 · clear</option><option value="3">3 · severe</option></select></div>
      <button class="btn primary" id="d-inject">Create problem</button>
      <div class="row"><button class="btn" id="d-step">Advance 15 min</button><button class="btn" id="d-pause">${st.paused ? "Resume clock" : "Pause clock"}</button></div>
      <div class="row"><button class="btn" id="d-clear">Clear all faults</button><button class="btn danger" id="d-reset">Reset demo</button></div>
      <span class="label" style="margin-top:6px">Failure switches</span>
      <label class="toggle"><input type="checkbox" id="d-red" ${st.flags.red_team ? "checked" : ""}> Red-team the first plan</label>
      <label class="toggle"><input type="checkbox" id="d-twin" ${st.flags.twin_outage ? "checked" : ""}> Twin outage</label>
      <label class="toggle"><input type="checkbox" id="d-diag" ${st.flags.diag_outage ? "checked" : ""}> Diagnostics outage (agent asks the field)</label>
      <div class="field"><label for="d-api">Meta API</label><select id="d-api">${[["none", "Normal"], ["primary_down", "Primary model down"], ["all_down", "All models down"]].map(([k, v]) => `<option value="${k}" ${st.flags.api_outage === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <p id="d-msg" class="small muted" role="status"></p>
    </div></section>`;
}
function captureDemo() {
  return { fault: document.getElementById("d-fault")?.value, sev: document.getElementById("d-sev")?.value, msg: document.getElementById("d-msg")?.textContent };
}
function bindDemo(st, keep) {
  const $ = (id) => document.getElementById(id);
  if (keep) { if (keep.fault) $("d-fault").value = keep.fault; if (keep.sev) $("d-sev").value = keep.sev; if (keep.msg) $("d-msg").textContent = keep.msg; }
  const msg = (t) => ($("d-msg").textContent = t);
  $("d-cell").onchange = (e) => { selectedCell = e.target.value; e.target.blur(); };
  $("d-fault").onchange = $("d-sev").onchange = (e) => e.target.blur();
  $("d-inject").onclick = async () => {
    try {
      await api("/api/demo/inject", { body: { cell_id: $("d-cell").value, fault_type: $("d-fault").value, severity: +$("d-sev").value } });
      msg(`Created ${FAULTS[$("d-fault").value].toLowerCase()} on ${$("d-cell").value}. The detector needs 2 windows (about 6 s) to confirm it.`);
    } catch (e) { msg(e.message); }
  };
  $("d-step").onclick = async () => { await api("/api/demo/step", { body: {} }); refresh(); };
  $("d-pause").onclick = async () => { await api("/api/demo/flags", { body: { paused: !st.paused } }); refresh(); };
  $("d-clear").onclick = async () => { await api("/api/demo/clear", { body: {} }); msg("All faults cleared and radio settings restored to plan."); };
  $("d-reset").onclick = async () => { $("d-reset").disabled = true; msg("Resetting…"); await api("/api/demo/reset", { body: {} }); msg("Demo reset: new network, empty ledger."); refresh(); };
  $("d-red").onchange = (e) => api("/api/demo/flags", { body: { red_team: e.target.checked } });
  $("d-twin").onchange = (e) => api("/api/demo/flags", { body: { twin_outage: e.target.checked } });
  $("d-diag").onchange = (e) => api("/api/demo/flags", { body: { diag_outage: e.target.checked } });
  $("d-api").onchange = (e) => { e.target.blur(); api("/api/demo/flags", { body: { api_outage: e.target.value } }); };
}

async function renderDashboard() {
  const st = await getState();
  const s = st.summary, H = st.health;
  const last = (k) => { for (let i = H.length - 1; i >= 0; i--) if (H[i][k] != null) return H[i][k]; return null; };
  const statusKind = { Healthy: "ok", Watching: "warn", Degraded: "bad" }[s.network_status];
  const tiles = [["Availability", "availability", "%", 2, "var(--ok)"], ["Drop rate", "drop_rate", "%", 2, "var(--warn)"], ["PRB utilisation", "prb_util", "%", 1, "var(--accent)"],
    ["DL throughput", "dl_thpt_mbps", "Mbps", 1, "var(--info)"], ["SINR", "sinr_db", "dB", 1, "var(--info)"]];
  const open = st.incidents.filter((i) => OPEN.has(i.status));
  const worst = st.cells.slice().sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 8);
  const sel = st.cells.find((c) => c.cell_id === selectedCell) || st.cells[0];
  paint("dashboard", `
    <div class="pagehead"><div><div class="crumb">Monitor / Network overview</div><h1>Seattle cluster</h1>
      <p class="sub">${s.cells} LTE cells on ${new Set(st.cells.map((c) => c.site)).size} sites · B66 AWS-3, B2 PCS, B71 600 MHz</p></div>
      <div class="headright">${chip(s.network_status, statusKind)}<span class="small muted mono">ROP ${hhmm(st.sim_time)} ${esc(st.market.tz_label)}</span></div></div>
    ${st.offline ? `<div class="banner warn">No Meta key found, so the agents use the offline rules engine. Add MODEL_API_KEY to the .env file in the project folder and restart.</div>` : ""}
    <section class="tiles">${tiles.map(([n, k, u, d, c]) => `<div class="tile"><span class="label">${n}</span><span class="v">${last(k) == null ? "–" : Number(last(k)).toFixed(d)}<small>${u}</small></span>${spark(H.map((h) => h[k]), c)}<span class="small muted">cluster average, 12 h</span></div>`).join("")}
      <div class="tile"><span class="label">Open incidents</span><span class="v">${s.open_incidents}${s.critical ? `<small class="bad">${s.critical} critical</small>` : ""}</span><span class="small muted">${s.watch} cells on watch</span><span class="small muted">${s.pending_tickets} waiting on a team</span></div></section>
    <div class="layout">
      <section class="panel span-5"><header><h2>Cluster map</h2><span class="small muted">zoom in, click a sector or site</span>
        <div class="seg" role="group" aria-label="Map view"><button type="button" id="mv-us">US</button><button type="button" id="mv-cl">Cluster</button></div></header>
        <div class="body"><div id="geoslot" class="geoslot" data-keep></div>${legend()}
        <p class="small muted">Simulated sites placed near real Seattle neighbourhoods. Green = modelled outdoor coverage (RSRP above -110 dBm), not a measured map.</p>${mapCard(sel)}</div></section>
      <section class="panel span-7 flat"><header><h2>Work queue</h2><span class="small muted">${open.length} open</span><a class="hlink" href="#/incidents">All incidents</a></header>
        <div class="body tablewrap">${queueTable(open, st.sim_time)}</div></section>
      <section class="panel span-7"><header><h2>Network health</h2><span class="small muted">cluster average, last 12 h</span></header>
        <div class="body">${lineChart([
          { name: "PRB utilisation %", values: H.map((h) => h.prb_util), color: "var(--accent)" },
          { name: "Drop rate % ×10", values: H.map((h) => (h.drop_rate == null ? null : h.drop_rate * 10)), color: "var(--warn)", dash: true },
        ], H.map((h) => h.ts), { min: 0, height: 190, aria: "Cluster PRB utilisation and drop rate over 12 hours" })}</div></section>
      <section class="panel span-5"><header><h2>AI agent activity</h2><span class="small muted">${esc(st.engine)}</span></header>
        <div class="body"><div class="kanban">
          ${[["Investigating", st.activity.investigating], ["With teams", st.activity.awaiting], ["Monitoring fix", st.activity.monitoring], ["Escalated", st.activity.escalated]]
            .map(([l, v], i) => `<div><span class="label">${l}</span><span class="v ${i === 3 && v ? "bad" : ""}">${v}</span></div>`).join("")}</div>
          ${callsFeed(st)}</div></section>
      <section class="panel span-12 flat"><header><h2>Top cells by anomaly score</h2><span class="small muted">latest 15-minute window · score 1.0 = alert threshold</span></header>
        <div class="body tablewrap">${worstTable(worst)}</div></section>
    </div>`);
  document.querySelectorAll("tr[data-inc]").forEach((tr) => (tr.onclick = () => (location.hash = "#/incidents/" + tr.dataset.inc)));
  document.querySelectorAll("tr[data-cell]").forEach((tr) => (tr.onclick = () => (location.hash = "#/cells/" + tr.dataset.cell)));
  opsMap(st);
}

let gm = null, gmSig = "", gmLayers = null;
const SECTOR_COLOR = { ok: "#1d7a46", watch: "#c27a00", symptom: "#c27a00", incident: "#b42318", critical: "#b42318", "no-data": "#6b7b80" };
function opsMap(st) {
  if (!window.L) return;
  if (!gm) {
    gm = GeoMap.create({ label: "Network map: United States with the Seattle cluster" });
    gmLayers = { coverage: L.layerGroup().addTo(gm.map), sectors: L.layerGroup(), sites: L.layerGroup(), cluster: L.layerGroup().addTo(gm.map) };
    L.control.layers(null, { "Modelled coverage": gmLayers.coverage, "Sectors": gmLayers.sectors, "Sites": gmLayers.sites }, { collapsed: true, position: "topright" }).addTo(gm.map);
    gm.map.fitBounds(GeoMap.US_BOUNDS);
    const zoomed = () => {
      const close = gm.map.getZoom() >= 10;
      for (const k of ["sectors", "sites"]) close ? gm.map.addLayer(gmLayers[k]) : gm.map.removeLayer(gmLayers[k]);
      close ? gm.map.removeLayer(gmLayers.cluster) : gm.map.addLayer(gmLayers.cluster);
    };
    gm.map.on("zoomend", zoomed);
    gm.first = true;
  }
  GeoMap.mount(gm, document.getElementById("geoslot"));
  const bySite = {};
  for (const c of st.cells) (bySite[c.site] ||= []).push(c);
  const bounds = L.latLngBounds(st.cells.map((c) => [c.site_lat, c.site_lon])).pad(0.15);
  const sig = JSON.stringify([selectedCell, st.cells.map((c) => [c.status, c.coverage_km])]);
  if (sig !== gmSig) {
    gmSig = sig;
    Object.values(gmLayers).forEach((g) => g.clearLayers());
    for (const [site, cs] of Object.entries(bySite)) {
      const c0 = cs[0], worst = cs.some((c) => ["incident", "critical"].includes(c.status)) ? "bad" : cs.some((c) => ["watch", "symptom"].includes(c.status)) ? "warn" : "ok";
      const reach = Math.max(...cs.map((c) => c.coverage_km));
      L.circle([c0.site_lat, c0.site_lon], { radius: reach * 1000, stroke: false, fillColor: worst === "bad" ? "#b42318" : "#0f7a4d", fillOpacity: worst === "bad" ? 0.16 : 0.13, interactive: false }).addTo(gmLayers.coverage);
      const tip = `<b>${esc(site)}</b> · ${esc(c0.zip_code)}<br>${cs.map((c) => `${c.cell_id} ${esc(c.band.split(" ")[0])}: ${esc(c.status === "ok" ? "normal" : c.status)}`).join("<br>")}`;
      L.circleMarker([c0.site_lat, c0.site_lon], { radius: 6, color: "#fff", weight: 2, fillColor: { ok: "#0d5257", warn: "#c27a00", bad: "#b42318" }[worst], fillOpacity: 1 })
        .bindTooltip(tip, { direction: "top" }).bindPopup(sitePopup(site, cs), { maxWidth: 380, minWidth: 300 }).addTo(gmLayers.sites);
      for (const c of cs) {
        L.polygon(GeoMap.wedge(c.site_lat, c.site_lon, c.azimuth), { color: c.cell_id === selectedCell ? "#172326" : "#ffffff", weight: c.cell_id === selectedCell ? 2.5 : 1,
          fillColor: SECTOR_COLOR[c.status], fillOpacity: .78 })
          .bindTooltip(`${c.cell_id} · ${esc(c.band)}<br>PRB ${c.prb_util ?? "–"}% · SINR ${c.sinr_db ?? "–"} dB`, { sticky: true })
          .on("click", () => { selectedCell = c.cell_id; const d = document.getElementById("d-cell"); if (d) d.value = selectedCell; refresh(); })
          .addTo(gmLayers.sectors);
      }
    }
    const alerts = st.cells.filter((c) => ["incident", "critical"].includes(c.status)).length, watch = st.cells.filter((c) => ["watch", "symptom"].includes(c.status)).length;
    L.marker(bounds.getCenter(), { icon: L.divIcon({ className: "", iconSize: null,
      html: `<div class="clustermk ${alerts ? "bad" : watch ? "warn" : "ok"}"><b>${st.cells.length}</b><span>Seattle cluster · ${Object.keys(bySite).length} sites${alerts ? ` · ${alerts} in incident` : ""}</span></div>` }),
      keyboard: true, title: "Seattle cluster" }).on("click", () => gm.map.flyToBounds(bounds, { duration: 1.2 })).addTo(gmLayers.cluster);
  }
  document.getElementById("mv-us").onclick = () => gm.map.flyToBounds(GeoMap.US_BOUNDS, { duration: 1.2 });
  document.getElementById("mv-cl").onclick = () => gm.map.flyToBounds(bounds, { duration: 1.2 });
  if (gm.first) { gm.first = false; setTimeout(() => gm.map.flyToBounds(bounds, { duration: 2.2 }), 900); }
}
function sitePopup(site, cs) {
  return `<div class="sitepop"><b>${esc(site)}</b> <span class="muted">${esc(cs[0].zip_code)} · ${cs[0].site_lat.toFixed(4)}, ${cs[0].site_lon.toFixed(4)}</span>
    <div class="poprows"><span>Cell</span><span>Band · az</span><span>PRB · SINR</span><span>State</span>
    ${cs.map((c) => `<a href="#/cells/${c.cell_id}" class="mono">${c.cell_id}</a><span>${esc(c.band.split(" ")[0])} · ${c.azimuth}°</span><span class="mono">${c.prb_util ?? "–"}% · ${c.sinr_db ?? "–"} dB</span><span>${esc(c.status === "ok" ? "normal" : c.status)}</span>`).join("")}</div>
    <div class="small muted">Modelled reach up to ${Math.max(...cs.map((c) => c.coverage_km)).toFixed(1)} km · power/tilt ${cs.map((c) => `${c.tx_power_dbm} dBm/${c.tilt_deg}°`).join(", ")}</div></div>`;
}
function mapCard(c) {
  if (!c) return "";
  const kind = { ok: "ok", watch: "warn", symptom: "warn", incident: "bad", critical: "bad", "no-data": "plain" }[c.status];
  return `<div class="mapcard"><div><b class="mono">${c.cell_id}</b> <span class="muted">${esc(c.site)} · ${esc(c.band)} · ${esc(c.zip_code)}</span></div>
    <div class="row small">${chip(c.status === "ok" ? "normal" : c.status, kind)}<span class="mono">PRB ${c.prb_util ?? "–"}%</span><span class="mono">drop ${c.drop_rate ?? "–"}%</span><span class="mono">SINR ${c.sinr_db ?? "–"} dB</span>
    <a class="hlink" href="#/cells/${c.cell_id}">Open cell</a></div></div>`;
}
function queueTable(list, now) {
  if (!list.length) return `<p class="empty pad">No open incidents. The cluster is normal. Open Demo controls on the left to create a problem.</p>`;
  return `<table class="dense"><thead><tr><th>Incident</th><th>Cell · area</th><th>Severity · status</th><th>Workflow</th><th>Owner</th><th class="r">Age</th></tr></thead><tbody>
    ${list.map((i) => `<tr class="click" data-inc="${i.id}"><td class="mono">${i.id}</td><td><span class="mono">${i.cell_id}</span>${i.related ? ` <span class="muted">+${i.related}</span>` : ""}<div class="small muted">${esc(i.site)} ${esc(i.zip_code || "")}</div></td>
      <td><div class="chips">${sevChip(i.severity)}${statusChip(i.status)}${i.fcc_status === "reportable" ? chip("FCC reportable", "bad") : ""}</div></td><td>${stageBar(i.stages)}<div class="small muted">${i.kind === "data_quality" ? "Data feed" : esc(CAUSE[i.top_cause] || "diagnosing")}</div></td>
      <td class="small">${esc(i.department || "–")}</td><td class="r mono small">${ageText(ageMin(i.created, now))}</td></tr>`).join("")}</tbody></table>`;
}
function worstTable(cells) {
  return `<table class="dense"><thead><tr><th>Cell</th><th>Area</th><th>Band</th><th class="r">Users</th><th class="r">PRB %</th><th class="r">Drop %</th><th class="r">SINR dB</th><th class="r">DL Mbps</th><th>Anomaly score</th><th>Triggered by</th><th>State</th></tr></thead><tbody>
    ${cells.map((c) => {
      const sc = c.score == null ? null : Math.min(1.5, c.score / 0.62);
      const kind = { ok: "ok", watch: "warn", symptom: "warn", incident: "bad", critical: "bad", "no-data": "plain" }[c.status];
      return `<tr class="click" data-cell="${c.cell_id}"><td class="mono">${c.cell_id}</td><td>${esc(c.site)}</td><td class="small">${esc(c.band.split(" ")[0])}</td>
        <td class="r mono">${c.active_users ?? "–"}</td><td class="r mono">${c.prb_util ?? "–"}</td><td class="r mono">${c.drop_rate ?? "–"}</td><td class="r mono">${c.sinr_db ?? "–"}</td><td class="r mono">${c.dl_thpt_mbps ?? "–"}</td>
        <td><span class="scorebar"><span style="width:${sc == null ? 0 : (sc / 1.5) * 100}%" class="${sc >= 1 ? "hot" : ""}"></span><i style="left:${100 / 1.5}%"></i></span><span class="mono small">${sc == null ? "–" : sc.toFixed(2)}</span></td>
        <td class="small">${esc((c.triggered_by || []).map((t) => TRIG[t] || t).join(", ") || "–")}</td><td>${chip(c.status === "ok" ? "normal" : c.status, kind)}</td></tr>`;
    }).join("")}</tbody></table>`;
}
function callsFeed(st) {
  if (!st.agent_calls.length) return `<p class="empty">${st.offline ? "Offline mode makes no model calls." : "No model calls yet. Create a problem from Demo controls."}</p>`;
  return `<pre class="term short">${st.agent_calls.slice().reverse().slice(0, 8).map((c) => {
    const t = new Date(c.ts * 1000).toLocaleTimeString("en-US", { hour12: false });
    return `<span class="t">${t}</span> <span class="a">${esc((c.agent || "").padEnd(18))}</span> ${esc((c.model || "").padEnd(26))} ${c.ok ? `<span class="okt">ok ${c.latency_s}s</span>` : `<span class="badt">FAIL ${esc((c.error || "").slice(0, 50))}</span>`}`;
  }).join("\n")}</pre>`;
}

async function renderAlarms() {
  const [rows, st] = await Promise.all([api("/api/alarms"), getState()]);
  lastAlarms = rows;
  const counts = { all: rows.filter((a) => !a.cleared).length };
  ["critical", "major", "minor", "warning"].forEach((k) => (counts[k] = rows.filter((a) => !a.cleared && a.severity === k).length));
  paint("alarms", `
    <div class="pagehead"><div><div class="crumb">Monitor / Alarm monitor</div><h1>Alarm monitor</h1>
      <p class="sub">Alarms from the simulated radio units, with X.733-style event type and probable cause. Acknowledging marks an alarm as seen. It does not clear it.</p></div>
      <div class="headright"><span class="small muted">${counts.all} active · ${st.unacked_alarms} not acknowledged</span></div></div>
    <section class="panel flat"><header class="toolbar">
      <div class="seg" role="group" aria-label="Severity">${[["all", "All"], ["critical", "Critical"], ["major", "Major"], ["minor", "Minor"], ["warning", "Warning"]].map(([k, l]) =>
        `<button class="${ui.alarmSev === k ? "on" : ""} ${k}" data-sev="${k}">${l} <span class="n">${counts[k]}</span></button>`).join("")}</div>
      <div class="seg" role="group" aria-label="State">${[["active", "Active"], ["cleared", "Cleared"], ["all", "All"]].map(([k, l]) => `<button class="${ui.alarmState === k ? "on" : ""}" data-state="${k}">${l}</button>`).join("")}</div>
      <input id="al-q" type="search" class="filter" placeholder="Filter by cell, area, alarm or text" value="${esc(ui.alarmText)}" aria-label="Filter alarms">
    </header><div class="body tablewrap" id="al-body">${alarmTable(rows)}</div></section>`);
  document.querySelectorAll("[data-sev]").forEach((b) => (b.onclick = () => { ui.alarmSev = b.dataset.sev; saveUi(); refresh(); }));
  document.querySelectorAll("[data-state]").forEach((b) => (b.onclick = () => { ui.alarmState = b.dataset.state; saveUi(); refresh(); }));
  const q = document.getElementById("al-q");
  q.oninput = () => { ui.alarmText = q.value; document.getElementById("al-body").innerHTML = alarmTable(lastAlarms); bindAlarmRows(); };
  bindAlarmRows();
}
function alarmTable(rows) {
  const t = ui.alarmText.toLowerCase();
  const list = rows.filter((a) => (ui.alarmSev === "all" || a.severity === ui.alarmSev) && (ui.alarmState === "all" || (ui.alarmState === "active" ? !a.cleared : a.cleared))
    && (!t || [a.cell_id, a.site, a.code, a.description, a.zip_code, a.probable_cause].join(" ").toLowerCase().includes(t)));
  if (!list.length) return `<p class="empty pad">No alarms match. ${ui.alarmState === "active" ? "The network has no active alarms with these filters." : ""}</p>`;
  return `<table class="dense alarms"><thead><tr><th></th><th>Severity</th><th>Alarm ID</th><th>Raised</th><th>Managed object</th><th>Area</th><th>Specific problem</th><th>Probable cause</th><th>Event type</th><th>Additional text</th><th>State</th><th>Ack</th><th>Incident</th></tr></thead><tbody>
    ${list.map((a) => `<tr class="${a.cleared ? "cleared" : ""}"><td class="sevcell ${a.severity}"></td><td>${chip(a.severity, { critical: "bad", major: "bad", minor: "warn", warning: "info" }[a.severity])}</td>
      <td class="mono small">${a.alarm_id}</td><td class="mono small">${hhmm(a.raised)}</td><td><a class="mono" href="#/cells/${a.cell_id}">${a.cell_id}</a></td><td>${esc(a.site)}</td>
      <td class="mono small">${esc(a.code)}</td><td>${esc(a.probable_cause)}</td><td class="small">${esc(a.event_type)}</td><td>${esc(a.description)}</td>
      <td class="small">${a.cleared ? "cleared " + hhmm(a.cleared) : "active"}</td>
      <td>${a.cleared ? "" : `<button class="btn mini ${a.ack ? "acked" : ""}" data-ack="${a.alarm_id}" title="${a.ack ? "Acknowledged by " + esc(a.ack.by) + " at " + hhmm(a.ack.at) + ". Click to undo" : "Acknowledge"}">${a.ack ? "✓ " + hhmm(a.ack.at) : "Ack"}</button>`}</td>
      <td>${a.incident ? `<a class="mono" href="#/incidents/${a.incident}">${a.incident}</a>` : `<span class="muted">–</span>`}</td></tr>`).join("")}</tbody></table>`;
}
function bindAlarmRows() {
  document.querySelectorAll("[data-ack]").forEach((b) => (b.onclick = async () => { b.disabled = true; await api(`/api/alarms/${b.dataset.ack}/ack`, { body: {} }); refresh(); }));
}

async function renderCells() {
  const st = await getState();
  if (!st.cells.some((c) => c.cell_id === selectedCell)) selectedCell = st.cells[0].cell_id;
  const c = await api("/api/cells/" + selectedCell);
  const me = st.cells.find((x) => x.cell_id === selectedCell);
  const inc = st.incidents.find((i) => i.cell_id === selectedCell && OPEN.has(i.status));
  const sites = {};
  st.cells.forEach((x) => (sites[x.site] ||= []).push(x));
  const f = ui.treeFilter.toLowerCase();
  const tree = Object.entries(sites).filter(([s, cs]) => !f || s.toLowerCase().includes(f) || cs.some((x) => x.cell_id.toLowerCase().includes(f) || x.zip_code.includes(f)))
    .map(([s, cs]) => `<div class="node"><div class="site"><span>${esc(s)}</span><span class="small muted mono">${esc(cs[0].zip_code)}</span></div>
      ${cs.map((x) => `<a href="#/cells/${x.cell_id}" class="leaf ${x.cell_id === selectedCell ? "on" : ""}"><i class="led ${{ ok: "ok", watch: "warn", symptom: "warn", incident: "bad", critical: "bad", "no-data": "muted" }[x.status]}"></i><span class="mono">${x.cell_id}</span><span class="small muted">S${x.sector} · ${esc(x.band.split(" ")[0])}</span></a>`).join("")}</div>`).join("");
  const rows = c.history.filter((r) => !r.missing);
  const labels = rows.map((r) => hhmm(r.ts));
  const K = [["prb_util", "PRB utilisation", "%", 90, "var(--accent)"], ["active_users", "Active users", "", null, "var(--info)"], ["dl_thpt_mbps", "DL throughput", "Mbps", null, "var(--info)"],
    ["drop_rate", "Drop rate", "%", 2, "var(--warn)"], ["sinr_db", "SINR", "dB", 6, "var(--info)"], ["cqi", "CQI", "", null, "var(--accent)"],
    ["ul_rssi_dbm", "UL RSSI", "dBm", -96, "var(--bad)"], ["ho_success", "Handover success", "%", 97, "var(--info)"], ["availability", "Availability", "%", 99.9, "var(--ok)"]];
  const tab = ui.cellTab;
  const det = c.detection || {};
  const cfg = c.config;
  let body = "";
  if (tab === "kpis") body = `<div class="chartgrid">${K.map(([k, n, u, thr, col]) => `<div class="chart"><h3>${n}${u ? ` <span class="muted">${u}</span>` : ""}<span class="mono">${rows.length ? rows[rows.length - 1][k] : "–"}</span></h3>${lineChart([{ name: n, values: rows.map((r) => r[k]), color: col }], labels, { threshold: thr, thresholdLabel: "limit", width: 360, height: 130, aria: n })}</div>`).join("")}</div>`;
  else if (tab === "alarms") body = c.alarms.length ? `<table class="dense"><thead><tr><th>Severity</th><th>Raised</th><th>Specific problem</th><th>Additional text</th><th>State</th></tr></thead><tbody>${c.alarms.slice().reverse().map((a) => `<tr><td>${chip(a.severity, { major: "bad", critical: "bad", minor: "warn", warning: "info" }[a.severity])}</td><td class="mono">${hhmm(a.raised)}</td><td class="mono small">${esc(a.code)}</td><td>${esc(a.description)}</td><td class="small">${a.cleared ? "cleared " + hhmm(a.cleared) : "active"}</td></tr>`).join("")}</tbody></table>` : `<p class="empty">No alarms on this cell in the last day.</p>`;
  else if (tab === "config") body = `<table class="dense"><thead><tr><th>Parameter</th><th class="r">Running</th><th class="r">Planned</th><th>Deviation</th></tr></thead><tbody>
      ${Object.keys(cfg.running).map((k) => `<tr><td>${nice(k)}</td><td class="r mono" ${cfg.deviations_from_plan[k] ? 'style="color:var(--warn);font-weight:600"' : ""}>${esc(cfg.running[k])}</td><td class="r mono">${esc(cfg.planned[k])}</td><td class="small">${cfg.deviations_from_plan[k] ? esc(JSON.stringify(cfg.deviations_from_plan[k])) : "–"}</td></tr>`).join("")}</tbody></table>
      <p class="small muted">Read over Open M-Plane (NETCONF get-config) from the simulated radio unit. Changes only happen through an approved incident, with confirmed-commit and automatic rollback.${cfg.pending_confirmed_commit ? " <b>A confirmed-commit is pending on this radio.</b>" : ""}</p>`;
  else body = `<dl class="kv"><dt>Isolation Forest score</dt><dd class="mono">${det.score ?? "–"} <span class="muted">/ alert at ${det.threshold ?? "–"}</span></dd>
      <dt>Cell baseline score</dt><dd class="mono">${det.baseline_score ?? "–"} <span class="muted">/ alert at 1.0</span></dd>
      <dt>Rules hit</dt><dd>${esc((det.breaches || []).join("; ") || "none")}</dd><dt>Triggered by</dt><dd>${esc((det.triggered_by || []).map((t) => TRIG[t] || t).join(", ") || "nothing (normal)")}</dd>
      <dt>Data quality</dt><dd>${det.quality_ok === false ? `<span style="color:var(--warn)">${esc((det.issues || []).join("; "))}</span>` : "ok"}</dd>
      ${det.baseline_contributors ? `<dt>Unusual for this hour</dt><dd>${esc((Array.isArray(det.baseline_contributors) ? det.baseline_contributors : Object.keys(det.baseline_contributors)).map((x) => (Array.isArray(x) ? x.join(" ") : x)).join(", ") || "none")}</dd>` : ""}</dl>
      <p class="small muted">An alert needs 2 consecutive windows from any detector. See the Model card for how each detector was chosen and measured.</p>`;
  paint("cells", `
    <div class="pagehead"><div><div class="crumb">Monitor / Cell explorer / ${esc(c.site)}</div><h1 class="mono">${c.cell_id}</h1>
      <p class="sub">${esc(c.site)} · sector ${c.sector} · azimuth ${c.azimuth}° · ${esc(c.band)} · ZIP ${esc(c.zip_code)} · neighbours ${c.neighbours.map((n) => `<a class="mono" href="#/cells/${n}">${n}</a>`).join(", ")}</p></div>
      <div class="headright">${chip(me.status === "ok" ? "normal" : me.status, { ok: "ok", watch: "warn", symptom: "warn", incident: "bad", critical: "bad", "no-data": "plain" }[me.status])}
        ${inc ? `<a class="btn" href="#/incidents/${inc.id}">Open ${inc.id}</a>` : ""}<button class="btn" id="cell-demo">Create problem here</button></div></div>
    <div class="explorer">
      <aside class="panel tree"><header><input id="tree-q" type="search" class="filter" placeholder="Filter sites, cells, ZIP" value="${esc(ui.treeFilter)}" aria-label="Filter the network tree"></header>
        <div class="body"><div class="root"><b>${esc(st.market.name)}</b><span class="small muted">${st.cells.length} cells</span></div>${tree || `<p class="empty">No match.</p>`}</div></aside>
      <section class="panel"><header class="tabhead">${tabs([["kpis", "Performance"], ["alarms", "Alarms", c.alarms.filter((a) => !a.cleared).length], ["config", "Configuration"], ["detection", "Detection"]], tab, "ctab")}<span class="small muted">last 12 h · 15-min ROP</span></header>
        <div class="body">${body}</div></section>
    </div>`);
  document.querySelectorAll("[data-ctab]").forEach((b) => (b.onclick = () => { ui.cellTab = b.dataset.ctab; saveUi(); refresh(); }));
  const tq = document.getElementById("tree-q");
  tq.onchange = tq.onsearch = () => { ui.treeFilter = tq.value; refresh(); };
  tq.onkeydown = (e) => { if (e.key === "Enter") { ui.treeFilter = tq.value; tq.blur(); refresh(); } };
  document.getElementById("cell-demo").onclick = () => { ui.demoOpen = true; saveUi(); refresh(); };
}

async function renderIncidents() {
  const st = await getState();
  const list = st.incidents.filter((i) => ui.incFilter === "all" || (ui.incFilter === "open" ? OPEN.has(i.status) : !OPEN.has(i.status)));
  paint("incidents", `
    <div class="pagehead"><div><div class="crumb">Operate / Incidents</div><h1>Incidents</h1><p class="sub">Each incident is investigated by the agents, checked by the safety layer and routed to one team.</p></div></div>
    <section class="panel flat"><header class="toolbar"><div class="seg">${[["open", "Open"], ["closed", "Closed"], ["all", "All"]].map(([k, l]) => `<button class="${ui.incFilter === k ? "on" : ""}" data-if="${k}">${l}</button>`).join("")}</div>
      <span class="small muted">${list.length} shown</span></header>
      <div class="body tablewrap">${list.length ? `<table class="dense"><thead><tr><th>Incident</th><th>Opened</th><th>Title</th><th>Area</th><th>Sev</th><th>Status</th><th>Workflow</th><th>Likely cause</th><th>Owner</th><th>Ticket</th></tr></thead><tbody>
        ${list.map((i) => `<tr class="click" data-inc="${i.id}"><td class="mono">${i.id}</td><td class="mono small">${hhmm(i.created)}</td><td>${esc(i.title)}${i.related ? ` <span class="muted small">+${i.related} symptom cells</span>` : ""}</td>
          <td>${esc(i.site)} <span class="small muted mono">${esc(i.zip_code || "")}</span></td><td>${sevChip(i.severity)}</td><td>${statusChip(i.status)}${i.fcc_status === "reportable" ? " " + chip("FCC", "bad") : ""}</td>
          <td>${stageBar(i.stages)}</td><td>${i.kind === "data_quality" ? "Data feed" : esc(CAUSE[i.top_cause] || "–")}${i.support ? ` <span class="small muted">(${esc(i.support)})</span>` : ""}</td><td class="small">${esc(i.department || "–")}</td><td class="mono small">${esc(i.ticket_id || "–")}</td></tr>`).join("")}</tbody></table>`
        : `<p class="empty pad">No ${ui.incFilter === "all" ? "" : ui.incFilter} incidents.</p>`}</div></section>`);
  document.querySelectorAll("[data-if]").forEach((b) => (b.onclick = () => { ui.incFilter = b.dataset.if; saveUi(); refresh(); }));
  document.querySelectorAll("tr[data-inc]").forEach((tr) => (tr.onclick = () => (location.hash = "#/incidents/" + tr.dataset.inc)));
}

async function renderIncident(id) {
  const [inc, st] = await Promise.all([api("/api/incidents/" + id), getState()]);
  const det = inc.detection || {};
  const t = inc.ticket;
  const photos = photosPanel(inc);
  const tab = ui.incTab[id] || "diagnosis";
  const rows = inc.kpi_window.filter((r) => !r.missing);
  const labels = rows.map((r) => hhmm(r.ts));
  let main = "";
  if (tab === "diagnosis") main = `<section class="panel"><header><h2>Evidence</h2><span class="small muted">KPIs for ${inc.cell_id}, last 8 h</span></header>
      <div class="body"><div class="grid cols-3">${chartSet(inc).map(([k, name, thr, color]) => `<div><h3>${name}</h3>${lineChart([{ name, values: rows.map((r) => r[k]), color }], labels, { threshold: thr, width: 380, height: 140, aria: name })}</div>`).join("")}</div>
      <div><h3 style="margin-bottom:6px">Alarms</h3>${inc.alarms.length ? `<div class="tablewrap"><table class="dense"><tbody>${inc.alarms.slice().reverse().map((a) => `<tr><td class="mono small">${hhmm(a.raised)}</td><td>${chip(a.severity, a.severity === "major" ? "bad" : a.severity === "warning" ? "warn" : "info")}</td><td class="mono small">${esc(a.code)}</td><td>${esc(a.description)}</td><td class="small muted">${a.cleared ? "cleared " + hhmm(a.cleared) : "active"}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">No alarms on this cell.</p>`}</div></div></section>
    ${inc.kind === "network" ? hypothesesPanel(inc) + verificationPanel(inc) : ""}`;
  else if (tab === "plans") main = inc.plans.length ? plansPanel(inc) + (inc.change ? changePanel(inc) : "") : `<section class="panel"><div class="body"><p class="empty">No plan yet. The planner runs after the analyst has enough evidence.</p></div></section>`;
  else if (tab === "evidence") main = inc.evidence.length ? evidencePanel(inc) : `<section class="panel"><div class="body"><p class="empty">The investigator has not called any tools yet.</p></div></section>`;
  else if (tab === "photos") main = photos;
  else if (tab === "console") main = agentConsole(inc);
  else if (tab === "report") main = reportPanel(inc);
  else main = `<section class="panel"><header><h2>Evidence-to-Action Safety Ledger</h2><span class="small muted">${inc.ledger.length} entries, oldest first</span></header>
      <div class="body"><ul class="ledger">${inc.ledger.map((l) => `<li><span class="t">${hhmm(l.sim_ts)}</span><span class="a">${esc(l.actor)}</span><span>${esc(l.summary)}</span></li>`).join("")}</ul></div></section>`;
  const facts = [["Cell", `<a class="mono" href="#/cells/${inc.cell_id}">${inc.cell_id}</a>`], ["Area", `${esc(inc.site)} <span class="mono muted">${esc(inc.zip_code || "")}</span>`], ["Band", esc(inc.band || "–")],
    ["Opened", `${day(inc.created)}`], ["Age", ageText(ageMin(inc.created, st.sim_time))], ["Owner", esc(inc.department || "–")], ["Ticket", `<span class="mono">${esc(inc.ticket_id || "–")}</span>`]];
  paint("incidents", `
    <div class="pagehead"><div><div class="crumb"><a href="#/incidents">Operate / Incidents</a> / ${inc.id}</div><h1>${esc(inc.title)}</h1></div>
      <div class="headright">${statusChip(inc.status)}${sevChip(inc.severity)}${chip(inc.engine.startsWith("Offline") ? "Offline rules" : "Meta Model API", inc.engine.startsWith("Offline") ? "warn" : "brand")}</div></div>
    <dl class="factbar">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
    ${inc.escalation ? `<div class="banner bad"><b>Escalated to NOC Shift Lead.</b> ${esc(inc.escalation)}${inc.checkpoint?.resumable ? ` <button class="btn mini" id="resume-inv">Resume from the ${esc(inc.checkpoint.phase)} step</button>` : ""}</div>` : ""}
    ${(inc.photos || []).some((p) => p.findings?.consistent_with_diagnosis === "no") ? `<div class="banner warn"><b>A site photo does not match the diagnosis.</b> Check Site photos before approving, and consider Request more info.</div>` : ""}
    <section class="panel"><header><h2>Investigation workflow</h2><span class="small muted">${inc.tool_calls} tool calls · ${inc.evidence_rounds + 1} evidence round(s) · reopened ${inc.reopen_count}×</span></header>
      <div class="body"><div class="timeline">${Object.entries(inc.stages).map(([k, v], i) => `<div class="step ${v.status}"><span class="dot">${v.status === "pass" ? "✓" : v.status === "fail" ? "✕" : i + 1}</span><span class="nm">${STAGE_NAMES[k]}</span><span class="nt">${esc(v.note || nice(v.status))}</span></div>`).join("")}</div></div></section>
    <div class="ws">
      <div class="ws-main">
        ${tabs([["diagnosis", "Diagnosis", inc.diagnosis ? inc.diagnosis.hypotheses.length : 0], ["plans", "Plans and safety", inc.plans.length], ["evidence", "Evidence", inc.evidence.length],
          photos && ["photos", "Site photos", (inc.photos || []).length], ["console", "Agent console", inc.agent_runs.length], ["report", "Report", inc.report ? "✓" : 0], ["ledger", "Ledger", inc.ledger.length]], tab, "itab")}
        <div class="grid" style="align-content:start">${main}</div></div>
      <div class="ws-side">
        ${workPlanPanel(inc)}
        ${evidenceRequestPanel(inc)}
        ${t ? decisionPanel(t, inc) : ""}
        ${inc.regulatory_ticket_data ? decisionPanel(inc.regulatory_ticket_data, inc) : ""}
        <section class="panel"><header><h2>Detection</h2></header><div class="body"><dl class="kv">
          <dt>Score</dt><dd class="mono">${det.score ?? "–"} <span class="muted">/ ${det.threshold ?? "–"}</span></dd>
          <dt>Rules hit</dt><dd>${esc((det.breaches || det.issues || []).join("; ") || "model anomaly")}</dd>
          <dt>Triggered by</dt><dd>${esc((det.triggered_by || []).map((x) => TRIG[x] || x).join(", ") || (det.quality_ok === false ? "data-quality checks" : "–"))}${det.baseline_score != null ? ` <span class="muted mono small">baseline ${det.baseline_score} / 1.0</span>` : ""}</dd>
          ${(inc.related_cells || []).length ? `<dt>Symptoms</dt><dd>${inc.related_cells.map((r) => `<a class="mono" href="#/cells/${r.cell_id}">${r.cell_id}</a> <span class="small muted">${esc((r.breaches || []).join(", "))}</span>`).join("<br>")}</dd>` : ""}
        </dl></div></section>
        ${inc.kind === "network" ? fccPanel(inc.fcc) : ""}
        <section class="panel"><header><h2>Radio config</h2><span class="small muted">M-Plane, simulated RU</span></header><div class="body">
          <table class="dense"><thead><tr><th>Parameter</th><th class="r">Running</th><th class="r">Planned</th></tr></thead><tbody>
          ${["tx_power_dbm", "tilt_deg", "bandwidth_mhz"].map((k) => `<tr><td>${nice(k)}</td><td class="r mono" style="${inc.config.deviations_from_plan[k] ? "color:var(--warn);font-weight:600" : ""}">${inc.config.running[k]}</td><td class="r mono">${inc.config.planned[k]}</td></tr>`).join("")}
          </tbody></table>${inc.config.pending_confirmed_commit ? `<p class="small" style="color:var(--warn)">Confirmed-commit pending: the radio rolls back by itself unless recovery is confirmed.</p>` : ""}</div></section>
      </div>
    </div>`);
  document.querySelectorAll("[data-itab]").forEach((b) => (b.onclick = () => { ui.incTab[id] = b.dataset.itab; refresh(); }));
  const cc = document.getElementById("copy-console");
  if (cc) cc.onclick = () => { navigator.clipboard?.writeText(document.getElementById("console-text").textContent); cc.textContent = "Copied"; };
  bindDecision(id);
  bindInvestigation(id);
  const rb = document.getElementById("resume-inv");
  if (rb) rb.onclick = async () => { rb.disabled = true; try { await api(`/api/incidents/${id}/resume`, { body: {} }); refresh(); } catch (e) { rb.disabled = false; rb.textContent = e.message; } };
}
function changePanel(inc) {
  return `<section class="panel"><header><h2>Open M-Plane change package</h2>${chip(inc.change.dry_run.ok ? "dry run passed" : "dry run failed", inc.change.dry_run.ok ? "ok" : "bad")}</header>
    <div class="body"><p class="small muted">${esc(inc.change.package.note)} Auto-rollback after ${inc.change.package.confirm_timeout_s / 60} minutes unless confirmed.</p><pre class="code">${esc(prettyXml(inc.change.package.edit_config))}\n${esc(inc.change.package.commit)}</pre></div></section>`;
}
function agentConsole(inc) {
  const lines = inc.ledger.map((l) => `<span class="t">${esc(l.sim_ts.slice(11, 19))}</span> <span class="a">${esc(l.actor.padEnd(15).slice(0, 15))}</span> <span class="e">${esc(l.event.padEnd(22).slice(0, 22))}</span> ${esc(l.summary)}`);
  const runs = (inc.agent_runs || []).map((r) => `<span class="a">${esc((r.agent || "").padEnd(19))}</span> ${esc((r.model || "").padEnd(27))} ${r.ok ? `<span class="okt">ok  </span>` : `<span class="badt">FAIL</span>`} ${String(r.latency_s ?? "").padStart(6)} s  ${r.usage && r.usage.total_tokens ? r.usage.total_tokens + " tokens" : ""}${r.error ? `  <span class="badt">${esc(r.error.slice(0, 90))}</span>` : ""}`);
  return `<section class="termwin"><div class="bar"><span><i></i><i></i><i></i></span><span>Agent console · ${inc.id}</span><span class="grow"></span><span>${inc.ledger.length} events · ${runs.length} model calls</span><button class="btn mini" id="copy-console">Copy</button></div>
    <pre class="term" id="console-text">${lines.join("\n")}${runs.length ? `\n\n<span class="h"># model calls (agent, model, result, latency, tokens)</span>\n` + runs.join("\n") : `\n\n<span class="h"># no model calls: ${esc(inc.engine)}</span>`}</pre></section>`;
}

async function renderDepartments() {
  const [tickets, st] = await Promise.all([api("/api/tickets"), getState()]);
  const list = tickets.filter((t) => ui.dept === "all" || t.department === ui.dept).sort((a, b) => (a.status === "pending" ? 0 : 1) - (b.status === "pending" ? 0 : 1) || b.id.localeCompare(a.id));
  const kind = { config_change: "Config change", field_action: "Field / RF action", escalation: "Escalation", data_quality: "Data feed", regulatory: "FCC report" };
  paint("departments", `
    <div class="pagehead"><div><div class="crumb">Operate / Approvals</div><h1>Approvals and team queues</h1>
      <p class="sub">When a fix needs a configuration change, a site visit or a human decision, the agents send it to one team. Nothing changes on the network until that team approves.</p></div></div>
    <div class="deptcards">${[["all", "All teams"], ...DEPTS.map((d) => [d, d])].map(([k, l]) => {
      const ts = tickets.filter((t) => k === "all" || t.department === k);
      const p = ts.filter((t) => t.status === "pending").length;
      return `<button class="deptcard ${ui.dept === k ? "on" : ""}" data-dept="${esc(k)}"><span class="label">${esc(l)}</span><span class="v">${p}</span><span class="small muted">waiting · ${ts.length} total</span></button>`;
    }).join("")}</div>
    <section class="panel flat"><div class="body tablewrap">${list.length ? `<table class="dense"><thead><tr><th>Ticket</th><th>Created</th><th>Team</th><th>Type</th><th>Cell</th><th>Recommendation</th><th>Second opinion</th><th>Status</th><th>Decided by</th></tr></thead><tbody>
      ${list.map((t) => `<tr class="click" data-inc="${t.incident_id}"><td class="mono">${t.id}</td><td class="mono small">${hhmm(t.created)}</td><td class="small">${esc(t.department)}</td><td class="small">${kind[t.kind] || esc(t.kind)}</td>
        <td class="mono">${t.cell_id}</td><td>${esc(t.recommendation).slice(0, 160)}${t.not_simulated ? " " + chip("not simulated", "warn") : ""}</td>
        <td>${t.review ? chip(t.review.verdict === "agree" ? "agrees" : t.review.concerns.length + " concern(s)", t.review.verdict === "agree" ? "ok" : "warn") : `<span class="muted">–</span>`}</td>
        <td>${chip(t.status, t.status === "pending" ? "warn" : ["approved", "done", "closed"].includes(t.status) ? "ok" : "plain")}</td><td class="small">${esc(t.decided_by || "–")}</td></tr>`).join("")}</tbody></table>`
      : `<p class="empty pad">Nothing sent to ${ui.dept === "all" ? "any team" : esc(ui.dept)} yet.</p>`}</div></section>`);
  document.querySelectorAll("[data-dept]").forEach((b) => (b.onclick = () => { ui.dept = b.dataset.dept; refresh(); }));
  document.querySelectorAll("tr[data-inc]").forEach((tr) => (tr.onclick = () => (location.hash = "#/incidents/" + tr.dataset.inc)));
}

async function renderLedger() {
  const [rows, st, ho] = await Promise.all([api("/api/ledger"), getState(), api("/api/handover")]);
  const q = ui.ledgerText.toLowerCase();
  const list = rows.filter((l) => !q || [l.incident_id, l.actor, l.event, l.summary].join(" ").toLowerCase().includes(q));
  paint("ledger", `<div class="pagehead"><div><div class="crumb">Assure / Safety ledger</div><h1>Evidence-to-Action Safety Ledger</h1>
      <p class="sub">Append-only record of every detection, tool call, model output, safety check, decision and change. Newest first.</p></div></div>
    <section class="panel"><header><h2>Shift handover</h2><span class="small muted">${ho.text ? `${esc(ho.by)} · ${hhmm(ho.generated_at)} ${esc(st.market.tz_label)} · ${ho.incidents} incident(s), ${Math.round(ho.input_chars / 1000)}k characters read` : st.offline ? "template until a Meta key is added" : `${esc(st.models.wonder)} reads every incident and the whole ledger`}</span></header><div class="body">
      ${ho.text ? `<pre class="code report" id="handover-text">${esc(ho.text)}</pre>` : `<p class="small muted">Write the handover the next NOC shift reads first: what is open and waiting on whom, FCC deadlines, what closed, and patterns across incidents.</p>`}
      <div class="row"><button class="btn" id="write-handover">${ho.text ? "Rewrite handover" : "Write shift handover"}</button>${ho.text ? `<button class="btn" id="copy-handover">Copy</button>` : ""}</div></div></section>
    <section class="panel flat"><header class="toolbar"><input id="lg-q" type="search" class="filter" placeholder="Filter by incident, actor or text" value="${esc(ui.ledgerText)}" aria-label="Filter the ledger"><span class="small muted">${list.length} of ${rows.length} entries</span></header>
      <div class="body tablewrap">${list.length ? `<table class="dense"><thead><tr><th>Time</th><th>Incident</th><th>Actor</th><th>Event</th><th>What happened</th></tr></thead><tbody>
      ${list.map((l) => `<tr class="click" data-inc="${l.incident_id}"><td class="mono">${hhmm(l.sim_ts)}</td><td class="mono">${l.incident_id}</td><td class="mono">${esc(l.actor)}</td><td>${esc(nice(l.event))}</td><td>${esc(l.summary)}</td></tr>`).join("")}</tbody></table>` : `<p class="empty pad">The ledger is empty.</p>`}</div></section>`);
  document.querySelectorAll("tr[data-inc]").forEach((tr) => (tr.onclick = () => (location.hash = "#/incidents/" + tr.dataset.inc)));
  const lq = document.getElementById("lg-q");
  lq.onkeydown = (e) => { if (e.key === "Enter") { ui.ledgerText = lq.value; lq.blur(); refresh(); } };
  lq.onsearch = lq.onchange = () => { ui.ledgerText = lq.value; refresh(); };
  const hb = document.getElementById("write-handover");
  hb.onclick = async () => {
    busy = true; hb.disabled = true; hb.textContent = "Writing…";
    try { await api("/api/handover", { body: {} }); } catch (e) { alert(e.message); }
    busy = false; refresh();
  };
  const cb = document.getElementById("copy-handover");
  if (cb) cb.onclick = () => { navigator.clipboard?.writeText(document.getElementById("handover-text").textContent); cb.textContent = "Copied"; };
}

function renderLogin() {
  app.innerHTML = `<div class="login"><div class="form">
    <div class="brandmark">${LOGO}<span>RAN Sentinel</span></div>
    <p class="tag">Network investigation and reliability for Northstar Connect engineers.</p>
    <p class="tag">Open a sample shift with 36 simulated LTE cells. No account, password or API key is needed.</p>
    <button class="btn primary" id="demo-start">Explore engineer demo</button>
    <p id="err" class="err" hidden></p>
    <footer>Demo system with simulated network data. Customer view: <a href="/connect/">Northstar Connect</a></footer></div>
    <div class="art"><svg viewBox="0 0 600 600" preserveAspectRatio="xMidYMid slice" aria-hidden="true">${loginArt()}</svg>
      <div class="cap"><b>Detect, investigate, prove it's safe, then act.</b>Every AI step is checked by fixed safety rules and recorded in the ledger. Nothing changes on the network without an engineer's approval.</div></div></div>`;
  document.getElementById("demo-start").onclick = async (e) => {
    const button = e.currentTarget, err = document.getElementById("err");
    button.disabled = true;
    try {
      await api("/api/demo/start", { body: { portal: "ops" } });
      location.hash = "#/dashboard";
    } catch (x) { err.hidden = false; err.textContent = x.message; button.disabled = false; }
  };
}
function loginArt() {
  let g = "";
  const sites = [[120, 140], [300, 90], [470, 170], [200, 300], [380, 280], [520, 380], [110, 450], [300, 470], [460, 530]];
  sites.forEach(([x, y], i) => {
    for (let k = 1; k <= 3; k++) g += `<circle cx="${x}" cy="${y}" r="${k * 34}" fill="none" stroke="#7fd0d4" stroke-opacity="${0.18 - k * 0.04}"/>`;
    g += `<circle cx="${x}" cy="${y}" r="3" fill="#7fd0d4"/>`;
    if (i) g += `<line x1="${sites[i - 1][0]}" y1="${sites[i - 1][1]}" x2="${x}" y2="${y}" stroke="#7fd0d4" stroke-opacity=".12"/>`;
  });
  return g;
}

function chartSet(inc) {
  const cause = inc.diagnosis?.hypotheses?.[0]?.cause;
  const prb = ["prb_util", "PRB utilisation %", 90, "var(--accent)"], drop = ["drop_rate", "Drop rate %", 2, "var(--warn)"],
    sinr = ["sinr_db", "SINR dB", 6, "var(--info)"], far = ["far_user_share", "Far-user share", 0.18, "var(--accent)"],
    rssi = ["ul_rssi_dbm", "UL RSSI dBm", -96, "var(--bad)"], ho = ["ho_success", "Handover success %", 97, "var(--info)"];
  if (cause === "overshooting_coverage") return [far, sinr, drop];
  if (cause === "external_interference") return [sinr, rssi, drop];
  if (cause === "hardware_fault") return [drop, ho, prb];
  return [prb, drop, sinr];
}
function hypothesesPanel(inc) {
  const d = inc.diagnosis;
  if (!d) return `<section class="panel"><header><h2>Root-cause hypotheses</h2></header><div class="body"><p class="empty">The analyst is waiting for evidence.</p></div></section>`;
  return `<section class="panel"><header><h2>Root-cause hypotheses</h2><span class="small muted">uncertainty: ${esc(d.uncertainty || "–")} · support is evidence strength, not a probability</span></header>
    <div class="body" style="gap:0">${d.hypotheses.map((h, i) => `<div class="hyp ${i === 0 ? "top" : ""}"><span class="rk">${h.rank}</span>
      <div><b>${esc(CAUSE[h.cause] || h.cause)}</b><div class="small muted" style="margin-top:2px">${esc(h.reasoning || "")}</div>
        <div style="margin-top:6px">${(h.supporting_evidence || []).map((e) => `<span class="evtag plus">+${e}</span>`).join("")}${(h.contradicting_evidence || []).map((e) => `<span class="evtag minus">−${e}</span>`).join("")}</div></div>
      <div><span class="small">${esc(nice(h.support))}</span><div class="meter"><span style="width:${SUPPORT_W[h.support] || 0}%"></span></div></div></div>`).join("")}</div></section>`;
}
function evName(inc, id) {
  const e = inc.evidence.find((x) => x.id === id);
  return e ? nice(e.args?.check || e.tool.replace(/^get_|^run_/, "")) : "";
}
const WP_ICON = { done: "✓", doing: "◐", todo: "○", dropped: "✕" };
function workPlanPanel(inc) {
  const wp = inc.work_plan;
  if (!wp || !wp.steps.length) return "";
  const cp = inc.checkpoint;
  return `<section class="panel"><header><h2>Investigation plan</h2><span class="small muted">revision ${wp.revision}${cp && cp.saved_at ? ` · saved ${hhmm(cp.saved_at)}` : ""}</span></header><div class="body">
    ${wp.note ? `<p class="small"><b>Now:</b> ${esc(wp.note)}</p>` : ""}
    <ul class="vlist wplan">${wp.steps.map((s) => `<li class="${s.status === "done" ? "ok" : s.status === "dropped" ? "bad dropped" : s.status}"><span>${WP_ICON[s.status] || "○"}</span><span>${esc(s.step)}</span></li>`).join("")}</ul>
    ${wp.history.length > 1 ? `<details><summary class="small muted">Why it changed (${wp.history.length})</summary><ul class="ledger">${wp.history.slice().reverse().map((h) => `<li><span class="t">${hhmm(h.at)}</span><span class="a">${esc(h.by)}</span><span>${esc(h.note)}</span></li>`).join("")}</ul></details>` : ""}
  </div></section>`;
}
function evidenceRequestPanel(inc) {
  const reqs = inc.evidence_requests || [];
  if (!reqs.length) return "";
  const open = reqs.find((r) => r.status === "open" && inc.status === "AWAITING_EVIDENCE");
  const key = "ev-" + inc.id;
  const files = open ? [...(inc.photos || []).filter((p) => p.uploaded >= open.requested_at).map((p) => ({ ...p, type: "photo", name: p.id + " site photo" })),
    ...(inc.attachments || []).filter((d) => d.uploaded >= open.requested_at)] : [];
  return `<section class="panel${open ? " decision" : ""}" data-evreq="${inc.id}"><header><h2>Field evidence</h2>${open ? chip("investigation paused", "warn") : chip(reqs.length + " answered", "ok")}</header><div class="body">
    ${reqs.map((r) => `<div class="evreq"><span class="label">${esc(r.id)} · asked by the ${esc(r.by)}</span><p><b>${esc(r.ask)}</b></p><p class="small muted">${esc(r.why)}</p>
      ${r.answer ? `<p class="small">Answered by ${esc(r.answer.by)} <span class="mono">${esc(r.answer.evidence_id)}</span>: ${esc(r.answer.note)}${r.answer.photos.length + (r.answer.documents || []).length ? ` <span class="muted">(${r.answer.photos.length + (r.answer.documents || []).length} attachment${r.answer.photos.length + (r.answer.documents || []).length > 1 ? "s" : ""})</span>` : ""}</p>` : ""}</div>`).join("")}
    ${open ? `<div class="field"><label for="evnote-${inc.id}">What did you find on site?</label><textarea id="evnote-${inc.id}" placeholder="e.g. spectrum analyser shows a narrowband emitter east of the site">${esc(drafts[key] || "")}</textarea></div>
      <div class="field"><span class="flabel">Attachments <span class="muted">(optional)</span></span>
        <label class="dropzone" for="evfile-${inc.id}"><input type="file" id="evfile-${inc.id}" accept="${ATTACH_ACCEPT}" multiple hidden>
          <span><b>Attach files</b><br><span class="small muted">Photo (JPEG, PNG, WebP), CSV, PDF, DOCX or TXT · up to 10 MB each</span></span></label>
        ${files.length ? `<ul class="attlist">${files.map(attachRow).join("")}</ul>` : ""}
        <p class="small muted" id="evup-${inc.id}" hidden></p></div>
      <p class="small muted">Muse Spark reads each file as it is attached. Your note and ${files.length ? `these ${files.length} file${files.length > 1 ? "s" : ""}` : "any files"} go into the investigation, which resumes with everything gathered so far.</p>
      <div class="row"><button class="btn primary" data-ev="send" data-busy="Sending and resuming…">Send and resume investigation</button></div><p class="err dmsg" hidden></p>` : ""}
  </div></section>`;
}
const ATTACH_ACCEPT = ".jpg,.jpeg,.png,.webp,.csv,.pdf,.docx,.txt,image/jpeg,image/png,image/webp,text/csv,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain";
function attachRow(f) {
  const fd = f.findings, kind = f.type === "photo" ? "PHOTO" : (f.kind || "").toUpperCase();
  const fit = fd ? { yes: ["fits diagnosis", "ok"], no: ["does not fit", "bad"], unclear: ["unclear", "plain"] }[fd.consistent_with_diagnosis] : null;
  const link = f.type === "photo" ? `/api/photos/${f.id}` : `/api/files/${f.id}`;
  return `<li><span class="ftype">${esc(kind)}</span><div class="fbody"><a href="${link}" target="_blank" rel="noopener" class="fname">${esc(f.name)}</a>
    ${fd ? `<span class="small">${esc(fd.summary)}</span>` : `<span class="small muted">${esc((f.errors || []).join("; ") || "stored, not analysed")}</span>`}
    <span class="small muted">${fd ? esc(fd.by) : ""}${f.evidence_id ? ` · <span class="mono">${esc(f.evidence_id)}</span>` : ""}</span></div>${fit ? chip(fit[0], fit[1]) : ""}</li>`;
}
async function attachFiles(id, list) {
  const status = document.getElementById("evup-" + id), err = document.querySelector(`[data-evreq="${id}"] .dmsg`);
  busy = true; err.hidden = true;
  try {
    for (const [i, f] of [...list].entries()) {
      status.hidden = false;
      status.innerHTML = `<span class="spin"></span> Reading ${esc(f.name)} with Muse Spark (${i + 1} of ${list.length})…`;
      const img = /^image\//.test(f.type);
      const blob = img ? await shrinkImage(f) : f;
      await upload(`/api/incidents/${id}/attachments?name=${encodeURIComponent(f.name)}`, blob, img ? "image/jpeg" : (f.type || "application/octet-stream"));
    }
    status.hidden = true;
  } catch (e) { status.hidden = true; err.hidden = false; err.textContent = e.message; }
  busy = false; refresh();
}
function signoffBlock(inc) {
  const v = inc.verification, so = inc.rca_signoff;
  if (!v.passed) return "";
  if (so && so.decision === "confirm" && so.cause === v.cause) return `<div class="banner ok"><b>Root cause signed off</b> by ${esc(so.by)}${so.note ? `: ${esc(so.note)}` : ""}</div>`;
  const key = "rca-" + inc.id;
  const canDispute = ["AWAITING_DEPARTMENT", "ESCALATED"].includes(inc.status);
  return `<div class="signoff" data-rca="${inc.id}"><span class="label">Engineer sign-off</span>
    ${so && so.decision === "dispute" ? `<p class="small muted">Earlier diagnosis (${esc(CAUSE[so.cause] || so.cause)}) was disputed by ${esc(so.by)}: ${esc(so.note)}</p>` : ""}
    <div class="field"><label for="rcanote-${inc.id}">Note (required to dispute)</label><textarea id="rcanote-${inc.id}" rows="2">${esc(drafts[key] || "")}</textarea></div>
    <div class="row"><button class="btn primary" data-rcad="confirm">Sign off root cause</button>${canDispute ? `<button class="btn" data-rcad="dispute">Dispute and re-investigate</button>` : ""}</div><p class="err dmsg" hidden></p></div>`;
}
function bindInvestigation(id) {
  const wire = (sel, key, url, body) => document.querySelectorAll(sel).forEach((panel) => {
    const note = panel.querySelector("textarea");
    if (note) note.oninput = () => (drafts[key] = note.value);
    panel.querySelectorAll("button[data-ev], button[data-rcad]").forEach((b) => (b.onclick = async () => {
      const m = panel.querySelector(".dmsg");
      b.disabled = true;
      try {
        await api(url, { body: body(b, note) });
        delete drafts[key];
        refresh();
      } catch (e) { m.hidden = false; m.textContent = e.message; b.disabled = false; }
    }));
  });
  const fi = document.getElementById("evfile-" + id);
  if (fi) fi.onchange = () => { if (fi.files.length) attachFiles(id, fi.files); fi.value = ""; };
  const dz = fi && fi.closest(".dropzone");
  if (dz) {
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); };
    dz.ondragleave = () => dz.classList.remove("over");
    dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("over"); if (e.dataTransfer.files.length) attachFiles(id, e.dataTransfer.files); };
  }
  wire(`[data-evreq="${id}"]`, "ev-" + id, `/api/incidents/${id}/evidence`, (b, n) => ({ note: n ? n.value : "" }));
  wire(`[data-rca="${id}"]`, "rca-" + id, `/api/incidents/${id}/rca`, (b, n) => ({ decision: b.dataset.rcad, note: n ? n.value : "" }));
}
function verificationPanel(inc) {
  const v = inc.verification, cl = inc.checklist || [];
  if (!v) return "";
  const cov = v.coverage;
  return `<section class="panel"><header><h2>Diagnosis verification</h2>${chip(v.passed ? `Verified on attempt ${v.attempt}` : `Refused: ${v.failed.join(", ")}`, v.passed ? "ok" : "bad")}</header>
    <div class="body"><p class="small muted">Code checks the diagnosis before any plan is drafted: a hidden engineering playbook, every stated number looked up in its evidence, root-cause rules, and a claims check by a second model${v.claims_by ? ` (${esc(v.claims_by)})` : ""}. Three refusals go to a person.</p>
      <div class="grid cols-2" style="gap:14px">
        <div><h3>Playbook for ${esc(CAUSE[cov.cause] || cov.cause)} · ${cov.covered}/${cov.total}</h3><ul class="vlist">${cov.items.map((i) => `<li class="${i.covered ? "ok" : "bad"}"><span>${i.covered ? "✓" : "✕"}</span>${esc(i.item)}</li>`).join("")}</ul></div>
        <div><h3>Key facts</h3>${v.facts.length ? `<ul class="vlist">${v.facts.map((f) => `<li class="${f.verified ? "ok" : "bad"}"><span>${f.verified ? "✓" : "✕"}</span><span class="mono small">${esc(f.evidence_id)}</span> ${esc(evName(inc, f.evidence_id))} · ${esc(nice(f.metric))} = <b class="mono">${esc(f.value)}</b></li>`).join("")}</ul>` : `<p class="empty">No facts stated.</p>`}
          ${cl.length ? `<h3 style="margin-top:10px">Investigator checklist</h3><ul class="vlist">${cl.map((i) => `<li class="${i.done ? "ok" : ""}"><span>${i.done ? "✓" : "○"}</span>${esc(i.item)}${i.counter_evidence ? ` ${chip("counter-evidence", "info")}` : ""}</li>`).join("")}</ul>` : ""}</div>
      </div>
      ${signoffBlock(inc)}
      ${v.claims.length ? `<div class="banner bad"><b>Unsupported claims:</b> ${v.claims.map((c) => esc(c.claim) + (c.why ? ` <span class="muted">(${esc(c.why)})</span>` : "")).join("; ")}</div>` : ""}
      <div class="tablewrap"><table class="rules"><thead><tr><th>Check</th><th>Result</th><th>Reason</th></tr></thead><tbody>
        ${v.rules.map((r) => `<tr><td>${esc(r.rule)}</td><td class="st ${r.status}">${r.status}</td><td>${esc(r.reason)}</td></tr>`).join("")}</tbody></table></div></div></section>`;
}
function plansPanel(inc) {
  return `<section class="panel"><header><h2>Remediation plans and safety checks</h2><span class="small muted">${inc.plans.length} draft(s)</span></header><div class="body">
    ${inc.plans.map((p) => {
      const a = p.plan.action || {};
      const v = p.validation;
      const sb = p.sandbox;
      return `<div class="grid" style="gap:8px;padding-bottom:12px;border-bottom:1px solid var(--line)">
        <div class="planhead"><h3>Plan v${p.attempt}${p.plan.red_team ? ` ${chip("red-team draft", "warn")}` : ""}</h3>${chip(v.passed ? "Passed: " + v.summary : !v.simulated && !v.failed.length ? "Not simulated" : "Rejected: " + v.summary, v.passed ? "ok" : !v.failed.length ? "warn" : "bad")}</div>
        <p>${esc(p.plan.summary)}</p>
        <dl class="kv"><dt>Action</dt><dd class="mono">${esc(a.type)}${a.delta != null ? ` ${a.delta > 0 ? "+" : ""}${a.delta}` : ""} on ${esc(a.cell_id)}</dd>
          <dt>Checks first</dt><dd>${esc((p.plan.prerequisite_checks || []).join(", ") || "none")}</dd>
          <dt>Expected</dt><dd>${esc(p.plan.expected_effect || "–")}</dd>
          <dt>Rollback</dt><dd>${p.plan.rollback && p.plan.rollback.restore_value != null ? `restore ${esc(p.plan.rollback.restore_value)} if ${esc(p.plan.rollback.trigger)}` : "none given"}</dd>
          ${sb ? `<dt>Twin what-if</dt><dd><span class="mono">PRB ${sb.before.prb_util}→${sb.after.prb_util}% · neighbour ${sb.neighbour_before_prb}→${sb.neighbour_after_prb}% · far users ${sb.before.far_user_share}→${sb.after.far_user_share} · coverage loss ${sb.coverage_loss_pct}%</span>${sb.rf ? `<br><span class="mono small">RF twin: ${sb.rf.served_before} served points, ${sb.rf.new_holes} new holes, ${sb.rf.handed_to_neighbours} to neighbours · median RSRP ${sb.rf.median_rsrp_before}→${sb.rf.median_rsrp_after} dBm</span>` : ""}<br><span class="small muted">${esc(sb.engine)}</span></dd>` : p.sandbox_error ? `<dt>Twin what-if</dt><dd style="color:var(--warn)">Not run: ${esc(p.sandbox_error)}</dd>` : ""}
        </dl>
        <div class="tablewrap"><table class="rules"><thead><tr><th>Rule</th><th>Result</th><th>Reason</th></tr></thead><tbody>
          ${v.rules.map((r) => `<tr><td>${esc(r.rule)}</td><td class="st ${r.status}">${r.status}</td><td>${esc(r.reason)}</td></tr>`).join("")}</tbody></table></div></div>`;
    }).join("")}</div></section>`;
}
function evidencePanel(inc) {
  return `<section class="panel"><header><h2>Evidence collected by the investigator</h2><span class="small muted">${inc.evidence.length} items</span></header><div class="body" style="gap:0">
    ${inc.evidence.map((e) => `<details class="ev"><summary><span class="evtag">${e.id}</span><code>${esc(e.tool)}</code><span class="small muted mono">${esc(JSON.stringify(e.args))}</span>${e.error ? `<span class="small" style="color:var(--bad)">failed: ${esc(e.error)}</span>` : ""}</summary>
      ${e.result ? `<pre class="code" style="margin-top:6px">${esc(JSON.stringify(e.result, null, 1).slice(0, 2500))}</pre>` : ""}</details>`).join("")}</div></section>`;
}
function decisionPanel(t, inc) {
  const open = ["pending", "in_progress"].includes(t.status);
  const kindText = { config_change: "Configuration change for approval", field_action: "Field / RF action", escalation: "Escalation", data_quality: "Data feed problem", regulatory: "FCC outage report (NORS)" }[t.kind];
  let buttons = "";
  if (open && t.kind === "config_change" && t.status === "pending") buttons = `<button class="btn primary" data-d="approve">Approve change</button><button class="btn" data-d="reject">Reject</button><button class="btn" data-d="more_info">Request more info</button>`;
  else if (open && t.kind === "field_action" && t.status === "pending") buttons = `<button class="btn primary" data-d="approve">Accept and dispatch</button><button class="btn" data-d="reject">Reject</button><button class="btn" data-d="more_info">Request more info</button>`;
  else if (open && (t.kind === "field_action" || t.kind === "data_quality")) buttons = `<button class="btn primary" data-d="resolved">Mark fixed</button>`;
  else if (open && t.kind === "regulatory") buttons = `<button class="btn primary" data-d="filed">Mark NORS notification filed</button>`;
  else if (open && t.kind === "escalation") buttons = `<button class="btn" data-d="more_info">Run new investigation</button><button class="btn" data-d="close">Close incident</button>`;
  return `<section class="panel decision" data-ticket="${t.id}"><header><h2>${esc(t.department)}</h2>${chip(t.status, t.status === "pending" ? "warn" : ["approved", "done", "closed"].includes(t.status) ? "ok" : "plain")}</header>
    <div class="body"><span class="label">${kindText}</span><p class="rec">${esc(t.recommendation)}</p>
    ${ticketFacts(t)}
    ${t.review ? reviewBlock(t.review) : ""}
    ${t.kind === "escalation" ? briefBlock(inc.escalation_brief) : ""}
    ${t.not_simulated ? `<div class="banner warn">The twin was unavailable, so this plan was not simulated. Review it with extra care.</div>` : ""}
    ${open && buttons ? `<div class="field"><div class="labelrow"><label for="note-${t.id}">Note or reason${t.kind === "regulatory" ? " (NORS reference)" : " (required to reject)"}</label>${lastState && !lastState.offline ? `<button class="btn mini mic" type="button" data-mic title="Dictate with ${esc(lastState.models.voice)}">${MIC} Dictate</button>` : ""}</div><textarea id="note-${t.id}">${esc(drafts[t.id] || "")}</textarea></div>
      ${heard[t.id] ? `<p class="small heard">Your note sounds like <b>${esc(nice(heard[t.id]).toLowerCase())}</b>. The matching button is highlighted; nothing is sent until you click it.</p>` : ""}
      <div class="row">${heard[t.id] ? buttons.replace(`data-d="${heard[t.id]}"`, `data-d="${heard[t.id]}" data-heard`) : buttons}</div><p class="err dmsg" hidden></p>` :
      t.decided_by ? `<p class="small muted">Decided by ${esc(t.decided_by)}${t.decision_note ? `: “${esc(t.decision_note)}”` : ""}</p>` : ""}
    ${t.kind === "config_change" && t.status === "pending" ? `<p class="small muted">Approving sends an Open M-Plane change to the simulated radio unit with automatic rollback.</p>` : ""}</div></section>`;
}
function bindDecision(id) {
  document.querySelectorAll(".decision[data-ticket]").forEach((panel) => {
    const tid = panel.dataset.ticket;
    const note = panel.querySelector("textarea");
    if (note) note.oninput = () => (drafts[tid] = note.value);
    const mic = panel.querySelector("[data-mic]");
    if (mic) {
      micButton(mic, "/api/voice", (r) => {
        busy = false;
        if (!r.text) { showMsg(panel, "Nothing was heard. Try again a little closer to the microphone."); return; }
        drafts[tid] = ((note.value ? note.value.trim() + " " : "") + r.text).trim();
        if (r.intent && panel.querySelector(`[data-d="${r.intent}"]`)) heard[tid] = r.intent; else delete heard[tid];
        refresh();
      }, (e) => { busy = false; showMsg(panel, e); });
      const inner = mic.onclick;
      mic.onclick = (ev) => { busy = true; return inner(ev); };
    }
    panel.querySelectorAll("[data-d]").forEach((b) => (b.onclick = async () => {
      const m = panel.querySelector(".dmsg");
      b.disabled = true;
      try {
        await api(`/api/tickets/${tid}/decide`, { body: { decision: b.dataset.d, note: note ? note.value : "" } });
        delete drafts[tid]; delete heard[tid];
        refresh();
      } catch (e) { m.hidden = false; m.textContent = e.message; b.disabled = false; }
    }));
  });
  bindPhotos(id);
  const rb = document.getElementById("write-report");
  if (rb) rb.onclick = async () => {
    rb.disabled = true; rb.textContent = "Writing…";
    try { await api(`/api/incidents/${id}/report`, { body: {} }); } catch (e) { alert(e.message); }
    refresh();
  };
  const cb = document.getElementById("copy-report");
  if (cb) cb.onclick = () => { navigator.clipboard?.writeText(document.getElementById("report-text").textContent); cb.textContent = "Copied"; };
}
function showMsg(panel, text) { const m = panel.querySelector(".dmsg"); if (m) { m.hidden = false; m.textContent = text; } }
function briefBlock(b) {
  if (!b) return `<p class="small muted">The Escalation Briefer is writing a brief for you…</p>`;
  return `<div class="review"><span class="label">Escalation brief · ${esc(b.by)}</span>
    <p><b>Known:</b> ${esc(b.what_we_know)}</p>${b.what_is_unclear ? `<p><b>Unclear:</b> ${esc(b.what_is_unclear)}</p>` : ""}
    ${b.next_checks.length ? `<p><b>Next read-only checks:</b> ${b.next_checks.map((c) => `<code>${esc(c)}</code>`).join(" ")}</p>` : ""}
    <p class="small muted">Suggested owner: ${esc(b.suggested_owner)}</p></div>`;
}
function photosPanel(inc) {
  const cause = inc.diagnosis?.hypotheses?.[0]?.cause;
  const photos = inc.photos || [];
  const field = ["hardware_fault", "external_interference"].includes(cause) || inc.ticket?.kind === "field_action" || (inc.evidence_requests || []).some((r) => r.status === "open");
  if (inc.kind !== "network" || (!field && !photos.length)) return "";
  const st = lastState || { offline: true, models: {} };
  return `<section class="panel" id="photos"><header><h2>Site photos</h2><span class="small muted">${st.offline ? "stored only: analysis needs a Meta key" : `${esc(st.models.sam)} finds objects · ${esc(st.models.vision)} reads them`}</span></header><div class="body">
    ${photos.length ? photos.slice().reverse().map(photoCard).join("") : `<p class="small muted">Field technicians can add a photo of the antenna, cables or connectors. It is added to the evidence and checked against the diagnosis. It never changes the incident on its own.</p>`}
    <form id="photo-form" class="photoform"><input id="photo-file" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" aria-label="Site photo">
      <input id="photo-note" type="text" placeholder="Note, e.g. 'sector 2 jumper, top of mast'" aria-label="Photo note" maxlength="300">
      <button class="btn" id="photo-send" type="submit">Add photo</button></form><p class="err" id="photo-msg" hidden></p></div></section>`;
}
function photoCard(p) {
  const f = p.findings;
  const w = p.width || 1000, h = p.height || 750;
  const boxes = p.width ? p.detections.map((d) => `<g><rect x="${d.x1}" y="${d.y1}" width="${d.x2 - d.x1}" height="${d.y2 - d.y1}" fill="none" stroke="var(--accent)" stroke-width="${Math.max(2, w / 300)}"/>
    <text x="${d.x1 + 4}" y="${d.y1 + Math.max(14, w / 40)}" font-size="${Math.max(12, w / 45)}" fill="var(--accent)" paint-order="stroke" stroke="#000" stroke-width="3">${esc(d.label)}${d.conf != null ? " " + Math.round(d.conf * 100) + "%" : ""}</text></g>`).join("") : "";
  const kind = { yes: "ok", no: "bad", unclear: "warn" }[f?.consistent_with_diagnosis] || "plain";
  return `<div class="photo"><div class="frame"><img src="/api/photos/${p.id}" alt="Site photo ${p.id}${p.note ? ": " + esc(p.note) : ""}" loading="lazy">
      ${boxes ? `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">${boxes}</svg>` : ""}</div>
    <div class="grid" style="gap:6px;align-content:start"><div class="row"><span class="evtag">${esc(p.evidence_id || "")}</span><b class="mono">${p.id}</b><span class="small muted">${hhmm(p.uploaded)} · ${esc(p.by)}</span></div>
      ${p.note ? `<p class="small">“${esc(p.note)}”</p>` : ""}
      ${f ? `<div class="row">${chip(f.consistent_with_diagnosis === "yes" ? "Fits diagnosis" : f.consistent_with_diagnosis === "no" ? "Does not fit diagnosis" : "Unclear", kind)}<span class="small muted">${p.detections.length} object(s) · ${esc(f.by)}</span></div>
        <p>${esc(f.summary)}</p>${f.visible_issues.length ? `<ul class="small">${f.visible_issues.map((i) => `<li><b>${esc(i.object)}:</b> ${esc(i.issue)}</li>`).join("")}</ul>` : ""}
        ${f.next_step ? `<p class="small muted">Next: ${esc(f.next_step)}</p>` : ""}` : `<p class="small muted">Stored without analysis${p.errors.length ? ": " + esc(p.errors[0]) : ""}.</p>`}</div></div>`;
}
function bindPhotos(id) {
  const form = document.getElementById("photo-form");
  if (!form) return;
  const msg = document.getElementById("photo-msg"), btn = document.getElementById("photo-send");
  document.getElementById("photo-file").onchange = () => (busy = true);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const file = document.getElementById("photo-file").files[0];
    if (!file) { msg.hidden = false; msg.textContent = "Choose a photo first."; return; }
    busy = true; btn.disabled = true; btn.textContent = "Analysing…"; msg.hidden = true;
    try {
      const small = await shrinkImage(file);
      await upload(`/api/incidents/${id}/photo?note=${encodeURIComponent(document.getElementById("photo-note").value)}`, small, "image/jpeg");
      busy = false; refresh();
    } catch (err) { busy = false; btn.disabled = false; btn.textContent = "Add photo"; msg.hidden = false; msg.textContent = err.message; }
  };
}
function ticketFacts(t) {
  const a = t.plan && t.plan.action;
  if (!a && !t.validation && !t.sandbox) return "";
  const PARAM = { adjust_tilt: ["Electrical tilt", "°", "tilt_deg"], adjust_tx_power: ["TX power", " dBm", "tx_power_dbm"] }[a && a.type];
  const before = PARAM && t.sandbox && t.sandbox.changes ? Number(t.sandbox.changes[PARAM[2]]) - Number(a.delta) : null;
  const rows = [];
  if (PARAM) rows.push(["Change", `${PARAM[0]} ${a.delta > 0 ? "+" : ""}${a.delta}${PARAM[1]}${before != null && !isNaN(before) ? ` <span class="muted">(${before} → ${before + Number(a.delta)})</span>` : ""}`]);
  else if (a) rows.push(["Change", "No configuration change"]);
  if (a && a.cell_id) rows.push(["Cell", `<span class="mono">${esc(a.cell_id)}</span>`]);
  if (t.validation) {
    const r = t.validation.rules || [], ok = r.filter((x) => x.status === "PASS").length, n = r.filter((x) => x.status !== "N/A").length;
    rows.push(["Safety rules", t.validation.passed ? `<span class="okc">${ok}/${n} passed</span>` : `<span class="badc">${esc((t.validation.failed || []).join(", ") || "not passed")}</span>`]);
  }
  if (t.sandbox) rows.push(["Twin", `coverage loss ${t.sandbox.coverage_loss_pct}% · PRB ${t.sandbox.before.prb_util}→${t.sandbox.after.prb_util}%`]);
  if (t.plan && t.plan.rollback && Object.keys(t.plan.rollback).length) rows.push(["Rollback", "automatic if KPIs worsen"]);
  return `<dl class="tfacts">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
}
function reviewBlock(r) {
  const n = r.concerns.length;
  return `<details class="review ${r.verdict}" ${n && n <= 1 ? "open" : ""}><summary><span class="label">Second opinion · ${esc(r.by)}</span>
    <span class="rv">${r.verdict === "agree" ? "Agrees with the plan" : `${n} concern${n === 1 ? "" : "s"} to weigh`}</span></summary>
    ${n ? `<ol>${r.concerns.map((c) => `<li>${esc(c)}</li>`).join("")}</ol>` : ""}
    ${r.questions_for_department.length ? `<p class="small muted">Questions: ${r.questions_for_department.map(esc).join(" ")}</p>` : ""}</details>`;
}
function fccPanel(f) {
  if (!f) return "";
  const kind = { reportable: "bad", below_threshold: "warn", not_an_outage: "ok" }[f.status];
  const label = { reportable: "Reportable", below_threshold: "Below threshold", not_an_outage: "Not an outage" }[f.status];
  return `<section class="panel"><header><h2>FCC Part 4 outage check</h2>${chip(label, kind)}</header><div class="body">
    <p>${esc(f.summary)}</p>
    ${f.status !== "not_an_outage" ? `<div class="meter big"><span style="width:${Math.max(1, f.progress_pct || 0)}%;background:var(--${kind})"></span></div>
      <dl class="kv"><dt>User-minutes</dt><dd class="mono">${f.user_minutes.toLocaleString("en-US")} / ${f.threshold_user_minutes.toLocaleString("en-US")}</dd>
      <dt>Duration</dt><dd class="mono">${f.duration_min} min</dd><dt>Users affected</dt><dd class="mono">${f.users_potentially_affected.toLocaleString("en-US")}</dd></dl>` : ""}
    <p class="small muted">${esc(f.rule)}: 30 min and 900,000 user-minutes, or a 911/988 special facility. Notify within 120 min, initial report 72 h, final report 30 days. ${esc(f.basis)}. ${esc(f.note)}</p></div></section>`;
}
function reportPanel(inc) {
  const r = inc.report;
  return `<section class="panel"><header><h2>Incident report</h2>${r ? `<span class="small muted">${esc(r.by)} · ${hhmm(r.generated_at)}</span>` : ""}</header><div class="body">
    ${r ? `<pre class="code report" id="report-text">${esc(r.text)}</pre>` : `<p class="small muted">The Incident Reporter agent writes a shift handover and management summary from the ledger.</p>`}
    <div class="row"><button class="btn" id="write-report">${r ? "Rewrite report" : "Write incident report"}</button>${r ? `<button class="btn" id="copy-report">Copy</button>` : ""}</div></div></section>`;
}
function prettyXml(x) { return x.replace(/></g, ">\n<"); }

const pct = (v) => (v == null ? "–" : (v * 100).toFixed(1) + "%");
const num = (v, d = 3) => (v == null ? "–" : Number(v).toFixed(d));
async function renderModelCard() {
  const [mc, st] = await Promise.all([api("/api/model-card"), getState()]);
  const sim = mc.benchmarks.simulator, tts = mc.benchmarks.telecomts;
  const agentsRows = [
    ["Investigator", "Writes a checklist (with one counter-evidence item), calls read-only tools (KPIs, alarms, M-Plane config, diagnostics), and pauses to ask a field engineer when the data cannot settle it", st.models.primary],
    ["Root-Cause Analyst", "Ranks 4 causes with cited evidence and states key facts; asks for more checks when unsure", st.models.primary],
    ["Diagnosis Verifier", "Code checks every diagnosis before planning: hidden playbook, each number looked up in its evidence, root-cause rules. Three refusals escalate", "code"],
    ["Claims Checker", "Reads the analyst's reasoning against the evidence and lists unbacked claims; part of the verifier", st.models.reviewer],
    ["Remediation Planner", "Drafts one plan from a fixed action catalogue, revises it when rules reject it", st.models.primary],
    ["Plan Reviewer", "Independent second opinion on a different model; advisory only", st.models.reviewer],
    ["Customer Comms", "Writes customer status updates; filtered for internal details", st.models.primary],
    ["Customer Assistant", "Answers customers from published updates only, ZIP-aware", st.models.primary],
    ["Incident Reporter", "Management report for one incident, from its ledger", st.models.primary],
    ["Escalation Briefer", "When the pipeline stops, briefs the Shift Lead: what is known, what is unclear, next checks", st.models.wonder],
    ["Shift Handover", "Reads every incident and the whole shift ledger (1M-token context) and writes the handover", st.models.wonder],
    ["Field Photo Analyst", "SAM 3.1 boxes antennas, cables and connectors in a site photo; Muse Spark reads them against the diagnosis", `${st.models.sam} + ${st.models.vision}`],
    ["Voice notes", "Engineers dictate decision notes; customers can ask by voice. Suggests a button, never clicks it", st.models.voice],
  ];
  const detRows = sim ? Object.entries(sim.detection).map(([k, v]) => `<tr><td>${{ thresholds_only: "Threshold rules only", iforest_only: "Isolation Forest only", cell_baseline_only: "Cell baseline (Mahalanobis) only", rules_plus_iforest: "Rules + Isolation Forest", combined: "All three (shipped)" }[k] || esc(k)}</td>
    <td class="mono">${pct(v.detection_rate)} <span class="muted">(${v.detected}/${v.total})</span></td><td class="mono">${v.mean_minutes_to_alert ?? "–"} min</td>
    <td class="mono">${sim.false_alarms_normal_traffic[k].alerts} in ${sim.false_alarms_normal_traffic.cell_days} cell-days</td></tr>`).join("") : "";
  paint("model", `<div class="pagehead"><div><div class="crumb">Assure / Model card</div><h1>Models, agents and measured accuracy</h1></div></div>
    <div class="grid cols-2" style="align-items:start">
      <section class="panel"><header><h2>Anomaly detector</h2><span class="small muted mono">${esc(mc.detector.version)}</span></header><div class="body">
        <p>${esc(mc.detector.design)}</p>
        <p class="small muted">Why these models: a new network has no labelled faults, so all three learn or encode normal behaviour only. They run on a laptop without a GPU, and each alert names the KPIs that drove it. On TelecomTS the cell-baseline method was the best unsupervised detector we tested (below). Once engineers have confirmed enough incidents in the ledger, a supervised model can be added: on TelecomTS, labels lift detection F1 from 0.61 to 0.97.</p></div></section>
      <section class="panel"><header><h2>Agents and Meta models</h2><span class="small muted">${st.offline ? "offline rules engine until a key is added" : "Meta Model API"}</span></header><div class="body tablewrap">
        <table><thead><tr><th>Agent</th><th>Job</th><th>Model</th></tr></thead><tbody>${agentsRows.map(([a, j, m]) => `<tr><td><b>${a}</b></td><td>${j}</td><td class="mono">${st.offline ? "rules" : esc(m)}</td></tr>`).join("")}</tbody></table>
        <p class="small muted">Every chat call retries once, then tries ${esc(st.models.fallback)}, then ${esc(st.models.last_resort)}${st.models.fireworks ? `, then ${esc(st.models.fireworks)} on Fireworks` : ""}; if all fail the incident escalates to the NOC Shift Lead. Voice and photo analysis fail soft: you can type, and photos are stored without analysis.</p>
        <p class="small muted"><b>Reasoning effort:</b> ${(() => { const e = { ...(st.models.effort || {}) }; const acc = e.accepted; delete e.accepted; const d = e.default; delete e.default; const per = Object.entries(e).map(([a, l]) => `${esc(nice(a))} ${esc(l)}`); return !d && !per.length ? "model default for every agent (set AGENT_EFFORT in .env to tune per agent)" : [d && `${esc(d)} by default`, ...per].filter(Boolean).join(", ") + (acc === false ? ". The Meta API rejected the setting, so it is not being sent." : ""); })()}</p>
        <p class="small muted"><b>On the key but not used:</b> muse-image-1.0, because a generated picture is not evidence and could be mistaken for a real site photo. The -contributor variants cost less, but Meta may train on what is sent, and incidents and customer questions can hold sensitive data; set ASSISTANT_MODEL to opt in for the customer assistant only.</p></div></section>
    </div>
    <section class="panel"><header><h2>Simulator benchmark</h2><span class="small muted">${sim ? "run " + esc(sim.generated_at.slice(0, 10)) : "not run yet"}</span></header><div class="body tablewrap">
      ${sim ? `<table><thead><tr><th>Detector</th><th>Faults detected</th><th>Mean time to alert</th><th>False alarms (normal traffic)</th></tr></thead><tbody>${detRows}</tbody></table>
      <p>Root cause ranked first after the full investigation: <b>${pct(sim.diagnosis_offline_rules.top1_accuracy)}</b> (${sim.diagnosis_offline_rules.correct}/${sim.diagnosis_offline_rules.total}) · ${Object.entries(sim.diagnosis_offline_rules.per_fault).map(([k, v]) => `${esc(FAULTS[k] || k)} ${pct(v)}`).join(" · ")}</p>
      <p class="small muted">${esc(sim.caveat)} 4 faults × 3 severities × 4 cells; diagnosis measured with the offline rules engine.</p>` : `<p class="empty">Run <code>py scripts/benchmark_simulator.py</code></p>`}</div></section>
    <section class="panel"><header><h2>TelecomTS benchmark (open 5G dataset)</h2><span class="small muted">MIT licence · Feng et al., ICML 2026</span></header><div class="body tablewrap">
      ${tts && !tts.error && tts.unsupervised ? `<p class="small muted">${tts.windows.toLocaleString("en-US")} windows (${pct(tts.anomaly_share)} anomalous), ${tts.features_per_window} features per window. 80/20 train/test split; the unsupervised detector is picked on a validation split, never on test. Threshold = 1% false-alarm target on normal data.</p>
        <table><thead><tr><th>Detector</th><th>Labels needed</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC-AUC</th><th>False alarms</th></tr></thead><tbody>
        ${Object.entries(tts.unsupervised.detectors).map(([k, v]) => `<tr${k === tts.unsupervised.selected ? ' style="font-weight:600"' : ""}><td>${esc({ isolation_forest_raw: "Isolation Forest", isolation_forest_context: "Isolation Forest on context baseline", pca_reconstruction_context: "PCA reconstruction on context baseline", mahalanobis_context: "Mahalanobis on context baseline" }[k] || k)}${k === tts.unsupervised.selected ? " ✓ selected" : ""}</td><td>No</td>
          <td class="mono">${num(v.test.precision)}</td><td class="mono">${num(v.test.recall)}</td><td class="mono">${num(v.test.f1)}</td><td class="mono">${num(v.test.roc_auc)}</td><td class="mono">${pct(v.test.false_alarm_rate)}</td></tr>`).join("")}
        <tr><td>Gradient-boosted trees (reference)</td><td>Yes</td><td class="mono">${num(tts.supervised_gbt.precision)}</td><td class="mono">${num(tts.supervised_gbt.recall)}</td><td class="mono">${num(tts.supervised_gbt.f1)}</td><td class="mono">${num(tts.supervised_gbt.roc_auc)}</td><td class="mono">${pct(tts.supervised_gbt.false_alarm_rate)}</td></tr></tbody></table>
        <p class="small">Selected detector's recall by fault type: ${Object.entries(tts.unsupervised.selected_recall_by_type).sort((a, b) => b[1] - a[1]).map(([t, r]) => `${esc(t)} ${pct(r)}`).join(" · ")}</p>
        ${tts.root_cause.accuracy != null ? `<p>Root cause with labels, 10 types: accuracy <b>${pct(tts.root_cause.accuracy)}</b>, macro-F1 ${num(tts.root_cause.macro_f1)}${tts.root_cause.sentinel_causes ? ` · mapped to RAN Sentinel's causes: accuracy <b>${pct(tts.root_cause.sentinel_causes.accuracy)}</b>` : ""}.</p>` : ""}
        <p class="small muted">Caveat: TelecomTS anomalies were recorded in separate sessions from normal traffic, and windows from one session can fall in both train and test, so the supervised scores are likely optimistic.</p>` : tts && !tts.error ? `<p>These results came from an older version of the benchmark. Run it again to see the current detectors.</p>` :
        `<p>Not run on this computer yet. The dataset is about 32,000 labelled 5G windows from a testbed, with 11 anomaly types including real over-the-air jamming.</p><pre class="code">py -m pip install huggingface_hub
py scripts/benchmark_telecomts.py</pre><p class="small muted">The script downloads the data from Hugging Face (AliMaatouk/TelecomTS), trains the models and writes data/benchmarks/telecomts.json. This page then shows the results.</p>`}
    </div></section>`);
}

route();

const SUP_TONE = { open: "info", in_progress: "brand", waiting_customer: "warn", resolved: "ok", closed: "" };
const PRI_TONE = { low: "", normal: "info", high: "warn", urgent: "bad" };
const supWhen = (iso) => (iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC` : "–");
async function renderSupport() {
  const qs = new URLSearchParams({ status: ui.supStatus || "active", category: ui.supCat || "all", q: ui.supText || "" });
  const [d] = await Promise.all([api("/api/support/tickets?" + qs), getState()]);
  const c = d.counts, active = c.open + c.in_progress + c.waiting_customer;
  const seg = [["active", "Active", active], ["open", "Open", c.open], ["in_progress", "In progress", c.in_progress], ["waiting_customer", "Waiting for customer", c.waiting_customer], ["resolved", "Resolved", c.resolved], ["closed", "Closed", c.closed], ["all", "All", Object.values(c).reduce((a, b) => a + b, 0)]];
  paint("support", `<div class="pagehead"><div><div class="crumb">Operate / Customer support</div><h1>Customer support desk</h1>
      <p class="sub">Requests sent from the Help center in Northstar Connect. Reply, set the status and priority; the customer sees your reply in the app.</p></div></div>
    <div class="stats"><div class="stat"><span class="label">Active</span><span class="v">${active}</span></div><div class="stat"><span class="label">Unread</span><span class="v">${d.unread}</span></div>
      <div class="stat"><span class="label">Waiting for customer</span><span class="v">${c.waiting_customer}</span></div><div class="stat"><span class="label">Resolved</span><span class="v">${c.resolved}</span></div></div>
    <section class="panel flat"><header class="toolbar"><div class="seg" role="group" aria-label="Filter by status">${seg.map(([k, l, n]) => `<button class="${(ui.supStatus || "active") === k ? "on" : ""}" data-ss="${k}" aria-pressed="${(ui.supStatus || "active") === k}">${l}<span class="n">${n}</span></button>`).join("")}</div>
      <select id="sup-cat" class="filter" aria-label="Filter by category" style="min-width:0;flex:none;width:auto"><option value="all">All categories</option>${Object.entries(d.categories).map(([k, l]) => `<option value="${k}" ${ui.supCat === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
      <input id="sup-q" type="search" class="filter" placeholder="Search ID, subject, customer or message" value="${esc(ui.supText || "")}" aria-label="Search support tickets">
      <span class="small muted">${d.tickets.length} shown</span></header>
      <div class="body tablewrap">${d.tickets.length ? `<table class="dense"><thead><tr><th>Ticket</th><th>Opened</th><th>Subject</th><th>Customer</th><th>Category</th><th>Priority</th><th>Status</th><th>Updated</th></tr></thead><tbody>
        ${d.tickets.map((t) => `<tr class="click ${t.unread_staff ? "unread" : ""}" data-sup="${esc(t.id)}" tabindex="0"><td class="mono">${t.unread_staff ? `<i class="newdot" title="New customer message"></i>` : ""}${esc(t.id)}</td><td class="mono small">${esc(supWhen(t.created))}</td>
          <td>${esc(t.subject)}</td><td>${esc(t.name)}<div class="small muted">${esc(t.email)}</div></td><td class="small">${esc(t.category_label)}</td><td>${chip(t.priority_label, PRI_TONE[t.priority])}</td><td>${chip(t.status_label, SUP_TONE[t.status])}</td><td class="mono small">${esc(supWhen(t.updated))}</td></tr>`).join("")}</tbody></table>`
        : `<p class="empty pad">${ui.supText ? `No tickets match “${esc(ui.supText)}”.` : "No tickets with this status. Customers create tickets from Help, Contact support in Northstar Connect."}</p>`}</div></section>`);
  document.querySelectorAll("[data-ss]").forEach((b) => (b.onclick = () => { ui.supStatus = b.dataset.ss; refresh(); }));
  document.getElementById("sup-cat").onchange = (e) => { ui.supCat = e.target.value; refresh(); };
  const q = document.getElementById("sup-q");
  q.onkeydown = (e) => { if (e.key === "Enter") { ui.supText = q.value; q.blur(); refresh(); } };
  q.onsearch = q.onchange = () => { ui.supText = q.value; refresh(); };
  document.querySelectorAll("tr[data-sup]").forEach((tr) => {
    tr.onclick = () => (location.hash = "#/support/" + tr.dataset.sup);
    tr.onkeydown = (e) => { if (e.key === "Enter") tr.onclick(); };
  });
}

async function renderSupportTicket(id) {
  let t;
  try { [t] = await Promise.all([api("/api/support/tickets/" + encodeURIComponent(id)), getState()]); }
  catch (e) {
    if (e.status === 401) throw e;
    paint("support", `<div class="pagehead"><div><div class="crumb">Operate / Customer support</div><h1>Ticket not found</h1></div></div>
      <section class="panel"><div class="body"><p>${esc(e.message)}</p><div class="row"><a class="btn" href="#/support">Back to the support desk</a></div></div></section>`);
    return;
  }
  const closed = t.status === "closed";
  const msg = (m) => m.role === "system" ? `<li class="sys"><span>${esc(m.body)}</span> <span class="mono small muted">${esc(supWhen(m.created))}</span></li>`
    : `<li class="m ${m.role}"><div class="mh"><b>${esc(m.author)}</b><span class="small muted">${m.role === "customer" ? "Customer" : "Care team"}</span><span class="mono small muted">${esc(supWhen(m.created))}</span></div><p>${esc(m.body)}</p></li>`;
  paint("support", `<div class="pagehead"><div><div class="crumb"><a href="#/support">Operate / Customer support</a> / ${esc(t.id)}</div><h1>${esc(t.subject)}</h1>
      <p class="sub">${chip(t.status_label, SUP_TONE[t.status])} ${chip(t.priority_label + " priority", PRI_TONE[t.priority])} <span class="small muted">${esc(t.category_label)} · opened ${esc(supWhen(t.created))}</span></p></div>
      <a class="btn" href="#/support">All tickets</a></div>
    <div class="grid cols-2">
      <div class="grid" style="gap:14px;align-content:start">
        <section class="panel"><header><h2>Conversation</h2><span class="small muted">${t.messages.filter((m) => m.role !== "system").length} messages</span></header>
          <div class="body"><ol class="supthread">${t.messages.map(msg).join("")}</ol></div></section>
        ${closed ? `<section class="panel"><div class="body"><p class="small muted">This ticket is closed. Reopen it with the status control to reply.</p></div></section>`
          : `<section class="panel" id="sreply-${esc(t.id)}" data-keep><header><h2>Reply to ${esc(t.name)}</h2></header><div class="body"><form id="srf" class="grid" style="gap:10px" novalidate>
            <div class="field"><label for="sbody">Message to the customer</label><textarea id="sbody" rows="5" maxlength="4000" placeholder="Write a clear answer. The customer reads it in the app." aria-describedby="serr"></textarea></div>
            <div class="row"><label class="small" for="safter">After sending, set status to</label><select id="safter" style="width:auto">${["waiting_customer", "in_progress", "resolved"].map((k) => `<option value="${k}">${esc(t.statuses[k])}</option>`).join("")}</select>
              <button class="btn primary" type="submit">Send reply</button></div><p class="err" id="serr" role="alert" hidden></p></form></div></section>`}
      </div>
      <div class="grid" style="gap:14px;align-content:start">
        <section class="panel"><header><h2>Ticket</h2></header><div class="body">
          <dl class="kv"><dt>Reference</dt><dd class="mono">${esc(t.id)}</dd><dt>Customer</dt><dd>${esc(t.name)}</dd><dt>Reply email</dt><dd>${esc(t.email)}</dd><dt>Account login</dt><dd>${esc(t.owner)}</dd>
            <dt>Assignee</dt><dd>${esc(t.assignee || "Unassigned")}</dd><dt>First response</dt><dd>${esc(t.first_response ? supWhen(t.first_response) : "Not yet")}</dd><dt>Updated</dt><dd>${esc(supWhen(t.updated))}</dd></dl>
          <form id="suf-${esc(t.id)}-${t.status}-${t.priority}" class="grid" style="gap:10px" data-keep>
            <div class="field"><label for="sstatus">Status</label><select id="sstatus">${Object.entries(t.statuses).map(([k, l]) => `<option value="${k}" ${t.status === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
            <div class="field"><label for="sprio">Priority</label><select id="sprio">${Object.entries(t.priorities).map(([k, l]) => `<option value="${k}" ${t.priority === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
            <div class="row"><button class="btn" type="submit">Save changes</button></div><p class="err" id="suerr" role="alert" hidden></p></form></div></section>
        <section class="panel"><header><h2>Other requests from this customer</h2></header><div class="body">${t.history.length ? `<div class="list">${t.history.map((h) => `<a class="supother" href="#/support/${esc(h.id)}"><span class="mono">${esc(h.id)}</span> ${esc(h.subject)} ${chip(h.status_label, SUP_TONE[h.status])}</a>`).join("")}</div>` : `<p class="empty">No other requests.</p>`}</div></section>
      </div></div>`);
  const uf = document.getElementById(`suf-${t.id}-${t.status}-${t.priority}`);
  uf.onsubmit = async (e) => {
    e.preventDefault();
    const err = uf.querySelector("#suerr"); err.hidden = true;
    busy = true;
    try { await api(`/api/support/tickets/${encodeURIComponent(t.id)}/update`, { body: { status: uf.querySelector("#sstatus").value, priority: uf.querySelector("#sprio").value } }); }
    catch (x) { if (x.status === 401) throw x; err.textContent = x.message; err.hidden = false; }
    busy = false; refresh();
  };
  if (closed) return;
  const box = document.getElementById("sreply-" + t.id);
  box.querySelector("#srf").onsubmit = async (e) => {
    e.preventDefault();
    const body = box.querySelector("#sbody"), err = box.querySelector("#serr"); err.hidden = true;
    if (!body.value.trim()) { err.textContent = "Write a message first."; err.hidden = false; body.focus(); return; }
    busy = true;
    try { await api(`/api/support/tickets/${encodeURIComponent(t.id)}/reply`, { body: { body: body.value, status: box.querySelector("#safter").value } }); body.value = ""; }
    catch (x) { if (x.status === 401) throw x; err.textContent = x.message; err.hidden = false; }
    busy = false; refresh();
  };
}
