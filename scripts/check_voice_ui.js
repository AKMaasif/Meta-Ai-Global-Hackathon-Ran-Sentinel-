// Run against an isolated offline demo: BASE_URL=http://127.0.0.1:8021 node scripts/check_voice_ui.js
// No real microphone or paid TTS calls: audio generation is stubbed at the HTTP boundary.
const { chromium, request } = require('playwright');
const assert = require('node:assert/strict');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8021';
(async () => {
 const browser = await chromium.launch({headless:true});
 try {
 const admin = await request.newContext({baseURL:BASE});
 assert.equal((await admin.post('/api/login',{data:{portal:'ops',email:process.env.OPS_EMAIL||'ops@northstar.demo',password:process.env.OPS_PASSWORD||'sentinel-demo'}})).status(),200);
 assert.equal((await admin.post('/api/demo/reset')).status(),200);await admin.dispose();
 const p = await browser.newPage({viewport:{width:390,height:844}});
 const errors=[];p.on('pageerror',e=>errors.push(e.message));
 let clips=0, delay=0;
 const wav=Buffer.alloc(44+4800);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(24000,24);wav.writeUInt32LE(48000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(4800,40);
 await p.route('**/api/care/voice/status',r=>r.fulfill({json:{think:'rules',speak:'test',voice:'Kore'}}));
 await p.route('**/api/care/voice/speak',async r=>{clips++;if(delay)await new Promise(z=>setTimeout(z,delay));await r.fulfill({contentType:'audio/wav',body:wav}).catch(()=>{});});
 await p.goto(BASE+'/connect/#/login');await p.locator('#em').fill(process.env.CUSTOMER_EMAIL||'customer@northstar.demo');await p.locator('#pw').fill(process.env.CUSTOMER_PASSWORD||'connect-demo');await p.locator('#f button').click();await p.locator('.app').waitFor();await p.request.post(BASE+'/api/care/prefs',{data:{key:'wifi_calling',value:false}});
 await p.locator('#valaunch').click();
 async function ask(text) {await p.locator('#vaq').fill(text);await p.locator('#vaask button').click();}
 async function idle() {await p.waitForFunction(()=>document.querySelector('#vastatus')?.textContent.startsWith('Tap the mic'),{},{timeout:20000});}
 await ask('What is my bill?');await idle();assert.equal(clips,1);console.log('PASS: multi-sentence answer uses one speech request');
 await ask('Turn on wifi calling');await idle();assert.equal(await p.locator('[data-vconfirm]').count(),1);assert.equal(await p.locator('[data-vcancel]').count(),1);
 let account=await (await p.request.get(BASE+'/api/care/account')).json();assert.equal(account.prefs.wifi_calling,false);console.log('PASS: setting prepared with confirmation and cancel, not applied');
 await p.locator('[data-vcancel]').click();await p.waitForFunction(()=>document.querySelector('#vasay').textContent.includes('Cancelled'));assert.equal(await p.locator('[data-vconfirm]').count(),0);console.log('PASS: Cancel retires pending action');
 await ask('Submit a complaint about slow data at work');await idle();await p.waitForURL('**/#/report');assert.equal(await p.locator('#det').inputValue(),'Submit a complaint about slow data at work');assert.equal(await p.locator('input[name=place]:checked').inputValue(),'work');console.log('PASS: complaint opens as a prefilled reviewable draft');
 await ask('Yes, send it');await idle();assert.match(await p.locator('#vasay').textContent(),/sent report/);assert.equal(await p.locator('[data-vconfirm]').count(),0);console.log('PASS: later explicit yes submits the complaint');
 await ask('Turn on wifi calling');await idle();await p.locator('[data-vconfirm]').click();await p.waitForFunction(()=>document.querySelector('#vasay').textContent.includes('Wi-Fi Calling is on'));account=await (await p.request.get(BASE+'/api/care/account')).json();assert.equal(account.prefs.wifi_calling,true);console.log('PASS: button confirmation applies setting');
 delay=3000;await ask('Show my bill');await p.waitForFunction(()=>document.querySelector('#vastatus').textContent.startsWith('Speaking'));await p.locator('#vaclose').click();await p.waitForTimeout(3200);assert.equal(await p.locator('#vasheet').isVisible(),false);console.log('PASS: close during speech generation stays closed without stale playback');
 await p.locator('#valaunch').click();delay=0;await ask('Open my account');await idle();await p.waitForURL('**/#/account');console.log('PASS: new turn works after cancelled speech');
 await ask('Submit a complaint about slow data at home');await idle();
 const before=(await (await p.request.get(BASE+'/api/care/network')).json()).reports.length;
 await p.locator('#vaclose').click();await p.locator('#det').fill('Edited by the customer: slow data since noon.');await p.locator('#rf button').click();await p.locator('#rres .card').waitFor();
 await p.locator('#valaunch').click();await ask('Yes please');await idle();
 const after=(await (await p.request.get(BASE+'/api/care/network')).json()).reports.length;assert.equal(after,before+1);console.log('PASS: edited manual submission retires voice draft and cannot be submitted again by yes');
 await ask('Open my account');await idle();await p.waitForURL('**/#/account');
 // A delayed agent response must not navigate after closing the assistant.
 await p.route('**/api/care/voice/turn',async r=>{await new Promise(z=>setTimeout(z,800));await r.fulfill({json:{answer:'Here is your bill.',actions:[],steps:[],ui:[{type:'navigate',page:'bill'}],by:'test'}});});
 await ask('Open my bill');await p.waitForFunction(()=>document.querySelector('#vastatus').textContent==='Working on it…');await p.locator('#vaclose').click();await p.waitForTimeout(1200);assert.match(p.url(),/#\/account$/);console.log('PASS: stale reasoning response cannot navigate after close');
 await p.request.post(BASE+'/api/care/prefs',{data:{key:'wifi_calling',value:false}});
 await p.goto(BASE+'/connect/#/assistant');await p.locator('#q').fill('Turn on wifi calling');
 await Promise.all([p.waitForResponse(r=>r.url().endsWith('/api/care/concierge')),p.locator('#ask button.send').click()]);
 await p.locator('#log .bubble.bot').last().locator('[data-confirm]').click();
 await p.waitForFunction(async()=> (await (await fetch('/api/care/account')).json()).prefs.wifi_calling===true);
 console.log('PASS: typed assistant confirmation still works');
 assert.deepEqual(errors,[]);console.log('PASS: no browser JavaScript errors');
 console.log('All 12 voice UI checks passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
