const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';

const scriptDir = path.dirname(new URL(import.meta.url).pathname);
const output = process.env.TAU_BROWSER_EVIDENCE_DIR ? path.resolve(process.env.TAU_BROWSER_EVIDENCE_DIR) : scriptDir;
await fs.mkdir(output, {recursive:true});
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath: process.env.CHROMIUM_EXECUTABLE_PATH} : {}) });
const checks = [], errors = [], requests = [];
function check(name, pass, detail) { checks.push({ name, pass: !!pass, detail }); }
const origin = process.env.TAU_PREVIEW_ORIGIN || 'http://127.0.0.1:8097';
async function ready(page) {
  await page.locator('#app[aria-busy="false"]').waitFor();
  await page.evaluate(() => document.fonts.ready);
  if (await page.getByRole('button', { name: 'Collapse', exact: true }).isVisible()) await page.getByRole('button', { name: 'Collapse', exact: true }).click();
}
try {
  for (const width of [360, 760, 1024, 1280, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 1080 }, deviceScaleFactor: 1, hasTouch: width < 800, reducedMotion: 'reduce' });
    await context.addCookies([{ name: 'tau_ui_preview', value: '1', domain: '127.0.0.1', path: '/' }]);
    const page = await context.newPage();
    page.on('pageerror', e => errors.push({ width, error: e.message }));
    page.on('request', r => { if (!r.url().startsWith(origin)) requests.push(r.url()); });
    for (const [name, route] of [['dashboard','/dashboard'], ['research','/research'], ['workspace','/research/1?strategy=1'], ['library','/research?artifacts=1&status='], ['position','/deploy'], ['explore','/explore'], ['community','/community'], ['account','/funds'], ['billing','/billing'], ['system','/system']]) {
      await page.goto(origin + route); await ready(page);
      if (name === 'workspace') await page.locator('#artifact-panel .sheet-doc').waitFor({ state: 'attached' });
      const geometry = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth, bg: getComputedStyle(document.body).backgroundColor, font: getComputedStyle(document.body).fontFamily, failed: document.body.textContent.includes('Something went wrong'), nav: [...document.querySelectorAll('.svc-link')].length }));
      check(`${name} fits at ${width}px`, geometry.document <= geometry.width && !geometry.failed, geometry);
      check(`${name} keeps shell and local font at ${width}px`, geometry.nav === 8 && geometry.font.includes('DM Sans') && geometry.bg === 'rgb(252, 252, 252)');
      if (name === 'dashboard') {
        check(`overview uses real session links and portfolio at ${width}px`, await page.locator('.overview-sessions .run-card').count() === 4 && await page.locator('.portfolio-value dd').textContent() === '$1,024.80');
        check(`deployment trend has a dedicated column at ${width}px`, await page.locator('.t-dep thead .dep-trend').count() === 1 && await page.locator('.t-dep tbody .dep-trend .spark').count() === 1);
        const plot = page.locator('#overview-performance-chart .chart');
        await page.waitForFunction(() => { const el = document.querySelector('#overview-performance-chart .chart'); return el && Math.abs(el.viewBox.baseVal.width - el.getBoundingClientRect().width) < 2; });
        const points = (await plot.locator('polyline').getAttribute('points')).split(' ').map(point => point.split(',').map(Number));
        check(`period P&L preserves loss days and correct endpoint at ${width}px`, points.length === 7 && points[1][1] > points[0][1] && points[4][1] > points[3][1] && (await plot.getAttribute('aria-label')).includes('paper profit and loss over the last 7 days; ends at +$24.80'));
        await page.getByText('Daily results', {exact:true}).click();
        check(`underlying daily results remain available at ${width}px`, await page.locator('.daily-results tbody tr').count() === 7 && await page.getByRole('cell', {name:'−$2.40',exact:true}).isVisible());
        await page.getByText('Daily results', {exact:true}).click();
        await page.getByRole('button', {name:'Expand hot markets',exact:true}).click();
        check(`expanded markets fit at ${width}px`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        await page.getByRole('button', {name:'Collapse',exact:true}).click();
        await page.waitForFunction(() => { const el = document.querySelector('#overview-performance-chart .chart'); return el && Math.abs(el.viewBox.baseVal.width - el.getBoundingClientRect().width) < 2; });
        check(`drawer close restores focus and measured chart at ${width}px`, await page.getByRole('button', {name:'Expand hot markets',exact:true}).evaluate(el => el === document.activeElement));
      }
      if (['dashboard','workspace','research','position'].includes(name)) await page.screenshot({ path: path.join(output, `verified-${name}-${width}.png`), fullPage: true });
      if (name === 'research') {
        check(`all six markets plus automatic choice retained at ${width}px`, await page.locator('input[name="market"]').count() === 7);
        check(`run forever keeps depth disabled at ${width}px`, await page.locator('#maxhyp').isDisabled());
        await page.locator('#runforever').uncheck();
        check(`depth becomes editable at ${width}px`, await page.locator('#maxhyp').isEnabled());
      }
      if (name === 'billing' && width < 1100) {
        const activeVisible = await page.locator('.svc-link[aria-current="page"]').evaluate(el => { const r = el.getBoundingClientRect(), p = el.parentElement.parentElement.getBoundingClientRect(); return r.left >= p.left - 1 && r.right <= p.right + 1; });
        check(`selected navigation is visible at ${width}px`, activeVisible);
      }
    }
    await page.goto(origin + '/research/1?strategy=1'); await ready(page);
    await page.locator('#session-chat-message').waitFor({ state: 'attached' });
    if (width <= 800) await page.getByRole('button', { name: 'Conversation', exact: true }).click();
    await page.getByRole('textbox', { name: 'Message the agent', exact: true }).fill('Preserve this local styling-check draft.');
    await page.locator('[data-open-artifact="6"]').click();
    await page.locator('#artifact-panel[data-artifact-id="6"] .sheet-doc').waitFor();
    check(`opening second artifact retains both tabs at ${width}px`, await page.locator('#artifact-tabs [role="tab"]').count() === 2);
    await page.getByRole('tab', { name: '#1 · Sample: fade overpriced tails', exact: true }).click();
    await page.locator('#artifact-panel[data-artifact-id="1"] .sheet-doc').waitFor();
    check(`saved artifact keeps all evidence and gates at ${width}px`, await page.locator('#artifact-panel .rules li').count() === 3 && await page.locator('#artifact-panel .split dl').count() === 2 && await page.getByRole('button', { name: 'Deploy with live money', exact: true }).isDisabled());
    if (width <= 800) await page.getByRole('button', { name: 'Conversation', exact: true }).click();
    check(`draft survives artifact switches at ${width}px`, await page.getByRole('textbox', { name: 'Message the agent', exact: true }).inputValue() === 'Preserve this local styling-check draft.');
    await page.getByRole('link', { name: 'Position', exact: true }).click(); await ready(page);
    await page.getByRole('link', { name: 'Research', exact: true }).click(); await ready(page);
    await page.locator('.run-card[href="/research/1"]').click(); await ready(page);
    check(`tabs survive SPA navigation at ${width}px`, await page.locator('#artifact-tabs [role="tab"]').count() === 2);
    if (width <= 800) await page.getByRole('button', { name: 'Conversation', exact: true }).click();
    check(`draft survives SPA navigation at ${width}px`, await page.getByRole('textbox', { name: 'Message the agent', exact: true }).inputValue() === 'Preserve this local styling-check draft.');
    if (width <= 800) await page.getByRole('button', { name: /Strategies 2/ }).click();
    await page.getByRole('button', { name: 'Close strategy #6', exact: true }).click();
    await page.getByRole('button', { name: 'Close strategy #1', exact: true }).click();
    check(`last-tab close returns to usable conversation at ${width}px`, await page.getByRole('textbox', { name: 'Message the agent', exact: true }).isVisible());
    await context.close();
  }
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, reducedMotion: 'reduce' });
  await context.addCookies([{ name: 'tau_ui_preview', value: '1', domain: '127.0.0.1', path: '/' }]);
  const page = await context.newPage();
  await page.route('**/api/runs', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Synthetic research read unavailable' }) }));
  await page.goto(origin + '/dashboard'); await ready(page);
  check('optional research read failure preserves portfolio and deployments', await page.locator('.portfolio-value dd').textContent() === '$1,024.80' && await page.locator('.t-dep tbody tr').count() === 1 && await page.getByText('Synthetic research read unavailable', {exact:true}).isVisible());
  await page.unroute('**/api/runs');
  await page.route('**/api/runs', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({runs:[]}) }));
  await page.goto(origin + '/dashboard'); await ready(page);
  check('empty research uses a calm state without an extra action', await page.getByText('Your research sessions will appear here.', {exact:true}).isVisible() && await page.locator('.overview-sessions .run-card').count() === 0 && await page.getByRole('link', {name:'New research',exact:true}).count() === 1);
  await page.unroute('**/api/runs');
  let release;
  const hold = new Promise(resolve => { release = resolve; });
  await page.route('**/api/runs', async route => { const response = await route.fetch(); await hold; await route.fulfill({ response }); });
  await page.goto(origin + '/dashboard');
  await page.getByRole('link', {name:'Billing',exact:true}).click();
  await page.getByRole('heading', {name:'Billing',exact:true}).waitFor();
  release();
  await page.waitForLoadState('networkidle');
  check('late dashboard response cannot replace a different page', new URL(page.url()).pathname === '/billing' && await page.getByRole('heading', {name:'Billing',exact:true}).isVisible() && await page.locator('.dash-overview').count() === 0);
  await context.close();
  check('no browser runtime errors', errors.length === 0, errors);
  check('all assets and data remain local', requests.length === 0, requests);
} catch (error) { check('browser run completed', false, error.stack); }
finally {
  await browser.close();
  const sourceHashes = {};
  for (const name of ['app.css','app.js','index.html']) sourceHashes[name] = createHash('sha256').update(await fs.readFile(path.resolve(scriptDir, '../../app/static', name))).digest('hex');
  const result = { timestamp: new Date().toISOString(), fixture: 'Read-only synthetic editing preview; no provider, financial or account writes.', sourceHashes, checks, passed: checks.filter(x => x.pass).length, failed: checks.filter(x => !x.pass) };
  await fs.writeFile(path.join(output, 'BROWSER_CHECKS.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({ passed: result.passed, failed: result.failed }));
  if (result.failed.length) process.exitCode = 1;
}
