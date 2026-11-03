// Destructive to demo state: run against an isolated offline server, not a demo to preserve.
const {chromium,request}=require('playwright');
const assert=require('node:assert/strict');
const BASE=process.env.BASE_URL||'http://127.0.0.1:8021';
(async()=>{
 const admin=await request.newContext({baseURL:BASE});
 assert.equal((await admin.post('/api/login',{data:{portal:'ops',email:process.env.OPS_EMAIL||'ops@northstar.demo',password:process.env.OPS_PASSWORD||'sentinel-demo'}})).status(),200);
 assert.equal((await admin.post('/api/demo/reset')).status(),200);await admin.dispose();
 const browser=await chromium.launch({headless:true});
 try{
 const context=await browser.newContext({viewport:{width:390,height:844}}),p=await context.newPage();
 const errors=[];p.on('pageerror',e=>errors.push(e.message));
 const wav=Buffer.alloc(4844);wav.write('RIFF');wav.writeUInt32LE(4836,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(24000,24);wav.writeUInt32LE(48000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(4800,40);
 let audioCalls=0,lastTurn;
 await context.route('**/api/care/voice/status',r=>r.fulfill({json:{think:'rules',speak:'test',voice:'Kore'}}));
 await context.route('**/api/care/voice/speak',r=>{audioCalls++;return r.fulfill({contentType:'audio/wav',body:wav});});
 p.on('request',r=>{if(r.url().endsWith('/api/care/voice/turn'))lastTurn=r.postDataJSON();});
 const credentials={portal:'connect',email:process.env.CUSTOMER_EMAIL||'customer@northstar.demo',password:process.env.CUSTOMER_PASSWORD||'connect-demo'};
 assert.equal((await context.request.post(BASE+'/api/login',{data:credentials})).status(),200);
 await p.goto(BASE+'/connect/#/home');await p.locator('#valaunch').click();
 async function ask(q){await p.locator('#vaq').fill(q);await p.locator('#vaask button').click();await p.waitForFunction(()=>document.querySelector('#vastatus')?.textContent.startsWith('Tap the mic'),{},{timeout:20000});}
 await ask('My data is slow at work');await ask('Report that');const old=await p.locator('[data-vconfirm]').getAttribute('data-vconfirm');
 assert.equal(await p.locator('input[name=place]:checked').inputValue(),'work');console.log('PASS: report-that resolves the earlier symptom and location');
 const before=audioCalls;await p.reload();await p.locator('#valaunch').click();await p.locator('[data-vconfirm]').waitFor();assert.equal(await p.locator('[data-vconfirm]').getAttribute('data-vconfirm'),old);assert.equal(await p.locator('input[name=place]:checked').inputValue(),'work');assert.match(await p.locator('#det').inputValue(),/slow.*work/i);assert.equal(audioCalls,before);console.log('PASS: page refresh restores draft and dialogue without replaying speech');
 await ask('Actually, change the location to home');const revised=await p.locator('[data-vconfirm]').getAttribute('data-vconfirm');assert.notEqual(revised,old);assert.equal(await p.locator('input[name=place]:checked').inputValue(),'home');assert(!/work/i.test(await p.locator('#det').inputValue()));console.log('PASS: correction revises the visible draft and invalidates its former ID');
 await ask('Read it back');assert.match(await p.locator('#vasay').textContent(),/home/i);console.log('PASS: read-back uses the revised complaint');
 const rejected=await (await context.request.post(BASE+'/api/care/voice/turn',{data:{text:'Yes please',action_id:old,speak:false}})).json();assert.equal(rejected.by,'confirmation guard');console.log('PASS: stale confirmation cannot submit the old draft');
 await ask('Yes, send it');const submitted=lastTurn;assert.match(await p.locator('#vasay').textContent(),/sent report/);const reports=(await(await context.request.get(BASE+'/api/care/network')).json()).reports;assert.equal(reports.length,1);assert.equal(reports[0].place,'Home');console.log('PASS: explicit confirmation submits one complaint for the revised location');
 await context.request.post(BASE+'/api/care/voice/turn',{data:submitted});assert.equal((await(await context.request.get(BASE+'/api/care/network')).json()).reports.length,1);console.log('PASS: retrying the same request does not submit twice');
 await ask('Did you send it?');assert.match(await p.locator('#vasay').textContent(),/reference|completed/i);console.log('PASS: completed-action memory recalls the submission');
 await ask('Turn on wifi calling');const settingOld=await p.locator('[data-vconfirm]').getAttribute('data-vconfirm');
 await ask('Actually, turn it off instead');const settingNew=await p.locator('[data-vconfirm]').getAttribute('data-vconfirm');assert.notEqual(settingOld,settingNew);await ask('Yes please');
 assert.equal((await(await context.request.get(BASE+'/api/care/account')).json()).prefs.wifi_calling,false);
 await ask('Turn it on');await ask('Yes please');assert.equal((await(await context.request.get(BASE+'/api/care/account')).json()).prefs.wifi_calling,true);console.log('PASS: setting corrections and follow-ups preserve explicit confirmation');
 await ask("What's my report number?");assert.match(await p.locator('#vasay').textContent(),/CR-/);console.log('PASS: report reference remains available after a later setting action');
 const other=await browser.newContext();await other.request.post(BASE+'/api/login',{data:credentials});const state=await(await other.request.get(BASE+'/api/care/voice/memory')).json();assert.equal(state.messages.length,0);assert.equal(state.actions.length,0);await other.close();console.log('PASS: a different login cannot read this conversation');
 await p.locator('#vanew').click();await p.waitForFunction(()=>document.querySelector('#vasay').textContent.includes('Conversation cleared'));await ask('Report that');assert.equal(await p.locator('[data-vconfirm]').count(),0);assert.match(await p.locator('#vasay').textContent(),/What problem/);console.log('PASS: New conversation removes context and unconfirmed actions');
 await ask('My data is slow at work');await context.request.post(BASE+'/api/logout');assert.equal((await context.request.get(BASE+'/api/care/voice/memory')).status(),401);await context.request.post(BASE+'/api/login',{data:credentials});assert.equal((await(await context.request.get(BASE+'/api/care/voice/memory')).json()).messages.length,0);console.log('PASS: logout and a new login start with empty memory');
 assert.deepEqual(errors,[]);console.log('PASS: no browser JavaScript errors');console.log('All 14 voice memory browser checks passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
