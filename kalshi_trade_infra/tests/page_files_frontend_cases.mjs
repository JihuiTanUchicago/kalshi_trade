// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the page
// files (app-<name>.js, app.meridian-<name>.js), fetched on first use (pageLoad, pageView).
// - a page whose file isn't in yet shows its skeleton and fetches the file once, by the version the
//   shell names; a file that fails, or doesn't arrive in time, fails its page with Try again, which
//   fetches it afresh, and the page draws once it is in;
// - a file that arrives after the user moved on never draws over the next page;
// - a file from another build that asks for a helper this build doesn't share fails as it runs;
// - after the first page paints, the files not yet in are prefetched once, at the lowest priority;
// - a page's own files (Funds' perps, broker and Alpaca paper scripts and stylesheets) never hold its
//   first figure back: the page draws once its file is in, and they load when its file asks, once that
//   frame has painted, each once; one that fails leaves its part out, never fails the page, and the next
//   ask fetches it afresh; those already on the page are neither fetched nor prefetched again; Funds'
//   perps box mounts once its script is in;
// - the autopilot panel's file (page-autopilot.js, one for both themes) is fetched the first time the panel opens, once: the
//   pill needs none, the panel shows its head over a skeleton meanwhile, and a file that doesn't
//   arrive says so in the panel with Try again; a panel closed meanwhile stays closed.
// The harnesses run every page file up front (bundle_source.mjs); a case takes one out to see it fetched.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

export function pageFileCases({name, frontend, prefix, pagesKey, storageFor}) {
  // A page as the shell left it: #tau-boot names each page file's version, and <head> takes the
  // script and prefetch elements the bundle adds (recorded here; nothing is fetched).
  const page = (versions, opts = {}) => {
    const reports = [];
    const f = frontend({fetchImpl: () => response({}), win: {__tauReport: (kind, err) => reports.push([kind, String(err)])}, ...opts});
    const boot = f.document.createElement('div');
    boot.id = 'tau-boot'; boot.dataset[pagesKey] = versions;
    f.document.body.appendChild(boot);
    const head = [];
    f.document.head = {appendChild: (el) => head.push(el)};
    return {f, head, reports, boot};
  };
  // A page's own files (#tau-boot data-page-assets), and the ones already on the page.
  const ownFiles = (boot, f, assets, linked = []) => {
    boot.dataset.pageAssets = assets;
    f.document.querySelectorAll = (sel) => linked.filter((src) => sel.startsWith(/\.css\?/.test(src) ? 'link' : 'script'))
      .map((src) => ({getAttribute: () => src}));
  };

  test(`${name}: a page file that doesn't arrive fails its page with Try again, which fetches it afresh`, async () => {
    const {f, head, reports} = page('research:1a2b3c,strategies:4d5e6f');
    delete f.PAGES.strategies;  // not fetched yet
    const drawn = [];
    f.location.pathname = '/strategies';
    const first = f.render(); await flush();
    // The page's skeleton under its nav at once, and one fetch of its file by the shell's version.
    assert.equal(head.length, 1);
    assert.equal(head[0].tag, 'script');
    assert.equal(head[0].src, `/static/${prefix}strategies.js?v=4d5e6f`);
    assert.match(f.root.innerHTML, /class="skeleton"/);
    assert.equal(f.root.getAttribute('aria-busy'), 'true');
    head[0].onerror(); await first; await settle();
    assert.ok(f.root.querySelector('.load-fail'), 'the failure is on the page');
    assert.match(f.root.innerHTML, /This page didn\u2019t load\. Check your connection and try again\./);
    assert.equal(f.root.getAttribute('aria-busy'), 'false');
    assert.deepEqual(reports, [['api', `GET /static/${prefix}strategies.js did not load`]]);
    // Try again fetches the file afresh; one that never arrives fails the same way, in time.
    f.root.querySelector('[data-retry]').onclick(); await flush();
    assert.equal(head.length, 2);
    assert.equal(head[1].src, head[0].src);
    f.elapse(20000); await settle();
    assert.ok(f.root.querySelector('.load-fail'), 'a file that never arrives fails its page too');
    // The third time it arrives (its file registers as it runs): the page draws, and no error stays up.
    f.root.querySelector('[data-retry]').onclick(); await flush();
    assert.equal(head.length, 3);
    f.PAGES.strategies = {viewStrategies: () => { drawn.push('list'); f.root.querySelector('main').innerHTML = '<p id="drawn">Strategies</p>'; }};
    head[2].onload(); await settle();
    assert.deepEqual(drawn, ['list']);
    assert.ok(f.root.querySelector('#drawn'));
    assert.equal(f.root.querySelector('.load-fail'), null);
    // In now: the next visit draws without a fetch.
    await f.render(); await settle();
    assert.deepEqual(drawn, ['list', 'list']);
    assert.equal(head.length, 3);
  });

  test(`${name}: a file that loads without registering fails its page instead of drawing nothing`, async () => {
    const {f, head} = page('community:0a0b0c');
    delete f.PAGES.community;
    f.location.pathname = '/community';
    const done = f.render(); await flush();
    head[0].onload(); await done; await settle();
    assert.match(f.root.innerHTML, /This page didn\u2019t load/);
  });

  test(`${name}: a page file that arrives after the user moved on never draws over the next page`, async () => {
    const {f, head} = page('funds:abc123');
    delete f.PAGES.funds;
    const drawn = [];
    f.location.pathname = '/funds';
    const done = f.render(); await flush();
    assert.equal(head[0].src, `/static/${prefix}funds.js?v=abc123`);
    f.S.gen++;  // the next page has started
    f.PAGES.funds = {viewFunds: () => drawn.push('funds')};
    head[0].onload(); await done; await settle();
    assert.deepEqual(drawn, []);
  });

  test(`${name}: a page file asking for a helper this build doesn't share fails as it runs`, () => {
    const {f} = page('');
    delete f.PAGES.admin;
    assert.throws(() => f.window.TauPage('admin', (T) => { const {notShared} = T; return {viewAdmin: notShared}; }), /asks for notShared/);
    assert.equal(f.PAGES.admin, undefined);
    f.window.TauPage('admin', (T) => ({viewAdmin: () => T.esc('<b>')}));
    assert.equal(f.PAGES.admin.viewAdmin(), '&lt;b&gt;');
    // Once per name: a second copy of a file (a retry that raced the first) changes nothing.
    const first = f.PAGES.admin;
    f.window.TauPage('admin', () => ({viewAdmin: () => 'other'}));
    assert.equal(f.PAGES.admin, first);
  });

  test(`${name}: after the first page paints, the page files not yet in are prefetched once, at idle`, async () => {
    const {f, head} = page('research:111aaa,strategies:222bbb,funds:333ccc');
    delete f.PAGES.funds; delete f.PAGES.research;
    f.PAGES.strategies = {viewStrategies: () => {}};
    f.location.pathname = '/strategies';
    await f.render(); await settle();
    assert.equal(head.length, 0, 'nothing before the page is idle');
    f.elapse(3000);
    assert.deepEqual(head.map((l) => [l.tag, l.rel, l.href]), [
      ['link', 'prefetch', `/static/${prefix}research.js?v=111aaa`], ['link', 'prefetch', `/static/${prefix}funds.js?v=333ccc`]]);
    await f.render(); await settle(); f.elapse(3000);
    assert.equal(head.length, 2, 'once a load');
  });

  test(`${name}: a page draws without waiting on its own files, which load once it has painted, when its file asks`, async () => {
    const {f, head, reports, boot} = page('funds:abc123');
    ownFiles(boot, f, 'funds:/static/kalshi-perps-live.css?v=0c0c0c funds:/static/kalshi-perps-live.js?v=0d0d0d funds:/static/broker-connections.js?v=0e0e0e other:/static/x.js?v=1',
      ['/static/broker-connections.js?v=0e0e0e']);  // already on the page
    delete f.PAGES.funds;
    const drawn = [];
    f.location.pathname = '/funds';
    const done = f.render(); await flush();
    // Only the page file: its own files never go out ahead of it.
    assert.deepEqual(head.map((el) => [el.tag, el.src || el.href]), [['script', `/static/${prefix}funds.js?v=abc123`]]);
    // The file runs as it arrives, as a fetched one does, and asks for its own files once it has drawn.
    f.window.TauPage('funds', (T) => ({viewFunds: () => { drawn.push('funds'); T.pageAssets('funds').then(() => drawn.push('own files')); }}));
    head[0].onload(); await done; await settle();
    assert.deepEqual(drawn, ['funds'], 'the page draws with its own files not even asked for yet');
    assert.equal(f.root.getAttribute('aria-busy'), 'false');
    assert.equal(head.length, 1, 'nothing before the drawn frame has painted');
    f.elapse(16); f.elapse(0); await settle();  // the frame, then just after its paint
    assert.deepEqual(head.slice(1).map((el) => [el.tag, el.rel || '', el.src || el.href]), [
      ['link', 'stylesheet', '/static/kalshi-perps-live.css?v=0c0c0c'], ['script', '', '/static/kalshi-perps-live.js?v=0d0d0d']]);
    head[1].onload(); head[2].onerror(); await settle();
    assert.deepEqual(drawn, ['funds', 'own files'], 'a file that fails leaves its part out, never the page');
    assert.deepEqual(reports, [['api', 'GET /static/kalshi-perps-live.js did not load']]);
    // The next visit draws at once; its ask fetches only the one that failed, afresh.
    await f.render(); await settle(); f.elapse(16); f.elapse(0); await settle();
    assert.deepEqual(drawn, ['funds', 'own files', 'funds']);
    assert.deepEqual(head.slice(3).map((el) => el.src || el.href), ['/static/kalshi-perps-live.js?v=0d0d0d']);
  });

  test(`${name}: Funds draws its figures before its own files load, and mounts the perps box once its script is in`, async () => {
    const funds = {kalshi: {connected: false}, kalshi_dev: {connected: false}, demo: {capital: 1000, equity: 1001, realized: 1}, paper: {cash: 1000, ledger: []}};
    const fetchImpl = (path) => {
      if (path === '/api/funds') return response(funds);
      throw new Error('Unexpected offline request: ' + path);
    };
    const f = frontend({fetchImpl});
    const boot = f.document.createElement('div');
    boot.id = 'tau-boot'; boot.dataset.pageAssets = 'funds:/static/kalshi-perps-live.css?v=0c0c0c funds:/static/kalshi-perps-live.js?v=0d0d0d';
    f.document.body.appendChild(boot);
    const head = [];
    f.document.head = {appendChild: (el) => head.push(el)};
    f.document.querySelectorAll = () => [];
    f.S.me.perps_live_available = true;
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    assert.match(f.root.querySelector('#ffigs').innerHTML, /Paper balance/);
    const box = f.root.querySelector('#kalshi-perps-live');
    assert.ok(box, 'the perps box is in place');
    assert.equal(head.length, 0, 'its files wait for the figures to paint');
    f.elapse(16); f.elapse(0); await settle();
    assert.deepEqual(head.map((el) => el.src || el.href), ['/static/kalshi-perps-live.css?v=0c0c0c', '/static/kalshi-perps-live.js?v=0d0d0d']);
    const mounts = [];
    f.window.TAU_PERPS_LIVE = {mount: (host, opts) => { mounts.push([host, typeof opts.api]); return {destroy() {}}; }};
    head[0].onload(); head[1].onload(); await settle();
    assert.deepEqual(mounts, [[box, 'function']], 'mounted once, in its box, with the page’s api');
    assert.ok(f.S.perps);
    // Moved on before they arrive: nothing mounts over the next page.
    const g = frontend({fetchImpl});
    const gb = g.document.createElement('div');
    gb.id = 'tau-boot'; gb.dataset.pageAssets = 'funds:/static/kalshi-perps-live.js?v=0d0d0d';
    g.document.body.appendChild(gb);
    const gh = [];
    g.document.head = {appendChild: (el) => gh.push(el)};
    g.document.querySelectorAll = () => [];
    g.S.me.perps_live_available = true;
    await g.viewFunds(); await settle(); g.elapse(16); g.elapse(0); await settle();
    g.S.gen++;
    const late = [];
    g.window.TAU_PERPS_LIVE = {mount: () => { late.push(1); return {destroy() {}}; }};
    gh[0].onload(); await settle();
    assert.deepEqual(late, []);
  });

  test(`${name}: the idle prefetch takes a page's own files too, except those already on the page`, async () => {
    const {f, head, boot} = page('strategies:222bbb,funds:333ccc');
    ownFiles(boot, f, 'funds:/static/kalshi-perps-live.js?v=0d0d0d funds:/static/broker-connections.js?v=0e0e0e', ['/static/broker-connections.js?v=0e0e0e']);
    delete f.PAGES.funds;
    f.PAGES.strategies = {viewStrategies: () => {}};
    f.location.pathname = '/strategies';
    await f.render(); await settle(); f.elapse(3000);
    assert.deepEqual(head.map((l) => [l.tag, l.rel, l.href]), [
      ['link', 'prefetch', `/static/${prefix}funds.js?v=333ccc`], ['link', 'prefetch', '/static/kalshi-perps-live.js?v=0d0d0d']]);
  });

  // The pill on a page whose shell names the panel file's version, with the file not run yet.
  const pill = () => {
    const store = new Map();
    const {f, head, reports} = page('research:1a2b3c,autopilot:9f8e7d', {storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response({messages: [], agent_busy: false});
      if (path === '/api/models') return response({models: [], default: ''});
      throw new Error('Unexpected offline request: ' + path);
    }});
    const panel = f.PAGES.autopilot;
    delete f.PAGES.autopilot;
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7, autopilot: false}};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, f.S.ap);
    assert.ok(box.querySelector('.apf-pill'));
    assert.equal(head.length, 0, 'the pill needs no file');
    return {f, head, reports, box, store, panel, open: () => box.querySelector('.apf-pill').onclick({}), close: () => box.querySelector('.apf-x').onclick({})};
  };

  test(`${name}: the autopilot panel's file is fetched the first time the panel opens, once`, async () => {
    const {f, head, reports, box, panel, open, close} = pill();
    open(); await flush();
    assert.deepEqual(head.map((s) => [s.tag, s.src]), [['script', `/static/page-autopilot.js?v=9f8e7d`]]);
    // Meanwhile the panel's head (its label, and the close button that takes focus) over a skeleton.
    assert.ok(box.querySelector('.apf-x') && box.querySelector('.skeleton'));
    assert.match(box.className, /\bopen\b/);
    assert.equal(box.querySelector('#apf-composer'), null);
    f.renderAutopilot(box, f.S.ap); await flush();  // the status poll's repaint while the file is on its way
    assert.equal(head.length, 1, 'one fetch');
    f.PAGES.autopilot = panel; head[0].onload(); await settle();
    assert.ok(box.querySelector('#apf-composer') && box.querySelector('#apf-messages'), 'the panel draws once its file has run');
    assert.equal(box.querySelector('.skeleton'), null);
    // Closed and opened again: drawn from the file already in, no second fetch.
    close(); assert.ok(box.querySelector('.apf-pill'));
    open(); await settle();
    assert.ok(box.querySelector('#apf-composer'));
    assert.equal(head.length, 1);
    assert.deepEqual(reports, []);
  });

  test(`${name}: an autopilot panel file that doesn't arrive says so in the panel, and Try again fetches it afresh`, async () => {
    const {f, head, reports, box, panel, open} = pill();
    open(); await flush();
    head[0].onerror(); await settle();
    assert.ok(box.querySelector('.load-fail'), 'the failure is in the panel');
    assert.match(box.querySelector('.apf-top').innerHTML, /The autopilot panel didn\u2019t load\. Check your connection and try again\./);
    assert.ok(box.querySelector('.apf-x'), 'and it still closes');
    assert.deepEqual(reports, [['api', `GET /static/page-autopilot.js did not load`]]);
    box.querySelector('[data-retry]').onclick(); await flush();
    assert.equal(head.length, 2);
    assert.equal(head[1].src, head[0].src);
    f.PAGES.autopilot = panel; head[1].onload(); await settle();
    assert.ok(box.querySelector('#apf-composer'));
    assert.equal(box.querySelector('.load-fail'), null);
  });

  test(`${name}: an autopilot panel closed before its file arrives stays closed`, async () => {
    const {f, head, box, store, panel, open, close} = pill();
    open(); await flush();
    close();
    assert.equal(store.get('tau_ap_open'), '0');
    f.PAGES.autopilot = panel; head[0].onload(); await settle();
    assert.ok(box.querySelector('.apf-pill'));
    assert.equal(box.querySelector('#apf-composer'), null);
  });
}
