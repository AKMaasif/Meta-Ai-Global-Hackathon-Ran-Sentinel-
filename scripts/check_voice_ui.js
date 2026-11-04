// Run against an isolated offline demo: BASE_URL=http://127.0.0.1:8021 node scripts/check_voice_ui.js
// No physical microphone: installed system voices are represented by Web Speech test doubles.
const { chromium, request } = require('playwright');
const assert = require('node:assert/strict');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8021';
(async () => {
 const browser = await chromium.launch({headless:true});
 try {
 const admin = await request.newContext({baseURL:BASE});
 assert.equal((await admin.post('/api/demo/start',{data:{portal:'ops'}})).status(),200);
 assert.equal((await admin.post('/api/demo/reset')).status(),200);await admin.dispose();
 const p = await browser.newPage({viewport:{width:390,height:844}});
 const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.addInitScript(() => {
   window.__spoken = []; window.__speechDelay = 20;
   window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
   const remote = {name:'Online voice',lang:'en-US',voiceURI:'remote',localService:false};
   const local = {name:'Test local voice',lang:'en-US',voiceURI:'local',localService:true};
   let timer;
   Object.defineProperty(window, 'speechSynthesis', {value:{
     getVoices:()=>[remote,local], addEventListener:()=>{}, removeEventListener:()=>{},
     speak:u=>{window.__spoken.push({text:u.text,voice:u.voice.voiceURI}); timer=setTimeout(()=>u.onend?.(),window.__speechDelay);},
     cancel:()=>clearTimeout(timer)
   }});
 });
 await p.goto(BASE+'/connect/#/login');await p.locator('#demo-start').click();await p.locator('.app').waitFor();await p.request.post(BASE+'/api/care/prefs',{data:{key:'wifi_calling',value:false}});
 await p.locator('#valaunch').click();
 async function ask(text) {await p.locator('#vaq').fill(text);await p.locator('#vaask button').click();}
 async function idle() {await p.waitForFunction(()=>document.querySelector('#vastatus')?.textContent.startsWith('Tap the mic'),{},{timeout:20000});}
 await ask('What is my bill?');await idle();assert.equal(await p.evaluate(()=>window.__spoken.length),1);assert.equal(await p.evaluate(()=>window.__spoken[0].voice),'local');console.log('PASS: multi-sentence answer uses one local utterance and excludes remote voices');
 await ask('Turn on wifi calling');await idle();assert.equal(await p.locator('[data-vconfirm]').count(),1);assert.equal(await p.locator('[data-vcancel]').count(),1);
 let account=await (await p.request.get(BASE+'/api/care/account')).json();assert.equal(account.prefs.wifi_calling,false);console.log('PASS: setting prepared with confirmation and cancel, not applied');
 await p.locator('[data-vcancel]').click();await p.waitForFunction(()=>document.querySelector('#vasay').textContent.includes('Cancelled'));assert.equal(await p.locator('[data-vconfirm]').count(),0);console.log('PASS: Cancel retires pending action');
 await ask('Submit a complaint about slow data at work');await idle();await p.waitForURL('**/#/report');assert.equal(await p.locator('#det').inputValue(),'Submit a complaint about slow data at work');assert.equal(await p.locator('input[name=place]:checked').inputValue(),'work');console.log('PASS: complaint opens as a prefilled reviewable draft');
 await ask('Yes, send it');await idle();assert.match(await p.locator('#vasay').textContent(),/sent report/);assert.equal(await p.locator('[data-vconfirm]').count(),0);console.log('PASS: later explicit yes submits the complaint');
 await ask('Turn on wifi calling');await idle();await p.locator('[data-vconfirm]').click();await p.waitForFunction(()=>document.querySelector('#vasay').textContent.includes('Wi-Fi Calling is on'));account=await (await p.request.get(BASE+'/api/care/account')).json();assert.equal(account.prefs.wifi_calling,true);console.log('PASS: button confirmation applies setting');
 await p.evaluate(()=>window.__speechDelay=3000);await ask('Show my bill');await p.waitForFunction(()=>document.querySelector('#vastatus').textContent.startsWith('Speaking'));await p.locator('#vaclose').click();await p.waitForTimeout(3200);assert.equal(await p.locator('#vasheet').isVisible(),false);console.log('PASS: close during local speech stops playback and stays closed');
 await p.locator('#valaunch').click();await p.evaluate(()=>window.__speechDelay=20);await ask('Open my account');await idle();await p.waitForURL('**/#/account');console.log('PASS: new turn works after cancelled speech');
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
