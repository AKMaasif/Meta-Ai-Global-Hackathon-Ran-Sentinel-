let chromium;
try { ({ chromium } = require("playwright")); } catch {
  console.error("Playwright is not installed. In the project folder run:\n  npm i --no-save playwright\n  npx playwright install chromium\nthen run this script again.");
  process.exit(2);
}
const fail = (msg) => { console.error(msg); process.exit(2); };
const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const results = [];
const check = (name, ok, detail) => { results.push({ name, ok, detail }); };

async function churn(page, ms) {
  return page.evaluate((ms) => new Promise((res) => {
    let removed = 0, anim = 0;
    const w0 = document.getElementById("work"), m0 = document.querySelector(".geomap");
    const mo = new MutationObserver((ms) => ms.forEach((m) => m.removedNodes.forEach((n) => { if (n.nodeType === 1) removed += 1 + n.querySelectorAll("*").length; })));
    mo.observe(document.getElementById("app"), { childList: true, subtree: true });
    document.addEventListener("animationstart", () => anim++, true);
    setTimeout(() => { mo.disconnect(); res({ removed, anim, sameWork: w0 === document.getElementById("work"), sameMap: m0 === document.querySelector(".geomap"), y: scrollY }); }, ms);
  }), ms);
}

(async () => {
  try { await fetch(`${BASE}/ops/`); } catch { fail(`The app is not reachable at ${BASE}. Start it first with: py run.py`); }
  const b = await chromium.launch();
  const errors = [];
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  p.on("pageerror", (e) => errors.push("ops: " + e.message));
  await p.goto(`${BASE}/ops/#/login`);
  await p.click("#demo-start"); await p.waitForTimeout(1500);
  if (!(await p.locator(".shell").count())) { await b.close(); fail("Demo entry to the operations console failed. Check the server log."); }
  if (!(await p.locator("tr.click[data-inc]").count())) {
    console.log("No open incident yet: creating a hardware fault on SEA-RAN-001 through Demo controls...");
    const r = await p.request.post(`${BASE}/api/demo/inject`, { data: { cell_id: "SEA-RAN-001", fault_type: "hardware", severity: 3 } });
    if (!r.ok()) console.log(`  could not create the fault (HTTP ${r.status()}); the click check will fail`);
    for (let i = 0; i < 30 && !(await p.locator("tr.click[data-inc]").count()); i++) await p.waitForTimeout(2000);
  }
  const c = await churn(p, 6000);
  check("ops: no screen rebuild over 3 refreshes", c.sameWork && c.removed < 50 && c.anim === 0, `${c.removed} elements replaced, ${c.anim} fade animations`);
  check("ops: map survives refreshes", c.sameMap, "");
  let ok = 0;
  for (let i = 0; i < 4; i++) {
    await p.goto(`${BASE}/ops/#/dashboard`); await p.waitForTimeout(1200);
    const row = p.locator("tr.click[data-inc]").first();
    const r = (await row.count()) ? await row.boundingBox() : null;
    if (!r) break;
    await p.mouse.move(r.x + 30, r.y + r.height / 2); await p.mouse.down(); await p.waitForTimeout(700 + i * 500); await p.mouse.up();
    await p.waitForTimeout(400);
    if ((await p.evaluate(() => location.hash)).startsWith("#/incidents/")) ok++;
  }
  check("ops: a click held across a refresh opens the incident", ok === 4, `${ok}/4`);
  await p.goto(`${BASE}/ops/#/dashboard`); await p.waitForTimeout(1200);
  await p.click("#gq"); await p.keyboard.type("SEA-RAN-0", { delay: 450 });
  check("ops: text typed across refreshes is kept", (await p.inputValue("#gq")) === "SEA-RAN-0", "");
  const t1 = await p.textContent(".clock"); await p.waitForTimeout(6000);
  check("ops: live data keeps flowing", t1 !== (await p.textContent(".clock")), "simulated clock advanced");
  let inflight = 0, most = 0, n = 0;
  await p.route("**/api/state", async (r) => { inflight++; n++; most = Math.max(most, inflight); await new Promise((x) => setTimeout(x, 2500)); inflight--; r.continue().catch(() => {}); });
  await p.waitForTimeout(10000); await p.unroute("**/api/state");
  check("ops: slow backend gets one request at a time", most === 1, `${n} requests in 10 s, at most ${most} at once`);
  await p.route("**/api/**", (r) => r.abort()); await p.waitForTimeout(5000);
  const feed = await p.textContent("#feed").catch(() => "");
  check("ops: lost connection is shown, last data kept", /Connection lost/.test(feed) && (await p.locator("h1").count()) > 0, feed.trim());
  await p.unroute("**/api/**"); await p.waitForTimeout(17000);
  check("ops: recovers within 15 s after the connection returns", /Updated/.test(await p.textContent("#feed")), "");

  const q = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  q.on("pageerror", (e) => errors.push("connect: " + e.message));
  await q.goto(`${BASE}/connect/#/login`);
  await q.click("#demo-start"); await q.waitForTimeout(1500);
  if (!(await q.locator(".app").count())) { await b.close(); fail("Demo entry to the customer app failed. Check that this server includes the no-login demo endpoint."); }
  await q.goto(`${BASE}/connect/#/network/home`); await q.waitForTimeout(3000);
  await q.evaluate(() => scrollTo(0, 900)); await q.waitForTimeout(200);
  const d = await churn(q, 11000);
  check("connect: no page rebuild over 2 refreshes", d.removed < 50, `${d.removed} elements replaced`);
  check("connect: scroll position and map survive", d.sameMap && d.y === 900, `scrollY ${d.y}`);
  ok = 0;
  for (let i = 0; i < 4; i++) {
    await q.goto(`${BASE}/connect/#/home`); await q.waitForTimeout(1000 + i * 1300);
    const t = await q.locator('.tabbar a[href="#/account"]').boundingBox({ timeout: 5000 }).catch(() => null);
    if (!t) break;
    await q.mouse.move(t.x + 10, t.y + 10); await q.mouse.down(); await q.waitForTimeout(600); await q.mouse.up(); await q.waitForTimeout(500);
    if ((await q.evaluate(() => location.hash)) === "#/account") ok++;
  }
  check("connect: a tap across a refresh switches tab", ok === 4, `${ok}/4`);
  check("no JavaScript errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.detail ? "  (" + r.detail + ")" : ""}`);
  const bad = results.filter((r) => !r.ok).length;
  console.log(bad ? `\n${bad} check(s) failed.` : "\nAll live-refresh checks passed.");
  await b.close();
  process.exit(bad ? 1 : 0);
})();
