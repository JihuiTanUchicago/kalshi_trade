// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the page
// files (app-<name>.js, app.meridian-<name>.js), fetched on first use (pageLoad, pageView).
// - a page whose file isn't in yet shows its skeleton and fetches the file once, by the version the
//   shell names; a file that fails, or doesn't arrive in time, fails its page with Try again, which
//   fetches it afresh, and the page draws once it is in;
// - a file that arrives after the user moved on never draws over the next page;
// - a file from another build that asks for a helper this build doesn't share fails as it runs;
// - after the first page paints, the files not yet in are prefetched once, at the lowest priority.
// The harnesses run every page file up front (bundle_source.mjs); a case takes one out to see it fetched.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

export function pageFileCases({name, frontend, prefix, pagesKey}) {
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
    return {f, head, reports};
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
}
