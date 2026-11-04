// Browser API tests use synthetic voices; physical speaker quality needs a human check.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch();
  let passed = 0;
  try {
    const page = await browser.newPage();
    async function setup(mode) {
      await page.goto('about:blank');
      await page.evaluate((mode) => {
        const handlers = new Set();
        const local = {name:'Local English',voiceURI:'local',lang:'en-US',localService:true};
        const remote = {name:'Premium Online',voiceURI:'remote',lang:'en-US',localService:false};
        window.spoken = []; window.cancelled = 0; window.available = mode === 'delayed' ? [] : mode === 'remote' ? [remote] : [remote,local];
        window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
        Object.defineProperty(window,'speechSynthesis',{configurable:true,value:mode === 'unsupported' ? undefined : {
          getVoices:()=>window.available,
          addEventListener:(name,fn)=>handlers.add(fn), removeEventListener:(name,fn)=>handlers.delete(fn),
          cancel:()=>window.cancelled++,
          speak:u=>{window.spoken.push({text:u.text,voice:u.voice.voiceURI}); if(mode==='error')setTimeout(()=>u.onerror?.(),10); else if(mode!=='pending')setTimeout(()=>u.onend?.(),10);}
        }});
        window.loadVoices = () => { window.available=[remote,local]; handlers.forEach(fn=>fn()); };
      }, mode);
      await page.addScriptTag({path:path.resolve(__dirname,'../frontend/shared/local-speech.js')});
    }
    await setup('normal');
    let result=await page.evaluate(async()=>({result:await LocalSpeech.say('First sentence. Second sentence.',{voiceURI:'remote'}),spoken:window.spoken}));
    assert.deepEqual(result.spoken,[{text:'First sentence. Second sentence.',voice:'local'}]);passed++;console.log('PASS: one complete local utterance; requested remote voice cannot be selected');
    await page.evaluate(()=>LocalSpeech.say('Do not speak',{voiceURI:'off'}));assert.equal(await page.evaluate(()=>window.spoken.length),1);passed++;console.log('PASS: Text only produces no speech');
    await setup('remote');result=await page.evaluate(()=>LocalSpeech.say('No remote speech'));assert.match(result.note,/No local English/);assert.equal(await page.evaluate(()=>window.spoken.length),0);passed++;console.log('PASS: remote-only voices leave a readable text fallback');
    await setup('delayed');await page.evaluate(()=>{window.reply=LocalSpeech.say('Late voices');setTimeout(loadVoices,50);});await page.evaluate(()=>window.reply);assert.equal(await page.evaluate(()=>window.spoken.length),1);passed++;console.log('PASS: delayed local voice discovery works');
    await setup('pending');await page.evaluate(()=>window.reply=undefined);await page.evaluate(()=>{window.reply=LocalSpeech.say('Interrupt this');});await page.evaluate(()=>LocalSpeech.cancel());result=await page.evaluate(()=>window.reply);assert(result.cancelled);passed++;console.log('PASS: interruption settles pending playback');
    await setup('delayed');await page.evaluate(()=>{window.reply=LocalSpeech.say('Must never start');LocalSpeech.cancel();loadVoices();});result=await page.evaluate(()=>window.reply);assert(result.cancelled);assert.equal(await page.evaluate(()=>window.spoken.length),0);passed++;console.log('PASS: cancellation while discovering voices cannot start stale speech');
    await setup('error');result=await page.evaluate(()=>LocalSpeech.say('Playback fails'));assert.match(result.note,/could not play/);passed++;console.log('PASS: playback errors return a text fallback');
    await setup('unsupported');result=await page.evaluate(()=>LocalSpeech.say('Unsupported browser'));assert.match(result.note,/unavailable/);passed++;console.log('PASS: browsers without speech synthesis retain text');
    console.log(`All ${passed} local speech checks passed.`);
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
