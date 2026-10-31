const UI = (() => {
  let liveSignal = null;
  let pressed = null;
  addEventListener("click", (e) => { const b = e.target.closest && e.target.closest("button"); if (b) pressed = { el: b, at: Date.now() }; }, true);
  const ING = { Create: "Creating", Send: "Sending", Approve: "Approving", Reject: "Rejecting", Request: "Requesting", Accept: "Accepting",
    Advance: "Advancing", Clear: "Clearing", Reset: "Resetting", Sign: "Signing", Add: "Adding", Mark: "Marking", Run: "Running",
    Close: "Closing", Apply: "Applying", Confirm: "Confirming", Pay: "Paying", Turn: "Turning", Dispute: "Disputing", Resume: "Resuming",
    Pause: "Pausing", Start: "Starting", Submit: "Submitting", Save: "Saving", Upload: "Uploading", Attach: "Attaching", Ask: "Asking", Check: "Checking" };
  function busyText(b) {
    if (b.dataset.busy) return b.dataset.busy;
    const [w, ...rest] = b.textContent.trim().split(/\s+/);
    return ING[w] ? [ING[w], ...rest].join(" ") + "…" : "Working…";
  }
  function claim() {
    const p = pressed; pressed = null;
    if (!p || Date.now() - p.at > 1500 || !p.el.isConnected || p.el.classList.contains("is-busy") || p.el.hasAttribute("data-mic") || p.el.hasAttribute("data-nobusy")) return null;
    const b = p.el, label = busyText(b);
    b.dataset.label = b.innerHTML; b.style.minWidth = b.offsetWidth + "px";
    b.classList.add("is-busy"); b.disabled = true; b.setAttribute("aria-busy", "true");
    b.innerHTML = `<span class="spin" aria-hidden="true"></span>${esc(label)}`;
    return { b, t0: Date.now() };
  }
  async function release(h) {
    if (!h) return;
    const wait = 450 - (Date.now() - h.t0);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    const b = h.b;
    if (!b.classList.contains("is-busy")) return;
    b.innerHTML = b.dataset.label; delete b.dataset.label;
    b.classList.remove("is-busy"); b.disabled = false; b.removeAttribute("aria-busy"); b.style.minWidth = "";
  }
  async function api(path, opts = {}) {
    const method = opts.method || (opts.body ? "POST" : "GET");
    const h = method === "GET" ? null : claim();
    try { return await send(path, opts, method); } finally { release(h); }
  }
  async function send(path, opts, method) {
    const res = await fetch(path, {
      method,
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
      signal: opts.signal || (method === "GET" ? liveSignal : undefined) || undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail, msg = (d && d.message) || (typeof d === "string" && d) || (res.status === 401 ? "Please sign in." : `Request failed (${res.status})`);
      const e = new Error(msg); e.status = res.status; e.portal = d && d.portal; throw e;
    }
    return data;
  }

  function morph(target, html) {
    const next = document.createElement(target.tagName === "TBODY" ? "tbody" : "div");
    next.innerHTML = html;
    patchChildren(target, next);
  }
  function patchChildren(cur, next) {
    const byId = new Map();
    for (const c of cur.children) if (c.id) byId.set(c.id, c);
    let i = 0;
    for (const n of [...next.childNodes]) {
      let c = cur.childNodes[i];
      const want = n.nodeType === 1 && n.id ? byId.get(n.id) : null;
      if (want && want !== c) { cur.insertBefore(want, c || null); c = want; }
      else if (c && !same(c, n)) {
        c = null;
      }
      if (c) patch(c, n);
      else cur.insertBefore(document.importNode(n, true), cur.childNodes[i] || null);
      i++;
    }
    while (cur.childNodes.length > i) cur.removeChild(cur.lastChild);
  }
  function same(c, n) {
    if (c.nodeType !== n.nodeType) return false;
    if (c.nodeType !== 1) return true;
    return c.tagName === n.tagName && (c.id || "") === (n.id || "");
  }
  const LIVE_ATTR = { DETAILS: ["open"], DIALOG: ["open"] };
  function patch(c, n) {
    if (c.nodeType !== 1) { if (c.nodeValue !== n.nodeValue) c.nodeValue = n.nodeValue; return; }
    if (c.classList.contains("is-busy")) return;
    const skip = LIVE_ATTR[c.tagName] || [];
    const focused = c === document.activeElement;
    for (const a of [...c.attributes]) if (!n.hasAttribute(a.name) && !skip.includes(a.name)) c.removeAttribute(a.name);
    for (const a of n.attributes) if (c.getAttribute(a.name) !== a.value && !skip.includes(a.name)) c.setAttribute(a.name, a.value);
    if (c.tagName === "INPUT") {
      if (!focused && c.type !== "file") {
        if (c.type === "checkbox" || c.type === "radio") c.checked = n.hasAttribute("checked");
        else if (c.value !== (n.getAttribute("value") ?? "")) c.value = n.getAttribute("value") ?? "";
      }
      return;
    }
    if (c.tagName === "TEXTAREA") { if (!focused && c.value !== n.value) c.value = n.value; return; }
    if (c.hasAttribute("data-keep")) return;
    patchChildren(c, n);
    if (c.tagName === "SELECT" && !focused) {
      const sel = n.querySelector("option[selected]");
      if (sel) c.value = sel.value;
    }
  }

  let pointerDown = false;
  addEventListener("pointerdown", () => { pointerDown = true; }, true);
  addEventListener("pointerup", () => { pointerDown = false; }, true);
  addEventListener("pointercancel", () => { pointerDown = false; }, true);
  function poller({ onState, paused } = {}) {
    let gen = 0, timer = null, running = false, again = false, ctrl = null, fails = 0, lastOk = null, fn = null, every = 2000;
    async function tick(g) {
      if (g !== gen || !fn) return;
      if (running) { again = true; return; }
      if (document.hidden) return;
      if (pointerDown || (paused && paused())) return schedule(g, 250);
      running = true;
      ctrl = new AbortController();
      liveSignal = ctrl.signal;
      try {
        await fn();
        if (g !== gen) return;
        fails = 0; lastOk = new Date();
        onState && onState({ ok: true, lastOk });
      } catch (e) {
        if (g !== gen || e.name === "AbortError") return;
        if (e.status === 401) throw e;
        fails++;
        onState && onState({ ok: false, lastOk, fails, error: e, retryIn: delay() });
      } finally {
        if (g === gen) { running = false; liveSignal = null; }
      }
      if (g !== gen) return;
      if (again) { again = false; return tick(g); }
      schedule(g);
    }
    const delay = () => (fails ? Math.min(15000, every * 2 ** Math.min(fails, 3)) : every);
    function schedule(g, ms) { clearTimeout(timer); timer = setTimeout(() => tick(g).catch(onFatal), ms ?? delay()); }
    let onFatal = () => {};
    const resume = () => { if (!document.hidden) { clearTimeout(timer); tick(gen).catch(onFatal); } };
    document.addEventListener("visibilitychange", resume);
    addEventListener("online", resume);
    return {
      start(newFn, ms, fatal) {
        gen++; if (ctrl) ctrl.abort(); clearTimeout(timer);
        fn = newFn; every = ms; running = false; again = false; fails = 0; onFatal = fatal || onFatal;
        return tick(gen).catch(onFatal);
      },
      now() { return tick(gen).catch(onFatal); },
      stop() { gen++; if (ctrl) ctrl.abort(); clearTimeout(timer); fn = null; },
      get lastOk() { return lastOk; },
    };
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const hhmm = (iso) => (iso ? String(iso).slice(11, 16) : "–");
  const day = (iso) => {
    if (!iso) return "–";
    const d = new Date(iso);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };
  const nice = (s) => String(s ?? "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

  const STATUS_CHIP = {
    DETECTED: "info", AUTO_REMEDIATION: "info", INVESTIGATING: "info", AWAITING_EVIDENCE: "warn", DIAGNOSIS_READY: "info", PLANNING: "info",
    AWAITING_DEPARTMENT: "warn", FIELD_WORK: "warn", CHANGE_APPLIED: "brand", MONITORING: "brand",
    RESOLVED: "ok", ESCALATED: "bad", REJECTED: "plain", CLOSED: "plain",
  };
  const SEV_CHIP = { critical: "bad", major: "warn", minor: "info" };
  const chip = (text, kind) => `<span class="chip ${kind || ""}">${esc(nice(text))}</span>`;
  const statusChip = (s) => chip({ AWAITING_DEPARTMENT: "Awaiting department", AWAITING_EVIDENCE: "Awaiting field evidence" }[s] || s, STATUS_CHIP[s]);
  const sevChip = (s) => chip(s, SEV_CHIP[s]);

  function lineChart(series, labels, o = {}) {
    const W = o.width || 560, H = o.height || 170, L = 40, R = o.right || 12, T = 10, B = 22;
    const all = series.flatMap((s) => s.values).filter((v) => v != null);
    if (!all.length) return `<div class="empty">No data in this window.</div>`;
    let lo = o.min ?? Math.min(...all), hi = o.max ?? Math.max(...all);
    if (o.threshold != null) { lo = Math.min(lo, o.threshold); hi = Math.max(hi, o.threshold); }
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.08; if (o.min == null) lo -= pad; if (o.max == null) hi += pad;
    const n = labels.length;
    const x = (i) => L + (n <= 1 ? 0 : (i * (W - L - R)) / (n - 1));
    const y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo);
    let g = "";
    const ticks = 4;
    for (let k = 0; k <= ticks; k++) {
      const v = lo + ((hi - lo) * k) / ticks;
      g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="1"/>`;
      g += `<text x="${L - 6}" y="${y(v) + 3}" text-anchor="end" font-size="10" fill="var(--muted)">${fmtTick(v, hi - lo)}</text>`;
    }
    const step = Math.max(1, Math.ceil(n / 6));
    labels.forEach((l, i) => { if ((i % step === 0 && n - 1 - i >= step / 2) || i === n - 1) g += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="10" fill="var(--muted)">${esc(l)}</text>`; });
    if (o.threshold != null) {
      g += `<line x1="${L}" x2="${W - R}" y1="${y(o.threshold)}" y2="${y(o.threshold)}" stroke="var(--bad)" stroke-dasharray="3 4" stroke-width="1"/>`;
      g += `<text x="${W - R}" y="${y(o.threshold) - 4}" text-anchor="end" font-size="10" fill="var(--bad)">${esc(o.thresholdLabel || "limit " + o.threshold)}</text>`;
    }
    series.forEach((s, si) => {
      const pts = s.values.map((v, i) => (v == null ? null : [x(i), y(v)]));
      let d = "", open = false;
      pts.forEach((p) => { if (!p) { open = false; return; } d += (open ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); open = true; });
      if (si === 0 && o.area !== false) {
        const valid = pts.filter(Boolean);
        if (valid.length > 1) g += `<path d="M${valid[0][0]} ${y(lo)} ${valid.map((p) => "L" + p[0] + " " + p[1]).join(" ")} L${valid[valid.length - 1][0]} ${y(lo)} Z" fill="${s.color}" opacity=".08"/>`;
      }
      g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${si === 0 ? 2 : 1.5}" ${s.dash ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round"/>`;
      const last = [...pts].reverse().find(Boolean);
      if (last) g += `<circle cx="${last[0]}" cy="${last[1]}" r="3" fill="${s.color}"/>`;
    });
    const legend = series.length > 1 ? `<div class="row small" style="gap:14px">${series.map((s) => `<span><span style="display:inline-block;width:10px;height:2px;background:${s.color};vertical-align:middle;margin-right:5px"></span>${esc(s.name)}</span>`).join("")}</div>` : "";
    return `${legend}<div style="overflow-x:auto"><svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:320px;height:auto;display:block" role="img" aria-label="${esc(o.aria || series.map((s) => s.name).join(", "))}">${g}</svg></div>`;
  }
  function fmtTick(v, span) { return span < 2 ? v.toFixed(2) : span < 20 ? v.toFixed(1) : Math.round(v); }

  const CELL_COLOR = { ok: "var(--ok)", watch: "var(--warn)", symptom: "var(--warn)", incident: "var(--bad)", critical: "var(--bad)", "no-data": "var(--muted)" };
  function clusterMap(cells, o = {}) {
    const xs = cells.map((c) => c.x), ys = cells.map((c) => c.y);
    const minX = Math.min(...xs) - 0.9, maxX = Math.max(...xs) + 0.9, minY = Math.min(...ys) - 0.7, maxY = Math.max(...ys) + 0.7;
    const W = 420, H = Math.round((W * (maxY - minY)) / (maxX - minX));
    const px = (x) => ((x - minX) / (maxX - minX)) * W, py = (y) => H - ((y - minY) / (maxY - minY)) * H;
    let g = `<rect x="0" y="0" width="${W}" height="${H}" fill="var(--sunk)"/>`;
    g += `<path d="M0 ${py(-1.2)} Q ${px(-2.0)} ${py(0.0)} ${px(-2.3)} ${py(1.6)} L0 ${py(2.0)} Z" fill="var(--info-soft)"/>`;
    g += `<ellipse cx="${px(0.7)}" cy="${py(3.6)}" rx="${(0.45 / (maxX - minX)) * W}" ry="${(0.8 / (maxY - minY)) * H}" fill="var(--info-soft)"/>`;
    const sites = {};
    cells.forEach((c) => { (sites[c.site] ||= []).push(c); });
    Object.entries(sites).forEach(([site, cs]) => {
      const cx = cs.reduce((a, c) => a + c.x, 0) / cs.length, cy = cs.reduce((a, c) => a + c.y, 0) / cs.length;
      g += `<text x="${px(cx)}" y="${py(cy) + 26}" text-anchor="middle" font-size="9" fill="var(--muted)" font-family="var(--sans)">${esc(site)}</text>`;
      cs.forEach((c) => {
        const a = ((c.azimuth - 90 - 45) * Math.PI) / 180, b = ((c.azimuth - 90 + 45) * Math.PI) / 180, r = 17;
        const X = px(cx), Y = py(cy);
        const sel = o.selected === c.cell_id;
        g += `<path class="sector" data-cell="${c.cell_id}" d="M${X} ${Y} L${X + r * Math.cos(a)} ${Y + r * Math.sin(a)} A${r} ${r} 0 0 1 ${X + r * Math.cos(b)} ${Y + r * Math.sin(b)} Z"
          fill="${CELL_COLOR[c.status] || "var(--ok)"}" fill-opacity="${c.status === "ok" ? 0.55 : 0.95}" stroke="${sel ? "var(--fg)" : "var(--surface)"}" stroke-width="${sel ? 2 : 1}" style="cursor:pointer"><title>${c.cell_id} · ${esc(c.site)} · ${esc(c.status)}${c.prb_util != null ? " · PRB " + c.prb_util + "%" : ""}</title></path>`;
      });
    });
    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;max-height:430px;display:block;border-radius:4px" role="img" aria-label="Map of ${cells.length} cells">${g}</svg>`;
  }

  async function upload(path, blob, type) {
    const h = claim();
    try { return await sendRaw(path, blob, type); } finally { release(h); }
  }
  async function sendRaw(path, blob, type) {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": type }, body: blob, credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail, msg = (d && d.message) || (typeof d === "string" && d) || (res.status === 401 ? "Please sign in." : `Request failed (${res.status})`);
      const e = new Error(msg); e.status = res.status; e.portal = d && d.portal; throw e;
    }
    return data;
  }

  const MAX_SECONDS = 60;
  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("This browser cannot record audio. Please type instead.");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const rec = new MediaRecorder(stream), parts = [];
    rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
    rec.start();
    const auto = setTimeout(() => rec.state === "recording" && rec.stop(), MAX_SECONDS * 1000);
    const done = new Promise((resolve) => (rec.onstop = () => { clearTimeout(auto); stream.getTracks().forEach((t) => t.stop()); resolve(new Blob(parts, { type: rec.mimeType })); }));
    return { stop: async () => { if (rec.state === "recording") rec.stop(); return toWav(await done); }, done };
  }
  async function toWav(blob, rate = 16000) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    ctx.close();
    const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
    const src = off.createBufferSource();
    src.buffer = decoded; src.connect(off.destination); src.start();
    const pcm = (await off.startRendering()).getChannelData(0);
    const buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf);
    const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    str(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
    return new Blob([buf], { type: "audio/wav" });
  }
  async function listen({ maxSeconds = 15, silenceMs = 1300, waitSeconds = 7, onLevel } = {}) {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("This browser cannot record audio. Please type instead.");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const an = ctx.createAnalyser(); an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const rec = new MediaRecorder(stream), parts = [], buf = new Float32Array(an.fftSize);
    rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
    let spoke = false, quietSince = 0, floor = 0.01, frames = 0, cancelled = false;
    const t0 = performance.now();
    const done = new Promise((resolve) => (rec.onstop = () => {
      clearInterval(meter); stream.getTracks().forEach((t) => t.stop()); ctx.close();
      resolve(cancelled || !spoke ? null : new Blob(parts, { type: rec.mimeType }));
    }));
    const stop = () => rec.state === "recording" && rec.stop();
    const meter = setInterval(() => {
      an.getFloatTimeDomainData(buf);
      const rms = Math.sqrt(buf.reduce((s, x) => s + x * x, 0) / buf.length), now = performance.now();
      if (++frames <= 6) floor = Math.max(floor, rms);
      const loud = rms > Math.max(0.02, floor * 2.5);
      onLevel && onLevel(Math.min(1, rms * 8));
      if (loud) { spoke = true; quietSince = 0; } else if (spoke && !quietSince) quietSince = now;
      if ((spoke && quietSince && now - quietSince > silenceMs) || now - t0 > maxSeconds * 1000 || (!spoke && now - t0 > waitSeconds * 1000)) stop();
    }, 50);
    rec.start();
    return { result: done.then((b) => (b ? toWav(b) : null)), stop, cancel: () => { cancelled = true; stop(); } };
  }

  function micButton(btn, path, onText, onError) {
    let session = null;
    const idle = btn.innerHTML;
    btn.onclick = async () => {
      if (!session) {
        try { session = await startRecording(); } catch (e) { onError(e.message || "Microphone not available."); return; }
        btn.classList.add("rec"); btn.innerHTML = "■ Stop"; btn.setAttribute("aria-pressed", "true");
        session.done.then(() => session && btn.classList.contains("rec") && btn.click());
        return;
      }
      const s = session; session = null;
      btn.classList.remove("rec"); btn.innerHTML = "Transcribing…"; btn.disabled = true; btn.setAttribute("aria-pressed", "false");
      try { onText(await upload(path, await s.stop(), "audio/wav")); } catch (e) { onError(e.message); }
      btn.innerHTML = idle; btn.disabled = false;
    };
  }
  const MIC = `<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>`;

  async function shrinkImage(file, max = 1600) {
    const img = await createImageBitmap(file);
    const k = Math.min(1, max / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
  }

  return { api, morph, poller, esc, hhmm, day, nice, chip, statusChip, sevChip, lineChart, clusterMap, upload, micButton, listen, MIC, shrinkImage };
})();
