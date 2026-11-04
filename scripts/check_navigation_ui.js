const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const BASE=process.env.BASE_URL||'http://127.0.0.1:8021';
(async()=>{
 const browser=await chromium.launch();
 try{
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(BASE+'/connect/#/login');await page.locator('#demo-start').click();await page.locator('.app').waitFor();
  await page.route('**/api/care/network',async route=>{
   const response=await route.fetch();await new Promise(resolve=>setTimeout(resolve,600));
   await route.fulfill({response}).catch(()=>{});
  });
  const refresh=page.waitForRequest(r=>r.url().endsWith('/api/care/network'));
  await page.evaluate(()=>location.hash='#/network');await refresh;
  await page.evaluate(()=>location.hash='#/report');
  await page.locator('#rf').waitFor();
  assert.equal(await page.locator('input[name=place]:checked').inputValue(),'home');
  assert(!await page.locator('.toast').count());
  console.log('PASS: entering a draft during a delayed refresh does not inherit the aborted request signal');
  const pending=page.waitForRequest(r=>r.url().endsWith('/api/care/network'));
  await page.evaluate(()=>{location.hash='#/network';});await pending;
  const draftRequest=page.waitForRequest(r=>r.url().endsWith('/api/care/network'));
  await page.evaluate(()=>{location.hash='#/report';});
  await draftRequest;
  await page.evaluate(()=>location.hash='#/account');await page.locator('#out').waitFor();
  await page.waitForTimeout(900);
  assert.equal(await page.locator('#rf').count(),0);assert.equal(await page.locator('#out').count(),1);
  assert.deepEqual(errors,[]);
  console.log('PASS: delayed network/draft rendering cannot replace the account page after navigation');
  console.log('All 2 navigation regression checks passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
