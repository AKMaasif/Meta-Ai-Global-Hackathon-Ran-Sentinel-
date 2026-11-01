const fs = require("fs"), path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); } catch {
  console.error("Playwright is not installed. In the project folder run:\n  npm i --no-save playwright\n  npx playwright install chromium\nthen run this script again.");
  process.exit(2);
}
const fromEnvFile = (() => {
  try {
    const out = {};
    for (const line of fs.readFileSync(path.join(__dirname, "..", ".env"), "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/);
      if (m) out[m[1]] = m[2].replace(/^(["'])(.*)\1$/, "$2");
    }
    return out;
  } catch { return {}; }
})();
const DEFAULTS = { OPS_EMAIL: "ops@northstar.demo", OPS_PASSWORD: "sentinel-demo", CUSTOMER_EMAIL: "customer@northstar.demo", CUSTOMER_PASSWORD: "connect-demo" };
const setting = (k) => process.env[k] || fromEnvFile[k] || DEFAULTS[k] || "";
const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const results = [];
const check = (name, ok, detail) => results.push({ name, ok: !!ok, detail });
const VIEWPORTS = [["phone", 360, 740], ["tablet", 768, 1024], ["desktop", 1440, 900]];

const overflow = (p) => p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const unnamed = (p) => p.evaluate(() => [...document.querySelectorAll("#app button, #app a, #app input, #app select, #app textarea")]
  .filter((e) => e.offsetParent !== null)
  .filter((e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(e.tagName)) return !(e.getAttribute("aria-label") || (e.id && document.querySelector(`label[for="${e.id}"]`)));
    return !(e.textContent.trim() || e.getAttribute("aria-label") || e.getAttribute("title"));
  }).map((e) => e.outerHTML.slice(0, 80)));

async function customer(b, vp) {
  const [label, w, h] = vp;
  const ctx = await b.newContext({ viewport: { width: w, height: h } });
  const p = await ctx.newPage();
  const errors = []; p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(`${BASE}/connect/#/login`); await p.waitForSelector("#em");
  await p.fill("#em", setting("CUSTOMER_EMAIL")); await p.fill("#pw", setting("CUSTOMER_PASSWORD")); await p.click("#f button");
  await p.waitForTimeout(1500);
  if (!(await p.locator(".tabbar").count())) { check(`${label}: customer sign-in`, false, "check CUSTOMER_EMAIL and CUSTOMER_PASSWORD"); await ctx.close(); return null; }
  await p.goto(`${BASE}/connect/#/help`); await p.waitForSelector(".helphero");
  check(`${label}: Help center loads with topics and popular questions`, (await p.locator(".cat").count()) >= 5 && (await p.locator("details.faq").count()) >= 3);
  check(`${label}: Help center has no horizontal scroll`, (await overflow(p)) <= 1, `${await overflow(p)} px`);
  const faq = p.locator("details.faq").first(); await faq.locator("summary").click();
  check(`${label}: FAQ expands`, await faq.evaluate((d) => d.open));
  await p.locator(".cat").nth(1).click(); await p.waitForTimeout(700);
  check(`${label}: topic filter shows only that topic`, (await p.locator(".cat.on").count()) === 1 && (await p.locator("details.faq").count()) === 2);
  await p.fill("#hq", "credit"); await p.waitForTimeout(900);
  check(`${label}: search finds the outage credit article`, ((await p.locator("#hres details.faq b").first().textContent()) || "").includes("Outage credits"));
  await p.fill("#hq", "zzzqqq"); await p.waitForTimeout(900);
  check(`${label}: search shows an empty state`, (await p.locator("#hres .emptybox").count()) === 1);
  await p.fill("#hq", ""); await p.waitForTimeout(500);
  await p.goto(`${BASE}/connect/#/help/outage-check`); await p.waitForSelector("figure.shot img");
  await p.locator("figure.shot img").scrollIntoViewIfNeeded(); await p.waitForTimeout(600);
  check(`${label}: article screenshot loads`, await p.locator("figure.shot img").evaluate((i) => i.complete && i.naturalWidth > 0));
  await p.goto(`${BASE}/connect/#/support/new`); await p.waitForSelector("#tf");
  await p.fill("#f-email", "not-an-email"); await p.fill("#f-subject", "ab"); await p.click("#tf button[type=submit]"); await p.waitForTimeout(300);
  const inv = await p.locator('#tf [aria-invalid="true"]').count();
  check(`${label}: contact form flags invalid fields`, inv === 4 && (await p.locator("#err-email").textContent()).includes("name@example.com"), `${inv} fields marked`);
  check(`${label}: contact form has no horizontal scroll`, (await overflow(p)) <= 1);
  check(`${label}: every visible control has an accessible name`, (await unnamed(p)).length === 0, (await unnamed(p)).join(" | "));
  await p.fill("#f-email", "jordan@example.com"); await p.selectOption("#f-category", "network");
  await p.fill("#f-subject", `UI check on ${label}`); await p.fill("#f-description", "Automated browser check: the phone shows one bar indoors at home.");
  await p.click("#tf button[type=submit]"); await p.waitForSelector("#newbox.done", { timeout: 8000 }).catch(() => {});
  const id = ((await p.locator("#newbox b.mono").textContent().catch(() => "")) || "").trim();
  check(`${label}: request is created and confirmed with a reference`, /^CS-\d{6}$/.test(id), id);
  await p.goto(`${BASE}/connect/#/support`); await p.waitForTimeout(1000);
  check(`${label}: request appears in My support requests`, (await p.locator(`a[href="#/support/${id}"]`).count()) === 1);
  await p.goto(`${BASE}/connect/#/support/${id}`); await p.waitForSelector(".thread");
  await p.fill("#rbody", "Adding a detail from the browser check."); await p.click("#rf button[type=submit]"); await p.waitForTimeout(1500);
  check(`${label}: customer reply is added to the conversation`, (await p.locator(".thread .msg.me").count()) === 2);
  check(`${label}: no JavaScript errors in the customer app`, errors.length === 0, errors.join("; "));
  return { p, ctx, id };
}

(async () => {
  const b = await chromium.launch();
  const made = [];
  for (const vp of VIEWPORTS) { const r = await customer(b, vp); if (r) made.push([vp, r]); }
  const errors = [];
  const o = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  o.on("pageerror", (e) => errors.push(e.message));
  await o.goto(`${BASE}/ops/#/login`); await o.waitForSelector("#email");
  await o.fill("#email", setting("OPS_EMAIL")); await o.fill("#pw", setting("OPS_PASSWORD")); await o.click(".form button"); await o.waitForTimeout(2500);
  if (made.length) {
    const [, { p, id }] = made[made.length - 1];
    await o.goto(`${BASE}/ops/#/support`); await o.waitForTimeout(2000);
    check("ops: support desk lists the new request", (await o.locator(`tr[data-sup="${id}"]`).count()) === 1);
    await o.fill("#sup-q", id); await o.press("#sup-q", "Enter"); await o.waitForTimeout(1500);
    check("ops: search narrows the list to one ticket", (await o.locator("tr[data-sup]").count()) === 1);
    await o.locator(`tr[data-sup="${id}"]`).click(); await o.waitForSelector("#sbody");
    await o.fill("#sbody", "Reply from the browser check."); await o.waitForTimeout(4500);
    check("ops: reply draft survives the live refresh", (await o.inputValue("#sbody")) === "Reply from the browser check.");
    await o.click("#srf button[type=submit]"); await o.waitForTimeout(1500);
    check("ops: reply posted and status changed", (await o.locator(".supthread .m.agent").count()) === 1 && (await o.locator(".pagehead .chip").first().textContent()).includes("Waiting for customer"));
    const sel = o.locator('select[id="sprio"]'); await sel.selectOption("high"); await o.locator('form[id^="suf-"] button[type=submit]').click(); await o.waitForTimeout(1500);
    check("ops: priority saved", (await o.locator(".pagehead").textContent()).includes("High priority"));
    for (const w of [1024, 1440]) { await o.setViewportSize({ width: w, height: 900 }); await o.waitForTimeout(500); check(`ops: ticket page fits at ${w} px`, (await overflow(o)) <= 1); }
    await p.waitForTimeout(5500);
    check("customer: sees the care team's reply without reloading", (await p.locator(".thread .msg.agent").count()) === 1 && (await p.locator(".card .pill").first().textContent()).includes("Waiting for your reply"));
    const [, first] = made[0];
    await o.request.post(`${BASE}/api/support/tickets/${first.id}/reply`, { data: { body: "Second reply from the browser check." } });
    await first.p.goto(`${BASE}/connect/#/help`); await first.p.waitForTimeout(1500);
    check("customer: Help tab and Help center show the new-reply marker", (await first.p.locator('.tabbar a[href="#/help"] .dot').count()) === 1 && (await first.p.locator(`a.replynote[href="#/support/${first.id}"]`).count()) === 1);
    await first.p.goto(`${BASE}/connect/#/support/${first.id}`); await first.p.waitForTimeout(1200);
    await first.p.goto(`${BASE}/connect/#/help`); await first.p.waitForTimeout(1500);
    check("customer: marker clears after reading the reply", (await first.p.locator('.tabbar a[href="#/help"] .dot').count()) === 0 && (await first.p.locator("a.replynote").count()) === 0);
  }
  check("no JavaScript errors in the ops console", errors.length === 0, errors.join("; "));
  await b.close();
  for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.detail ? "  (" + r.detail + ")" : ""}`);
  const bad = results.filter((r) => !r.ok).length;
  console.log(bad ? `\n${bad} of ${results.length} check(s) failed.` : `\nAll ${results.length} support UI checks passed.`);
  process.exit(bad ? 1 : 0);
})();
