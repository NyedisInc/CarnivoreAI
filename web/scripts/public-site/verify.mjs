import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { tmpdir } from 'node:os';
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(process.env.PLAYWRIGHT_MODULE || '/opt/homebrew/lib/node_modules/playwright')); }
const base = process.env.SITE_URL || 'http://localhost:5019';
const out = process.env.VERIFY_OUT || path.join(tmpdir(), 'carnivore-public-site-validation');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({headless:true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const report = {base, started:new Date().toISOString(), runs:[]};
try {
 for (const [name,width,height,js,reduced] of [['desktop',1440,900,true,false],['crossover',800,900,true,false],['phone',390,844,true,false],['compact',360,640,true,false],['reduced',390,844,true,true],['nojs',390,844,false,false]]) {
  const context = await browser.newContext({viewport:{width,height},deviceScaleFactor:1,javaScriptEnabled:js,reducedMotion:reduced?'reduce':'no-preference'});
  await context.addInitScript(() => { Element.prototype.requestPointerLock=()=>Promise.resolve(); Element.prototype.setPointerCapture=()=>{}; Element.prototype.releasePointerCapture=()=>{}; });
  const page=await context.newPage(); const run={name,width,height,js,reduced,errors:[],failed:[],responses:[],samples:[]}; report.runs.push(run);
  page.on('pageerror',e=>run.errors.push(String(e))); page.on('console',m=>{if(m.type()==='error')run.errors.push(m.text());}); page.on('requestfailed',r=>run.failed.push({url:r.url(),error:r.failure()})); page.on('response',r=>{if(r.status()>=400)run.responses.push({url:r.url(),status:r.status()});});
  await page.goto(base,{waitUntil:'networkidle'}); await page.evaluate(()=>document.fonts.ready); await page.waitForTimeout(250);
  run.title=await page.title(); run.acts=await page.locator('[data-sc-act]').evaluateAll(els=>els.map(e=>({id:e.id||e.className,top:e.getBoundingClientRect().top+scrollY,height:e.getBoundingClientRect().height,type:e.dataset.scAct})));
  const max=await page.evaluate(()=>document.documentElement.scrollHeight-innerHeight);
  for(let ai=0;ai<run.acts.length;ai++) {
   const act=run.acts[ai]; const span=act.type==='pin'&&width>750&&!reduced?Math.max(1,act.height-height):Math.max(1,act.height-height*.3);
   for(const fraction of [0,.2,.4,.6,.8,1]) {
    const y=Math.round(Math.min(max,Math.max(0,act.top+span*fraction)));
    await page.evaluate(y=>scrollTo({top:y,behavior:'instant'}),y); await page.waitForTimeout(160);
    const file=`${name}-${ai}-${Math.round(fraction*100)}.png`;
    const state=await page.evaluate(()=>({y:scrollY,overflow:document.documentElement.scrollWidth>innerWidth,broken:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src),motion:[...document.querySelectorAll('[data-sc-parallax],.path-trace,[data-sc-reveal]')].map(e=>({class:e.className,transform:getComputedStyle(e).transform,clip:getComputedStyle(e).clipPath})),text:[...document.querySelectorAll('h1,h2,p,a,button,strong,.viewer-state,.node-index,.hero-base span')].filter(e=>!e.closest('.sr-only')).map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);let opacity=1;for(let x=e;x;x=x.parentElement)opacity*=+getComputedStyle(x).opacity;return {text:e.textContent.trim(),rect:{x:r.x,y:r.y,width:r.width,height:r.height},color:s.color,size:parseFloat(s.fontSize),weight:s.fontWeight,opacity};}).filter(e=>e.rect.y>=0&&e.rect.y+e.rect.height<=innerHeight&&e.rect.width>0&&e.opacity>=.85)}));
    await page.screenshot({path:path.join(out,file)});

    run.samples.push({act:ai,fraction,file,...state});
   }
  }
  await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight)); await page.screenshot({path:path.join(out,`${name}-final.png`)});
  run.downloads=await page.locator('a[href$=".dmg"]').evaluateAll(els=>els.map(e=>e.href));
  run.legal=[];for(const href of await page.locator('footer nav[aria-label="legal"] a').evaluateAll(els=>els.map(e=>e.getAttribute('href')))){ const r=await page.goto(base+href,{waitUntil:'domcontentloaded',timeout:10000});const html=await page.content();run.legal.push({href,status:r.status(),scripts:/<script\b/i.test(html),privacyScripts:href.includes('privacy')?html.match(/.{0,100}script.{0,200}/gi):undefined}); }
  await page.goto(base,{waitUntil:'networkidle'});
  if(js){
   const button=page.getByRole('button',{name:'leave the desk',exact:true}); await button.click(); await page.waitForTimeout(250); run.toggle={label:await page.getByRole('button',{name:'return to desk',exact:true}).textContent(),status:await page.getByRole('status').textContent(),aria:await page.locator('.continuity-machine').getAttribute('aria-label')}; await page.screenshot({path:path.join(out,`${name}-away.png`)});await page.getByRole('button',{name:'return to desk',exact:true}).click();run.toggle.restored=await page.getByRole('status').textContent();
   await page.goto(base,{waitUntil:'networkidle'}); run.focus=[];for(let i=0;i<14;i++){await page.keyboard.press('Tab');await page.waitForTimeout(550);run.focus.push(await page.evaluate(()=>{const e=document.activeElement,r=e.getBoundingClientRect(),s=getComputedStyle(e);let opacity=1;for(let x=e;x;x=x.parentElement)opacity*=+getComputedStyle(x).opacity;return {text:e.textContent.trim(),tag:e.tagName,y:r.y,height:r.height,opacity,outline:s.outline,border:s.borderColor,visible:r.top>=0&&r.bottom<=innerHeight};}));}
  } else run.buttonCount=await page.getByRole('button').count();
  console.log(`${name}: ${run.samples.length} frames; errors=${run.errors.length}, failed=${run.failed.length}, overflow=${run.samples.some(s=>s.overflow)}`);
  await context.close(); await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
 }
}finally{await browser.close();await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));}

const expectedDownload = 'https://github.com/NyedisInc/CarnivoreAI/releases/download/v1.16.2/Carnivore-1.16.2-arm64.dmg';
const failures = [];
for (const run of report.runs) {
 const fail = message => failures.push(`${run.name}: ${message}`);
 if (run.errors.length || run.failed.length || run.responses.length) fail('console, network, or HTTP failure');
 if (run.samples.some(sample => sample.overflow || sample.broken.length)) fail('overflow or broken image');
 if (run.downloads.length !== 2 || run.downloads.some(url => url !== expectedDownload)) fail('unexpected download URL');
 if (run.legal.length !== 3 || run.legal.some(page => page.status !== 200 || page.scripts)) fail('legal page unavailable or scripted');
 if (run.js && (!run.toggle.status.includes('viewer disconnected') || !run.toggle.restored.includes('viewer connected') || !run.toggle.aria.includes('disconnected'))) fail('continuity control did not update accessible state');
 if (!run.js && run.buttonCount !== 0) fail('inactive control exposed without JavaScript');
 if (run.focus?.some(item => item.tag !== 'BODY' && (!item.visible || item.opacity < 0.85))) fail('keyboard target obscured');
}
report.failures = failures;
await writeFile(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; }
