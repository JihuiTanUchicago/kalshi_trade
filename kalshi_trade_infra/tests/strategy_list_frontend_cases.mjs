// Strategies list (/strategies) cases, run against each bundle's offline DOM/transport harness.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const flush = () => new Promise(resolve => setImmediate(resolve));

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

export function strategyListCases({name, frontend, detailStrategy}) {
  const row = (f, s) => f.strategySlip(detailStrategy({id: 46, title: 'List fixture', ...s}), null, {});
  const badge = html => (html.match(/<span class="mk (?:live|dep)">([^<]*)<\/span>/) || [])[1];

  test(`${name}: a deployed row's badge names the books it runs in, not "Deployed"`, () => {
    const f = frontend({fetchImpl: () => response({})});
    assert.equal(badge(row(f, {deployed: true, books: ['paper'], real: {pnl: 1, trades: 1, open: 0, mode: 'paper'}})), 'On paper');
    assert.equal(badge(row(f, {deployed: true, books: ['demo'], real: {pnl: 1, trades: 1, open: 0, mode: 'demo'}})), 'On demo');
    assert.equal(badge(row(f, {deployed: true, books: ['paper', 'demo'], real: {pnl: 1, trades: 1, open: 0, mode: 'paper'}})), 'On paper + demo');
    const live = row(f, {deployed: true, deploy_live: true, books: ['live', 'paper'], real: {pnl: 1, trades: 1, open: 0, mode: 'live', live: true}});
    assert.equal(badge(live), 'Live + paper'); assert.match(live, /<span class="mk live">Live \+ paper<\/span>/);
    // A server that sends no books keeps the old badge rather than guessing a book.
    assert.equal(badge(row(f, {deployed: true, real: {pnl: 1, trades: 1, open: 0}})), 'Deployed');
    assert.equal(badge(row(f, {deployed: false})), undefined);
  });

  const listOf = (n, pages = 1) => ({counts: {total: n, passed: n}, matched: n, pages,
    strategies: Array.from({length: Math.min(n, 2)}, (_, i) => detailStrategy({id: 60 + i, title: 'Sorted ' + i}))});

  test(`${name}: "Best on unseen data" sorts the whole list server-side and survives a reload`, async () => {
    const f = frontend({fetchImpl: () => response(listOf(2))});
    f.location.pathname = '/strategies'; f.location.search = '?status=&sort=best';
    await f.viewStrategies(); await flush();
    const sel = f.root.querySelector('#strat-sort');
    const chosen = s => (s.querySelectorAll('option').find(o => 'selected' in o.attributes) || {attributes: {}}).attributes.value;
    assert.equal(chosen(sel), 'best');  // read back from the URL on a reload
    const asked = f.requests.filter(({path}) => path.startsWith('/api/strategies?')).map(({path}) => new URLSearchParams(path.split('?')[1]));
    assert.equal(asked.at(-1).get('sort'), 'best'); assert.equal(asked.at(-1).get('page'), '0');
    // Back to newest: the choice leaves the URL, which keeps the other filters.
    sel.value = ''; sel.onchange(); await flush();
    assert.ok(f.navigations.includes('/strategies?status='), f.navigations.join(' '));
    // A fresh view with no sort in the URL reads "Newest first" and asks the server for no order.
    const g = frontend({fetchImpl: () => response(listOf(2))});
    g.location.pathname = '/strategies'; g.location.search = '?status=passed&market=btc15m';
    await g.viewStrategies(); await flush();
    assert.equal(chosen(g.root.querySelector('#strat-sort')), '');  // "Newest first" by default
    const sel2 = g.root.querySelector('#strat-sort');
    sel2.value = 'best'; sel2.onchange(); await flush();
    assert.ok(g.navigations.includes('/strategies?status=passed&market=btc15m&sort=best'), g.navigations.join(' '));
  });

  test(`${name}: the page number rides in the URL, so a reload stays on it`, async () => {
    let pages = 3;
    const f = frontend({fetchImpl: path => {
      const page = +new URLSearchParams(path.split('?')[1]).get('page');
      return response(page < pages ? listOf(120, pages) : {...listOf(120, pages), strategies: []});
    }});
    const pageAsked = () => f.requests.filter(({path}) => path.startsWith('/api/strategies?')).map(({path}) => new URLSearchParams(path.split('?')[1]).get('page'));
    f.location.pathname = '/strategies'; f.location.search = '?status=passed&page=2';
    await f.viewStrategies(); await flush();
    assert.equal(pageAsked().at(-1), '1');  // ?page=2 is the second page (0-based to the server)
    assert.match(f.root.querySelector('#slips').innerHTML, /Page 2 of 3/);
    await f.root.querySelector('[data-sp="2"]').onclick(); await flush();
    assert.equal(f.navigations.at(-1), '/strategies?status=passed&page=3');
    assert.equal(pageAsked().at(-1), '2');
    await f.root.querySelector('[data-sp="1"]').onclick(); await flush();
    await f.root.querySelector('[data-sp="0"]').onclick(); await flush();
    assert.equal(f.navigations.at(-1), '/strategies?status=passed');  // page 1 needs no number
    // A remembered page past the end (the list shrank) starts again at the first page.
    pages = 1;
    const g = frontend({fetchImpl: path => {
      const page = +new URLSearchParams(path.split('?')[1]).get('page');
      return response(page < pages ? listOf(2) : {...listOf(2), strategies: []});
    }});
    g.location.pathname = '/strategies'; g.location.search = '?status=&page=4';
    await g.viewStrategies(); await flush(); await flush();
    assert.match(g.root.querySelector('#slips').innerHTML, /Sorted 0/);
    assert.equal(g.navigations.at(-1), '/strategies?status=');
  });

  test(`${name}: a strategy the autopilot found is tagged on its row; the user's own are not`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const tag = /<span class="mk quiet ap-run-tag" title="Found in a research session the autopilot started\.">Autopilot<\/span>/;
    assert.match(row(f, {by_autopilot: true}), tag);
    assert.doesNotMatch(row(f, {}), /ap-run-tag/);
    // The seeded example keeps its own tag only.
    const ex = row(f, {by_autopilot: true, example: true});
    assert.match(ex, /example-tag/); assert.doesNotMatch(ex, /ap-run-tag/);
  });

  test(`${name}: a row says what its removed deployments made, each book on its own line`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const html = row(f, {deployed: false, past: {paper: {pnl: -13.56, trades: 9, deployments: 1}, demo: {pnl: 0, trades: 0, deployments: 1}}});
    assert.match(html, /Removed from paper: <span class="[^"]*">−\$13\.56<\/span> · 9 trades/);
    assert.match(html, /Removed from demo: no closed trades/);
    assert.ok(html.indexOf('Removed from paper') < html.indexOf('Removed from demo'));
    // Beside an active record it stays apart: never added into "since deploying".
    const both = row(f, {deployed: true, books: ['paper'], real: {pnl: 4, trades: 2, open: 0, mode: 'paper'}, past: {paper: {pnl: 2.25, trades: 4, deployments: 1}}});
    assert.match(both, /\+\$4\.00<\/span> on paper since deploying · 2 trades/);
    assert.match(both, /Removed from paper: <span class="[^"]*">\+\$2\.25<\/span> · 4 trades/);
    assert.doesNotMatch(both, /\$6\.25/);
    assert.doesNotMatch(row(f, {}), /Removed from/);
    // A research-only strategy never shows a book record, even if one leaks in.
    assert.doesNotMatch(row(f, {kind: 'code', research_only: true, past: {paper: {pnl: 1, trades: 1}}}), /Removed from/);
  });
}
