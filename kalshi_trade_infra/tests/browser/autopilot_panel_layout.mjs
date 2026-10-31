// Explicit browser regression using real app markup and CSS, with synthetic reads only.
// TAU_PLAYWRIGHT_MODULE=/path/to/playwright node tests/browser/autopilot_panel_layout.mjs
import assert from 'node:assert/strict';
import {readFileSync, mkdirSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve, join} from 'node:path';
import {bundleSource, exposing} from '../bundle_source.mjs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.TAU_PLAYWRIGHT_MODULE || 'playwright');
const output = process.env.TAU_LAYOUT_OUTPUT && resolve(process.env.TAU_LAYOUT_OUTPUT);
if (output) mkdirSync(output, {recursive: true});
const assets = new URL('../../app/static/', import.meta.url);
const expose = ['S', 'apBuildShell', 'apUpdate', 'apFeedLi'];
const boot = '  setupGlossary();\n  render();';
const checks = [], errors = [];
const browser = await chromium.launch({headless:true, channel:process.env.TAU_BROWSER_CHANNEL || 'chrome'});
try {
  for (const theme of ['tau','meridian']) {
    const bundle = theme === 'tau' ? 'app.js' : 'app.meridian.js';
    const original = bundleSource(bundle, {expose, target:'layout'});
    assert.equal(original.split(boot).length, 2);
    const source = original.replace(boot, 'globalThis.layout = ' + exposing(expose) + ';');
    for (const viewport of [{width:1280,height:900},{width:1024,height:768},{width:1280,height:600},{width:760,height:600},{width:390,height:844}]) {
      const page = await browser.newPage({viewport});
      const row = {theme, viewport, passed:false}; checks.push(row);
      page.on('pageerror', e => errors.push({theme,viewport,message:e.message}));
      try {
        await page.route('**/*', route => route.fulfill({contentType:'text/html',body:'<!doctype html><html><head></head><body><div id="app"></div><div id="autopilot-float"></div></body></html>'}));
        await page.goto('http://tau-layout.test/');
        await page.evaluate(() => {
          localStorage.setItem('tau_ap_open','1'); window.layoutRequests=[];
          window.fetch=async (input,options={}) => {
            const url=new URL(input,location.href),method=options.method || 'GET';
            window.layoutRequests.push({path:url.pathname,method});
            if(method!=='GET') throw new Error('Writes forbidden in layout fixture');
            const body=url.pathname==='/api/chat' ? {messages:[],agent_busy:false,turn_cost:0.01}
              : url.pathname==='/api/models' ? {models:[{key:'fixture',label:'Synthetic model'}],default:'fixture'} : {};
            return {ok:true,status:200,json:async()=>body,headers:new Headers()};
          };
        });
        await page.addStyleTag({content:readFileSync(new URL(bundle.replace('.js','.css'),assets),'utf8')});
        await page.addScriptTag({content:source});
        await page.evaluate(() => {
          const {S,apBuildShell,apUpdate}=window.layout;
          S.me={user:{id:7,name:'Synthetic account',autopilot:true},markets:[],directions:[]};
          S.ap={mode:'paper',autopilot:true,autopilot_live:false,live_enabled:false,kalshi_connected:false,
            paper_running:4,live_running:0,demo_running:0,today_paper_pnl:0,
            story:['Four paper strategies are collecting results.','No new research is starting while credits are low.'],
            research:{tested_7d:12,passed_7d:0,active:[]},focus:[],billing_blocked:true,billing_reason:'credits'};
          const box=document.getElementById('autopilot-float'); apBuildShell(box); apUpdate(box,S.ap);
        });
        await page.waitForFunction(()=>document.querySelector('#apf-model')?.options.length>0);
        await page.evaluate(()=>{document.querySelector('.apf-prefs').open=true;});
        const measure=()=>page.evaluate(()=>{
          const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {y:r.y,height:r.height,bottom:r.bottom};};
          const top=document.querySelector('.apf-top'),feed=document.querySelector('#apf-messages');
          return {panel:rect('.apf.open'),controls:rect('.apf-top'),session:rect('.apf-session'),composer:rect('#apf-composer'),
            topScroll:top.scrollTop,feedClient:feed.clientHeight,feedContent:feed.scrollHeight,feedScroll:feed.scrollTop};
        });
        row.short=await measure();
        await page.evaluate(()=>{
          const feed=document.getElementById('apf-messages');feed.replaceChildren();
          const content=Array.from({length:28},(_,i)=>`Synthetic paragraph ${i+1}: reviewing a research result and explaining the next step in detail.`).join('\n\n');
          for(let i=0;i<8;i++)feed.appendChild(window.layout.apFeedLi({id:i+1,role:'assistant',created_at:'2026-10-31T08:09:00Z',content}));
        });
        row.long=await measure();
        if(viewport.width>600){
          assert.ok(row.long.controls.height>=row.short.controls.height-2,`long history collapsed controls from ${row.short.controls.height}px to ${row.long.controls.height}px`);
          assert.ok(row.long.controls.height>=100,'controls have a usable viewport');
          assert.ok(row.long.composer.bottom<=viewport.height+1,'composer stays inside the viewport');
          assert.ok(row.long.panel.y>=-1,'panel starts inside viewport');
          assert.ok(row.long.feedContent>row.long.feedClient,'long feed has its own scrollport');
          await page.evaluate(()=>{const feed=document.getElementById('apf-messages');feed.scrollTop=feed.scrollHeight;});
          await page.waitForFunction(()=>document.getElementById('apf-messages').scrollTop>0,{},{timeout:2000});
          const scrolled=await measure();
          assert.ok(scrolled.feedScroll>0,'feed scrolling is effective');
          assert.equal(scrolled.topScroll,row.long.topScroll,'feed does not scroll controls');
          assert.equal(scrolled.controls.y,row.long.controls.y,'controls stay above feed');
          await page.locator('#apf-focus').focus();
          assert.equal(await page.locator('#apf-focus').evaluate(el=>{
            const r=el.getBoundingClientRect(),at=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
            return document.activeElement===el&&(at===el||el.contains(at));
          }),true,'market control is reachable and not covered');
        }else{
          assert.equal(await page.locator('.apf.open').evaluate(el=>getComputedStyle(el).overflowY),'auto');
          assert.ok(row.long.controls.height>=row.short.controls.height-2,'phone controls keep size');
          assert.ok(row.long.feedContent<=row.long.feedClient+1,'phone feed has no second scroller');
          await page.locator('#apf-messages .ln').last().scrollIntoViewIfNeeded();
          assert.ok(await page.locator('.apf.open').evaluate(el=>el.scrollTop)>0,'phone sheet reaches history');
          await page.locator('#apf-focus').focus();
          assert.equal(await page.locator('#apf-focus').evaluate(el=>document.activeElement===el),true);
        }
        assert.equal(await page.evaluate(()=>window.layoutRequests.some(r=>r.method!=='GET')),false);
        row.passed=true;
      }catch(e){row.error=e.message;}
      if(output&&theme==='tau'&&viewport.width===1280&&viewport.height===900){
        await page.evaluate(()=>{document.querySelector('.apf-top').scrollTop=0;});
        await page.screenshot({path:join(output,'autopilot-desktop.png')});
      }
      await page.close();
    }
  }
}finally{await browser.close();}
const report={mode:'Synthetic fixtures; actual app markup and styles; no account/provider access',checks,errors,
  passed:checks.every(c=>c.passed)&&errors.length===0};
if(output)writeFileSync(join(output,'LAYOUT_REPORT.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({passed:report.passed,cases:checks.length,failures:checks.filter(c=>!c.passed).map(({theme,viewport,error})=>({theme,viewport,error})),errors},null,2));
if(!report.passed)process.exitCode=1;
