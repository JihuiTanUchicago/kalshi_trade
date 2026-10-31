// Strategies list (/strategies) cases, run against each bundle's offline DOM/transport harness.
import assert from './assert_text.mjs';
import {test} from 'node:test';
import {bundleSource} from './bundle_source.mjs';

// The bundles' separator (SEP in app.js and app.meridian.js; test_separator_line_start.mjs).
const SEP = ' · ';
// Text as a reader sees it: no tags, entities read, the money word joiner gone.
const plain = (html) => html.replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').replace(/⁠/g, '');

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

  test(`${name}: "Later-period P&L" sorts the whole list server-side and survives a reload`, async () => {
    const f = frontend({fetchImpl: () => response(listOf(2))});
    f.location.pathname = '/strategies'; f.location.search = '?status=&sort=best';
    await f.viewStrategies(); await flush();
    const sel = f.root.querySelector('#strat-sort');
    // It says what it sorts by: the backtest P&L after the split date, which is held out for a strategy with a
    // gatekeeper record and the later period that picked it for one without (passed with no record, backtest
    // only). "P&L on data it never saw" was untrue of the second kind, and "Best on unseen data" never said best at what.
    const html = f.root.innerHTML;
    assert.match(html, /<option value="best" selected>Later-period P&amp;L<\/option>/);
    assert.doesNotMatch(html, /Best on unseen data|data it never saw<\/option>/);
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

  test(`${name}: the pass rate is left out under the Deployed toggle, where it could only read 100%`, async () => {
    const figs = async (search, counts) => {
      const f = frontend({fetchImpl: () => response({...listOf(2), counts})});
      f.location.pathname = '/strategies'; f.location.search = search;
      await f.viewStrategies(); await flush();
      const passrate = f.root.querySelector('#strategy-passrate');  // Meridian's summary line
      return f.root.querySelector('#sfigs').innerHTML + (passrate ? ' | ' + passrate.textContent : '');
    };
    const on = await figs('?status=&deployed=1', {total: 5, passed: 5, deployed: 5});
    assert.doesNotMatch(on, /100\.0%/); assert.match(on, /not with Deployed on: only passed strategies deploy/);
    const off = await figs('?status=', {total: 56, passed: 16, failed: 19, rejected: 14, deployed: 5});
    assert.match(off, /28\.6%/); assert.doesNotMatch(off, /not with Deployed on/);
    // Walk 2026-10-27: it says what it is a rate of. Research's rate is of every idea tested (most never become a
    // strategy), and one account read 8.6% there and 12.0% here with nothing saying why.
    assert.match(off, /of the 56 strategies here/); assert.doesNotMatch(on, /strategies here/);
    assert.match(await figs('?status=', {total: 1, passed: 1}), /of the 1 strategy here/);
    // Nothing passed yet is a 0% rate, not a blank.
    assert.match(await figs('?status=', {total: 4, rejected: 4}), /0\.0%/);
  });

  test(`${name}: the ideas-tested column says what it counts: "Ideas tested", the session's count, never "Tried 1 of 18"`, async () => {
    // Walk 2026-10-27: Tau's column read "Tried" over "1 of 18", which said neither what was tried nor where;
    // Meridian's reads "Ideas tested" over 18.
    const f = frontend({fetchImpl: () => response(listOf(2))});
    const cell = (html) => (html.match(/<td[^>]*data-lab="Ideas tested"[^>]*>([^<]*)<\/td>/) || [])[1];
    const html = row(f, {hypotheses_tried: 18});
    assert.equal(cell(html), '18');
    assert.doesNotMatch(html, /data-lab="Tried"|1 of 18/);
    assert.equal(cell(row(f, {hypotheses_tried: null, parent_id: 3})), 'Adjustment');
    f.location.pathname = '/strategies'; f.location.search = '?status=';
    await f.viewStrategies(); await flush();
    const head = f.root.querySelector('.t-strat thead').innerHTML;
    assert.match(head, /<th class="num" title="Every idea[^"]*session[^"]*">Ideas tested<\/th>/);
    assert.doesNotMatch(head, />Tried</);
    f.clearTimers();
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

  test(`${name}: a row stamps what its page says: Missed final test or Held back, never Passed or Void`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const stamp = html => (html.match(/data-lab="Status"><span class="mk[^"]*">([^<]*)<\/span>/) || [])[1];
    const pnl = html => html.slice(html.indexOf('data-lab="Backtest P&amp;L'), html.indexOf('data-lab="Trades"'));
    const oos = {pnl: 3.1, trades: 40, win_rate: 0.6};
    assert.equal(stamp(row(f, {status: 'passed', out_of_sample: oos})), 'Passed');
    const missed = row(f, {status: 'passed', verdict: 'missed_final', out_of_sample: oos});
    assert.equal(stamp(missed), 'Missed final test');
    // Its unseen-data gain is muted, as a Void one's is: the final test it missed is the evidence that counts.
    assert.match(pnl(missed), /pnl-nopass/); assert.match(pnl(missed), /missed the final test/);
    const held = row(f, {status: 'passed', verdict: 'held_back', out_of_sample: oos});
    assert.equal(stamp(held), 'Held back'); assert.match(held, /<span class="mk quiet">Held back<\/span>/);
    assert.doesNotMatch(pnl(held), /pnl-nopass/);
    // A probation strategy held back after passing on paper no longer reads Void.
    assert.equal(stamp(row(f, {status: 'failed', verdict: 'held_back', out_of_sample: oos})), 'Held back');
    assert.equal(stamp(row(f, {status: 'failed', out_of_sample: oos})), 'Void');
    // A verdict the page doesn't know keeps the status.
    assert.equal(stamp(row(f, {status: 'passed', verdict: '<b>x</b>'})), 'Passed');
  });

  test(`${name}: the chips and figures count a pass a later check left uncleared apart, and bulk deploy leaves it out`, async () => {
    const oos = {pnl: 3.1, trades: 40, win_rate: 0.6};
    const list = [detailStrategy({id: 61, title: 'Cleared', status: 'passed', out_of_sample: oos}),
      detailStrategy({id: 62, title: 'Missed', status: 'passed', verdict: 'missed_final', out_of_sample: oos}),
      detailStrategy({id: 63, title: 'Held', status: 'passed', verdict: 'held_back', out_of_sample: oos})];
    const counts = {total: 9, passed: 1, not_cleared: 2, failed: 4, rejected: 2, deployed: 0};
    const open = async (search, c = counts) => {
      const f = frontend({fetchImpl: () => response({counts: c, matched: 3, pages: 1, strategies: list})});
      f.location.pathname = '/strategies'; f.location.search = search;
      await f.viewStrategies(); await flush();
      return f;
    };
    let f = await open('?status=');
    const chips = f.root.querySelectorAll('[data-f="status"]');
    const chip = v => chips.find(b => b.dataset.v === v);
    assert.equal(chip('passed').textContent, 'Passed (1)');
    assert.equal(chip('not_cleared').textContent, 'Not cleared (2)'); assert.equal(chip('not_cleared').hidden, false);
    assert.equal(chip('').textContent, 'Kept (3)');  // the uncleared passes are still kept, not void
    const figs = f.root.querySelector('#sfigs').innerHTML;
    assert.match(figs, /Passed[\s\S]*?<span class="fig ">1<\/span><\/dd><dd class="sub-fig">2 more passed but weren’t cleared to trade<\/dd>/);
    assert.match(figs, /11\.1%/);  // the pass rate counts the one true pass of 9
    const one = (await open('?status=', {...counts, passed: 2, not_cleared: 1})).root.querySelector('#sfigs').innerHTML;
    assert.match(one, /1 more passed but wasn’t cleared to trade/);
    // Bulk deploy ticks only the true pass; the others' rows say why on their own pages.
    const picks = f.root.querySelectorAll('.pick');
    assert.deepEqual(picks.map(p => p.dataset.id), ['61']);
    const pickable = s => /class="pick"/.test(f.strategySlip(s, null, {pick: true}));
    assert.deepEqual(list.map(pickable), [true, false, false]);
    // A probation strategy held back on paper (stored Void) was never offered, and still isn't.
    assert.equal(pickable({...list[2], status: 'failed'}), false);
    // Its chip filters on the server, and rides in the URL like the others.
    chip('not_cleared').onclick(); await flush();
    assert.equal(f.navigations.at(-1), '/strategies?status=not_cleared');
    f = await open('?status=not_cleared');
    const asked = f.requests.filter(({path}) => path.startsWith('/api/strategies?')).map(({path}) => new URLSearchParams(path.split('?')[1]));
    assert.equal(asked.at(-1).get('status'), 'not_cleared');
    assert.equal(f.root.querySelectorAll('[data-f="status"]').find(b => b.dataset.v === 'not_cleared').getAttribute('aria-pressed'), 'true');
    // None uncleared: no chip, and the Passed figure stands alone.
    f = await open('?status=', {total: 5, passed: 2, failed: 3, deployed: 0});
    assert.equal(f.root.querySelectorAll('[data-f="status"]').find(b => b.dataset.v === 'not_cleared').hidden, true);
    assert.doesNotMatch(f.root.querySelector('#sfigs').innerHTML, /cleared to trade/);
  });

  test(`${name}: a row says what its removed deployments made, each book on its own line`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const html = row(f, {deployed: false, past: {paper: {pnl: -13.56, trades: 9, deployments: 1}, demo: {pnl: 0, trades: 0, deployments: 1}}});
    assert.match(html, /Removed from paper: <span class="[^"]*">−\$13\.56<\/span> · 9 trades/);
    assert.match(html, /Removed from demo: no closed trades/);
    assert.ok(html.indexOf('Removed from paper') < html.indexOf('Removed from demo'));
    // Beside an active record it stays apart: never added into "since deploying".
    const both = row(f, {deployed: true, books: ['paper'], real: {pnl: 4, trades: 2, open: 0, mode: 'paper'}, past: {paper: {pnl: 2.25, trades: 4, deployments: 1}}});
    assert.match(both, /\+\$4\.00<\/span> on paper since deploying · 2 trades/);
    assert.match(both, /Removed from paper: <span class="[^"]*">\+\$2\.25<\/span> · 4 trades/);
    assert.doesNotMatch(both, /\$6\.25/);
    assert.doesNotMatch(row(f, {}), /Removed from/);
    // A research-only strategy never shows a book record, even if one leaks in.
    assert.doesNotMatch(row(f, {kind: 'code', research_only: true, past: {paper: {pnl: 1, trades: 1}}}), /Removed from/);
  });

  test(`${name}: a removed paper book says how many of its trades were instant fills, as the track record leaves them out`, () => {
    // Walk 2026-10-27: "Removed from paper: +$0.75 · 3 trades" said nothing of the instant fills among them, which the
    // track record leaves out. The server's past.paper.instant_fills says how many; demo never carries one.
    const f = frontend({fetchImpl: () => response({})});
    const fig = (paper, demo) => row(f, {deployed: false, past: {paper, ...(demo ? {demo} : {})}});
    assert.match(fig({pnl: 0.75, trades: 3, deployments: 1, instant_fills: 1}),
      /Removed from paper: <span class="[^"]*">\+\$0\.75<\/span>\u00a0· 3 trades, 1 of them an instant fill, left out of the track record</);
    assert.match(fig({pnl: 0.75, trades: 3, deployments: 1, instant_fills: 2}), /3 trades, 2 of them instant fills, left out of the track record</);
    assert.match(fig({pnl: 0.75, trades: 2, deployments: 1, instant_fills: 2}), /2 trades, all instant fills, left out of the track record</);
    assert.match(fig({pnl: 0.75, trades: 1, deployments: 1, instant_fills: 1}), /1 trade, an instant fill, left out of the track record</);
    assert.doesNotMatch(fig({pnl: 0.75, trades: 3, deployments: 1}), /instant/);
    assert.doesNotMatch(fig({pnl: 0, trades: 0, deployments: 1}, {pnl: 1, trades: 2, deployments: 1, instant_fills: 2}), /instant/);
  });

  // Walk 2026-10-27: a strategy whose only paper trades were instant fills read "+$3.80 on paper since deploying ·
  // 2 trades" here, while the track record gave it a row saying all its trades were instant fills, left out of it.
  test(`${name}: a paper row whose trades were all instant fills says so, as the track record does`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const real = {pnl: 3.8, trades: 2, open: 0, mode: 'paper', instant_only: true};
    const html = row(f, {deployed: true, books: ['paper'], real});
    assert.match(html, /All 2 of its trades were instant fills, left out of the track record · <span class="[^"]*">\+\$3\.80<\/span> on paper · after Kalshi fees and the spread/);
    assert.doesNotMatch(html, /since deploying/);
    assert.match(row(f, {deployed: true, books: ['paper'], real: {...real, trades: 1}}), /Its only trade was an instant fill, left out of the track record/);
    // A demo book beside it keeps its own line, never added in.
    const demo = row(f, {deployed: true, books: ['paper', 'demo'], real: {...real, demo: {pnl: 0.5, trades: 1, open: 0}}});
    assert.match(demo, /Demo: <span class="[^"]*">\+\$0\.50<\/span> · 1 trade/);
    assert.doesNotMatch(demo, /\$4\.30/);
    // Unflagged, or with no closed trade yet, the row reads as before.
    assert.match(row(f, {deployed: true, books: ['paper'], real: {...real, instant_only: false}}), /\+\$3\.80<\/span> on paper since deploying · 2 trades/);
    assert.match(row(f, {deployed: true, books: ['paper'], real: {...real, trades: 0, pnl: 0}}), /No closed paper trades yet/);
  });

  // Walk 2026-10-27: a strategy whose paper trades were only partly instant fills still read "+$1.30 on paper since
  // deploying · 2 trades", while the track record counted 1 trade and said 1 instant fill was left out.
  test(`${name}: a row's figures and market end each line on "·", never start one with it`, () => {
    // Walk 2026-10-27, 390px and 1280px: "· +$3.80 on paper", "· 3 trades, 1 of them an instant fill" and "· Momentum"
    // began lines. Each separator takes a no-break space before its "·" and a plain one after.
    const f = frontend({fetchImpl: () => response({})});
    const rows = [row(f, {deployed: true, books: ['paper'], real: {pnl: 3.8, trades: 2, open: 0, mode: 'paper', instant_only: true, instant_fills: 2}}),
      row(f, {deployed: true, books: ['paper', 'demo'], real: {pnl: 1.3, trades: 2, open: 0, mode: 'paper', instant_fills: 1, demo: {pnl: 0.5, trades: 1, open: 0}},
        past: {paper: {pnl: 0.75, trades: 3, deployments: 1, instant_fills: 1}, demo: {pnl: 1, trades: 1, deployments: 1}}})];
    for (const html of rows) {
      const figs = [...html.matchAll(/<div class="sub-fig real-fig[^"]*">([\s\S]*?)<\/div>/g)].map((m) => m[1]);
      const market = html.match(/<td data-lab="Market"><span class="tick">([^<]*)</)[1];
      assert.ok(figs.length && figs.every((t) => t.includes(' · ') && !/ ·/.test(t)), figs.join('\n'));
      assert.ok(market.includes(' · ') && !/ ·/.test(market), market);
    }
  });

  test(`${name}: a paper row whose trades were partly instant fills says how many, as the track record does`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const real = {pnl: 1.3, trades: 2, open: 0, mode: 'paper', instant_fills: 1};
    const html = row(f, {deployed: true, books: ['paper'], real});
    assert.match(html, /\+\$1\.30<\/span> on paper since deploying\s·\s2 trades, 1 of them an instant fill, left out of the track record\s·\safter Kalshi fees and the spread/);
    assert.match(row(f, {deployed: true, books: ['paper'], real: {...real, trades: 5, instant_fills: 3}}), /5 trades, 3 of them instant fills, left out of the track record/);
    // All of them: the instant-only line, unchanged. A demo book beside it is never counted, nor added in.
    assert.match(row(f, {deployed: true, books: ['paper'], real: {...real, instant_fills: 2, instant_only: true}}), /All 2 of its trades were instant fills/);
    const demo = row(f, {deployed: true, books: ['paper', 'demo'], real: {...real, demo: {pnl: 0.5, trades: 1, open: 0}}});
    assert.match(demo, /Demo: <span class="[^"]*">\+\$0\.50<\/span>\s·\s1 trade\s·\safter Kalshi fees/);
    assert.doesNotMatch(demo, /\$1\.80/);
    // A live or demo row never carries it, even if one leaks in.
    assert.doesNotMatch(row(f, {deployed: true, books: ['demo'], real: {...real, mode: 'demo'}}), /instant/);
  });

  // A backtest-only strategy comes from the old loose gate: its out_of_sample is the backtest's later slice, the one that
  // gate picked it on, so the list says "later-period" from its status alone, as its page does (#590), never "unseen".
  test(`${name}: a backtest-only row's backtest figure is later-period, not unseen`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const oos = {pnl: 6.2, trades: 40, win_rate: 0.61, days: 30};
    const bt = row(f, {status: 'backtest-only', out_of_sample: oos});
    assert.match(bt, /later-period P&amp;L over 30 days after the split date, which picked it\u00a0· not\u00a0held\u00a0out/);
    assert.doesNotMatch(bt, /unseen/);
    assert.match(row(f, {status: 'passed', out_of_sample: oos}), /later-period P&amp;L over 30 days after the split date\u00a0· unseen\u00a0data/);
    // With only in-sample figures, it says so, as before.
    assert.match(row(f, {status: 'backtest-only', out_of_sample: null, in_sample: {pnl: 3, trades: 9, days: 60}}), /on the history it searched over 60 days/);
  });

  // A passed strategy the server found no gatekeeper record for (no_gatekeeper_record, from the list's own reads) comes
  // from the old loose gate too: its page says "Later-period P&L" (#590), and so does its row now.
  test(`${name}: a passed row with no gatekeeper record says later-period, not unseen`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const oos = {pnl: 6.2, trades: 40, win_rate: 0.61, days: 30};
    const none = row(f, {status: 'passed', no_gatekeeper_record: true, out_of_sample: oos});
    assert.match(none, /later-period P&amp;L over 30 days after the split date, which picked it\u00a0· not\u00a0held\u00a0out/);
    assert.doesNotMatch(none, /unseen/);
    assert.match(row(f, {status: 'passed', no_gatekeeper_record: false, out_of_sample: oos}), /later-period P&amp;L over 30 days after the split date\u00a0· unseen\u00a0data/);
    assert.match(row(f, {status: 'passed', no_gatekeeper_record: true, out_of_sample: null, in_sample: {pnl: 3, trades: 9, days: 60}}),
      /on the history it searched over 60 days/);
  });

  // The first version's simple backtest stored strategies as Void (failed) with no gatekeeper record. Their rows said
  // "unseen data": the server flags them now (no_gatekeeper_record, from the list's own read), and they say "not held
  // out" as a flagged pass does, without "which picked it" (nothing picked a void one).
  test(`${name}: a Void row with no gatekeeper record says not held out, not unseen data`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const oos = {pnl: -1.5, trades: 40, win_rate: 0.41, days: 9};
    const line = btLine(row(f, {status: 'failed', no_gatekeeper_record: true, out_of_sample: oos}));
    assert.equal(line.long, `later-period P&amp;L over 9 days after the split date · not held out${SEP}did not pass`);
    assert.equal(line.short, `later period${SEP}9 days${SEP}not held out${SEP}did not pass`);
    assert.doesNotMatch(line.title + line.long + line.short, /unseen|picked/);
    // A Void row with its record (the gatekeeper's inconclusive verdict) keeps "unseen data".
    const held = btLine(row(f, {status: 'failed', out_of_sample: oos}));
    assert.equal(held.long, `later-period P&amp;L over 9 days after the split date · unseen data${SEP}did not pass`);
  });

  // They count under the Void chip (it lists every void row) but never under "Void on unseen data": the summary takes
  // the server's failed_no_record off, and its note counts them, as Passed's counts the ones not cleared.
  test(`${name}: "Void on unseen data" leaves out the void ones with no gatekeeper record and says how many`, async () => {
    const open = async (counts) => {
      const f = frontend({fetchImpl: () => response({...listOf(2), counts})});
      f.location.pathname = '/strategies'; f.location.search = '?status=';
      await f.viewStrategies(); await flush();
      return f;
    };
    const f = await open({total: 20, passed: 5, failed: 9, failed_no_record: 3, rejected: 6});
    const figs = f.root.querySelector('#sfigs').innerHTML;
    assert.match(figs, /data-glo="void"[\s\S]*?<span class="fig ">6<\/span><\/dd><dd class="sub-fig">3 more were void on a backtest that wasn’t held out<\/dd>/);
    assert.match(figs, /25\.0%/);  // the pass rate is of every strategy here, as before
    const chip = f.root.querySelectorAll('[data-f="status"]').find((b) => b.dataset.v === 'failed');
    assert.equal(chip.textContent, 'Void (9)');
    const one = (await open({total: 4, passed: 1, failed: 2, failed_no_record: 1})).root.querySelector('#sfigs').innerHTML;
    assert.match(one, /<span class="fig ">1<\/span><\/dd><dd class="sub-fig">1 more was void on a backtest that wasn’t held out<\/dd>/);
    // With none (every account whose voids all have a record, and a server that doesn't send it) nothing changes.
    const none = (await open({total: 4, passed: 1, failed: 2})).root.querySelector('#sfigs').innerHTML;
    assert.match(none, /data-glo="void"[\s\S]*?<span class="fig ">2<\/span><\/dd>/);
    assert.doesNotMatch(none, /void on a backtest/);
  });

  // A row's Backtest P&L line: its full sentence (the hover, and what a screen reader says) and a phone's short form.
  const btLine = (html) => {
    const m = html.match(/<div class="sub-fig bt-sub" title="([^"]*)"><span class="bt-long">([^<]*)<\/span><span class="bt-short" aria-hidden="true">([^<]*)<\/span><\/div>/);
    return m ? {title: m[1], long: m[2], short: m[3]} : null;
  };

  // Walk 2026-10-28 at 390px, both themes: "later-period P&L over 9 days after the split date, which picked it: not held
  // out" ran about five lines in its third of the card, right under "BACKTEST P&L". And a held-out row said "on unseen
  // data" under a sort named "Later-period P&L", though its figure is the later period too (held out).
  test(`${name}: a phone's Backtest P&L line is short, says the same as the sort, and keeps the full sentence as its hover`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const oos = {pnl: 6.2, trades: 40, win_rate: 0.61, days: 9};
    const later = btLine(row(f, {status: 'backtest-only', out_of_sample: oos}));
    const held = btLine(row(f, {status: 'passed', no_gatekeeper_record: false, out_of_sample: oos}));
    const searched = btLine(row(f, {status: 'passed', out_of_sample: null, in_sample: {pnl: 3, trades: 9, days: 60}}));
    // Desktop's sentences: the later-period one as before, and a held-out one that names the period as the sort does.
    // Their qualifier holds together as the short form's does: a 1280px row broke "· not / held out" (walked 2026-10-28).
    assert.equal(later.long, 'later-period P&amp;L over 9 days after the split date, which picked it\u00a0· not\u00a0held\u00a0out');
    assert.equal(held.long, 'later-period P&amp;L over 9 days after the split date\u00a0· unseen\u00a0data');
    assert.equal(searched.long, 'on the history it searched over 60 days');
    // The phone's three read as one family: which data, over how long, and (for the later period) whether held out.
    assert.equal(later.short, `later\u00a0period${SEP}9\u00a0days${SEP}not\u00a0held\u00a0out`);
    assert.equal(held.short, `later\u00a0period${SEP}9\u00a0days${SEP}unseen\u00a0data`);
    assert.equal(searched.short, `history it searched${SEP}60\u00a0days`);
    for (const l of [later, held, searched]) {
      assert.equal(l.title, l.long);  // the hover is the full sentence
      assert.doesNotMatch(l.short, /P&amp;L|P&L/);  // not "P&L" again right under "BACKTEST P&L"
      assert.ok(plain(l.short).length <= 40, l.short);
    }
    // A verdict word rides on both forms; a day or less, and no stated span, read in words.
    const voidRow = btLine(row(f, {status: 'failed', out_of_sample: {...oos, days: 0.5}}));
    assert.equal(voidRow.short, `later\u00a0period${SEP}under a day${SEP}unseen\u00a0data${SEP}did\u00a0not\u00a0pass`);
    assert.equal(voidRow.long, `later-period P&amp;L in under a day after the split date\u00a0· unseen\u00a0data${SEP}did not pass`);
    assert.equal(btLine(row(f, {status: 'passed', out_of_sample: {...oos, days: null}})).short, `later\u00a0period${SEP}unseen\u00a0data`);
    // No figure: the verdict alone, one line with nothing to shorten.
    assert.match(row(f, {status: 'rejected', out_of_sample: null, in_sample: {}}), /<div class="sub-fig">did not pass<\/div>/);
  });

  test(`${name}: the sort and the glossary name the held-out slice the later period, as a row does`, async () => {
    const f = frontend({fetchImpl: () => response(listOf(2))});
    f.location.pathname = '/strategies'; f.location.search = '?status=&sort=best';
    await f.viewStrategies(); await flush();
    assert.match(f.root.innerHTML, /<option value="best" selected>Later-period P&amp;L<\/option>/);
    const src = bundleSource(name === 'Meridian' ? 'app.meridian.js' : 'app.js');
    // The glossary (#606) defines the sort's own term, and says the held-out slice is a later period too.
    const later = src.match(/\n {4}laterperiod: \['Later-period P&L', '([^']*)'\]/)[1];
    assert.match(later, /after its split date/); assert.match(later, /wasn’t held out/);
    const unseen = src.match(/\n {4}unseen: \['Later-period P&L \(unseen data\)', '([^']*)'\]/)[1];
    assert.match(unseen, /after its split date, on a held-out slice/); assert.doesNotMatch(unseen, /wasn’t held out/);
  });

  // Walk 2026-10-30 ("is the autopilot making money?"): a deployed row led with its backtest figure and kept its paper
  // result at the far end of the Status cell. With the list's Paper P&L column on, the paper money sits beside the
  // backtest's columns, labelled paper and net of fees; demo and live keep their own lines in Status, never added in.
  test(`${name}: a row's paper result since deploying sits in a Paper P&L column beside the backtest, never added to demo or live`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const col = (s) => f.strategySlip(detailStrategy({id: 46, title: 'List fixture', ...s}), null, {paper: true});
    const cell = (html) => (html.match(/<td class="num paper-col[^"]*" data-lab="Paper since deploying">([\s\S]*?)<\/td>/) || [])[1];
    const status = (html) => html.match(/<td class="act st" data-lab="Status">([\s\S]*?)<\/td>/)[1];
    const both = col({deployed: true, books: ['paper', 'demo'], real: {pnl: 3.2, trades: 14, open: 1, mode: 'paper', demo: {pnl: 0.5, trades: 1, open: 0}}});
    // The figure leads, as the backtest cell's does, then what it covers.
    assert.equal(plain(cell(both)), '+$3.20since deploying · 14 trades · after Kalshi fees and the spread');
    assert.match(cell(both), /^<span class="[^"]*">\+\$3\.20<\/span><div class="sub-fig real-fig">since deploying/);
    // Its cell stands right after the backtest's Win column, before Ideas tested.
    const at = (k) => both.indexOf(k);
    assert.ok(at('data-lab="Win"') < at('data-lab="Paper since deploying"') && at('data-lab="Paper since deploying"') < at('data-lab="Ideas tested"'));
    // Status keeps its badge and the demo book's own line; the paper line isn't said twice, and nothing is summed.
    assert.match(status(both), /On paper \+ demo/);
    assert.match(plain(status(both)), /Demo: \+\$0\.50 · 1 trade · after Kalshi fees/);
    assert.doesNotMatch(status(both), /3\.20|on paper since deploying/);
    assert.doesNotMatch(both, /\$3\.70/);
    // A paper book's instant fills ride in the column with it.
    assert.match(cell(col({deployed: true, books: ['paper'], real: {pnl: 1.3, trades: 2, open: 0, mode: 'paper', instant_fills: 1}})),
      /since deploying · 2 trades, 1 of them an instant fill, left out of the track record · after Kalshi fees and the spread/);
    assert.match(plain(cell(col({deployed: true, books: ['paper'], real: {pnl: 3.8, trades: 2, open: 0, mode: 'paper', instant_only: true}}))),
      /^\+\$3\.80All 2 of its trades were instant fills, left out of the track record · after Kalshi fees and the spread$/);
    assert.equal(plain(cell(col({deployed: true, books: ['paper'], real: {pnl: 0, trades: 0, open: 1, mode: 'paper'}}))), 'No closed paper trades yet');
    // Removed from paper: in the column; removed from demo stays in Status, each on its own line.
    const past = col({deployed: false, past: {paper: {pnl: -13.56, trades: 9, deployments: 1}, demo: {pnl: 1, trades: 1, deployments: 1}}});
    assert.match(plain(cell(past)), /^Removed from paper: −\$13\.56 · 9 trades$/);
    assert.match(status(past), /Removed from demo/); assert.doesNotMatch(status(past), /Removed from paper/);
    // A live row's record is its live book alone: live money stays in Status, and the column points to its page.
    const live = col({deployed: true, deploy_live: true, books: ['live', 'paper'], real: {pnl: 2, trades: 3, open: 0, mode: 'live', live: true}});
    assert.match(cell(live), /<a href="\/strategies\/46">Its paper book is on its page<\/a>/);
    assert.doesNotMatch(cell(live), /\$2\.00/); assert.match(status(live), /\+\$2\.00<\/span> on live since deploying/);
    // A demo-only row and a row never deployed: an empty cell (hidden on a phone), demo money in Status alone.
    const demo = col({deployed: true, books: ['demo'], real: {pnl: 2, trades: 1, open: 0, mode: 'demo'}});
    assert.equal(cell(demo), '—'); assert.match(demo, /class="num paper-col nil"/); assert.match(status(demo), /on demo since deploying/);
    assert.equal(cell(col({})), '—');
    // A research-only strategy never shows a book record, even if one leaks in.
    assert.equal(cell(col({kind: 'code', research_only: true, deployed: true, real: {pnl: 1, trades: 1, open: 0, mode: 'paper'}})), '—');
  });

  // Walk 2026-10-30 (live, paper and demo strategies on one list): a live row's record read "+$0.27 since deploying ·
  // 4 trades · after Kalshi fees" beside "+$3.53 on demo since deploying" and a paper column, the one figure on the list
  // that didn't say which money it was. It names its book and says it is real money, as the strategy page does.
  test(`${name}: a live row's since-deploying figure says it is live, real money, as the demo and paper rows name theirs`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = (real) => plain(f.strategySlip(detailStrategy({id: 47, title: 'Live fixture', deployed: true, deploy_live: true, books: ['live'], real}), null, {})).replace(/\u00a0/g, ' ');
    assert.match(row({pnl: 0.27, trades: 4, open: 0, mode: 'live', live: true}), /\+\$0\.27 on live since deploying · 4 trades · real money, after Kalshi fees/);
    assert.match(row({pnl: 0, trades: 0, open: 2, mode: 'live', live: true}), /No closed live trades yet/);
    // Demo and paper keep their own words; nothing calls them real money.
    assert.doesNotMatch(row({pnl: 1, trades: 1, open: 0, mode: 'demo'}), /real money|on live/);
    assert.doesNotMatch(row({pnl: 1, trades: 1, open: 0, mode: 'paper'}), /real money|on live/);
  });

  test(`${name}: the list shows the Paper P&L column only when a row on the page has a paper record, each row a cell under it`, async () => {
    const open = async (strategies) => {
      const f = frontend({fetchImpl: () => response({counts: {total: strategies.length, passed: strategies.length}, matched: strategies.length, pages: 1, strategies})});
      f.location.pathname = '/strategies'; f.location.search = '?status=';
      await f.viewStrategies(); await flush();
      return f.root.querySelector('#slips').innerHTML;
    };
    const shape = (html) => {
      const table = html.match(/<table class="stack t-strat">[\s\S]*?<\/table>/)[0];
      const head = (table.match(/<thead>[\s\S]*?<\/thead>/)[0].match(/<th[ >]/g) || []).length;
      const rows = (table.match(/<tbody>[\s\S]*?<\/tbody>/)[0].match(/<tr[ >][\s\S]*?<\/tr>/g) || []).map((r) => (r.match(/<td[ >]/g) || []).length);
      return {head, rows};
    };
    const on = await open([detailStrategy({id: 60, title: 'On paper', deployed: true, books: ['paper'], real: {pnl: 3.2, trades: 14, open: 0, mode: 'paper'}}),
      detailStrategy({id: 61, title: 'Not deployed'})]);
    assert.match(on, /<th class="num" title="What it has made on paper \(pretend money\) since you deployed it, after Kalshi fees and the spread\. Never added to its demo or live money\.">Paper P&amp;L<\/th>/);
    const s1 = shape(on);
    assert.ok(s1.rows.length === 2 && s1.rows.every((n) => n === s1.head), JSON.stringify(s1));
    // A row removed from paper is a paper record too.
    assert.match(await open([detailStrategy({id: 62, title: 'Removed', past: {paper: {pnl: 1, trades: 2, deployments: 1}}})]), /Paper P&amp;L<\/th>/);
    // No paper record on the page: no column of dashes, and the rows match the head.
    const off = await open([detailStrategy({id: 61, title: 'Not deployed'}), detailStrategy({id: 63, title: 'Demo only', deployed: true, books: ['demo'],
      real: {pnl: 2, trades: 1, open: 0, mode: 'demo'}})]);
    assert.doesNotMatch(off, /Paper P&amp;L|paper-col/);
    const s2 = shape(off);
    assert.ok(s2.rows.length === 2 && s2.rows.every((n) => n === s2.head), JSON.stringify(s2));
  });
  test(`${name}: each status chip counts the rows it lists, the example's included, grouped in thousands`, async () => {
    // Walked 2026-10-31: "Rejected (1)" opened on three rows (the two seeded example strategies are out of the
    // figures but listed), and a big account's chips read "Kept (1234)" beside "1,234" figures.
    const counts = {total: 1301, passed: 1234, failed: 50, rejected: 15, 'backtest-only': 2, deployed: 1002, examples: {rejected: 2, passed: 1}};
    const f = frontend({fetchImpl: () => response({counts, matched: 1237, pages: 25, strategies: [detailStrategy({id: 60, title: 'One'})]})});
    f.location.pathname = '/strategies'; f.location.search = '?status=';
    await f.viewStrategies(); await flush();
    const chip = (v) => f.root.querySelectorAll('[data-f="status"]').find((b) => b.dataset.v === v).textContent;
    assert.equal(chip(''), 'Kept (1,237)');  // 1,236 kept of the account's own and the one example pass
    assert.equal(chip('passed'), 'Passed (1,235)');
    assert.equal(chip('rejected'), 'Rejected (17)');
    assert.equal(chip('failed'), 'Void (50)');
    assert.equal(f.root.querySelector('[data-toggle="deployed"]').textContent, 'Deployed (1,002)');
    // The figures above still leave the example out.
    assert.match(f.root.querySelector('#sfigs').innerHTML, /1,234/);
    assert.doesNotMatch(f.root.querySelector('#sfigs').innerHTML, /1,235/);
  });

  test(`${name}: a new account's figures say they leave the example out, beside chips that list it`, async () => {
    // First-hour walk 2026-10-31: "Rejected in testing 0" (Meridian: "100.0% pass rate, of the 1 strategy here") sat over a
    // "Rejected (2)" chip, the two seeded example strategies, with nothing saying why the two disagreed.
    const counts = {total: 1, passed: 1, failed: 0, rejected: 0, 'backtest-only': 0, deployed: 1, examples: {rejected: 2}};
    const f = frontend({fetchImpl: () => response({counts, matched: 1, pages: 1, strategies: [detailStrategy({id: 60, title: 'One'})]})});
    f.location.pathname = '/strategies'; f.location.search = '?status=';
    await f.viewStrategies(); await flush();
    assert.equal(f.root.querySelectorAll('[data-f="status"]').find((b) => b.dataset.v === 'rejected').textContent, 'Rejected (2)');
    const figs = f.root.querySelector('#sfigs').textContent;
    assert.match(figs, /Rejected in testing[\s\S]*0\s*not counting the example’s 2/);
    assert.doesNotMatch(figs, /Passed[^R]*not counting|Void on unseen data[^R]*not counting/);
    if (name === 'Meridian') assert.equal(f.root.querySelector('#strategy-passrate').textContent, '100.0% pass rate, of the 1 strategy here, not counting the example’s 2');
    // An account with no example rows reads as before.
    const g = frontend({fetchImpl: () => response({counts: {...counts, examples: {}}, matched: 1, pages: 1, strategies: [detailStrategy({id: 60, title: 'One'})]})});
    g.location.pathname = '/strategies'; g.location.search = '?status=';
    await g.viewStrategies(); await flush();
    assert.doesNotMatch(g.root.querySelector('#sfigs').textContent, /example/);
    if (name === 'Meridian') assert.equal(g.root.querySelector('#strategy-passrate').textContent, '100.0% pass rate, of the 1 strategy here');
  });

  test(`${name}: a search, market or Deployed filter that matches nothing says so, not a new account's empty list`, async () => {
    // Walked 2026-10-31: the counts are narrowed by the search too, so a search for "zzz" read total 0 and the list said
    // "Autopilot is on. The strategies it finds will land here" over an account of 74 strategies.
    for (const search of ['?status=&q=zzz', '?status=&market=nba_game', '?status=&deployed=1']) {
      for (const autopilot of [true, false]) {
        const f = frontend({fetchImpl: () => response({counts: {total: 0, deployed: 0, examples: {}}, matched: 0, pages: 0, strategies: []})});
        f.S.me.user.autopilot = autopilot;
        f.location.pathname = '/strategies'; f.location.search = search;
        await f.viewStrategies(); await flush();
        const empty = f.root.querySelector('#slips .empty').innerHTML;
        assert.match(empty, /Try another filter, or clear them\./, search);
        assert.doesNotMatch(empty, /will land here|Start a session|New session|See its research|Go to Research/, search);
        assert.match(empty, /<h2>No matching strategies<\/h2>/);
        f.clearTimers && f.clearTimers();
      }
    }
    // It names what the list is filtered to, in the customer's words (the market's name, never its key; the search as
    // typed, escaped), and Clear filters undoes every filter but keeps the sort, which narrows nothing.
    {
      const f = frontend({fetchImpl: () => response({counts: {total: 0, deployed: 0, examples: {}}, matched: 0, pages: 0, strategies: []})});
      f.location.pathname = '/strategies'; f.location.search = '?status=passed&market=eth15m&q=%3Cb%3Ex&deployed=1&sort=best';
      await f.viewStrategies(); await flush();
      const empty = f.root.querySelector('#slips .empty');
      const said = plain(empty.querySelector('p').innerHTML);
      assert.match(said, /^Nothing matches Passed\u00a0· Deployed\u00a0· ETH [^·]+\u00a0· “&lt;b&gt;x”\. Try another filter, or clear them\.$/);
      assert.doesNotMatch(empty.innerHTML, /eth15m|<b>x/);
      empty.querySelector('[data-clear-filters]').onclick(); await flush();
      assert.equal(f.navigations.at(-1), '/strategies?sort=best&status=');
      f.clearTimers && f.clearTimers();
    }
    for (const search of ['?status=&q=zzz']) {
      for (const autopilot of [false]) {
        const f = frontend({fetchImpl: () => response({counts: {total: 0, deployed: 0, examples: {}}, matched: 0, pages: 0, strategies: []})});
        f.S.me.user.autopilot = autopilot;
        f.location.pathname = '/strategies'; f.location.search = search;
        await f.viewStrategies(); await flush();
        assert.match(f.root.querySelector('#slips .empty').innerHTML, /<p>Nothing matches “zzz”\. Try another filter, or clear them\.<\/p><button class="btn" type="button" data-clear-filters>Clear filters<\/button>/);
        f.clearTimers && f.clearTimers();
      }
    }
    // No filter on and nothing at all is still a new account's list.
    const g = frontend({fetchImpl: () => response({counts: {total: 0}, matched: 0, pages: 0, strategies: []})});
    g.S.me.user.autopilot = true;
    g.location.pathname = '/strategies'; g.location.search = '?status=';
    await g.viewStrategies(); await flush();
    assert.match(g.root.querySelector('#slips .empty').innerHTML, /Autopilot is on\. The strategies it finds will land here\./);
    // Every empty list's heading is an h2 under the page's h1: an h3 skipped a level (axe heading-order, walked 2026-10-31).
    assert.equal(g.root.querySelector('#slips .empty h2').textContent, name === 'Tau' ? 'Nothing here yet' : 'No strategies yet');
    assert.equal(g.root.querySelectorAll('#slips h3').length, 0);
  });

  // Where a keyboard user is left: the fake DOM records focus() (Tau's as `focused`, Meridian's as the document's
  // activeElement).
  const hasFocus = (f, el) => !!el && (el.focused === true || f.document.activeElement === el);

  test(`${name}: Prev and Next hand focus to the new page's first strategy, or to Try again when its read failed`, async () => {
    // Walked 2026-10-31: the new page was drawn over the button that was pressed, and focus fell to the top of the document.
    let fail = false;
    const f = frontend({fetchImpl: path => {
      if (fail) return response({error: 'Something went wrong on our side.'}, 500);
      const page = +new URLSearchParams(path.split('?')[1]).get('page');
      return response({...listOf(120, 3), strategies: [detailStrategy({id: 80 + page, title: 'First on page ' + (page + 1)})]});
    }});
    f.location.pathname = '/strategies'; f.location.search = '?status=';
    await f.viewStrategies(); await flush();
    const first = f.root.querySelector('tbody td.name a');
    assert.equal(hasFocus(f, first), false, 'a page that just opened leaves focus to the router');
    await f.root.querySelector('[data-sp="1"]').onclick(); await flush();
    const now = f.root.querySelector('tbody td.name a');
    assert.equal(now.textContent, 'First on page 2');
    assert.ok(hasFocus(f, now));
    assert.equal(now.focusOptions && now.focusOptions.preventScroll, true);
    fail = true;
    await f.root.querySelector('[data-sp="2"]').onclick(); await flush();
    assert.ok(hasFocus(f, f.root.querySelector('#slips [data-retry]')));
  });

  test(`${name}: bulk deploy's Clear leaves focus on the first box, and a deploy that partly failed still says so after the list reads again`, async () => {
    const rows = [detailStrategy({id: 61, title: 'Lands'}), detailStrategy({id: 62, title: 'Refused'}), detailStrategy({id: 63, title: 'Third'})];
    const f = frontend({fetchImpl: (path, options) => {
      if (path === '/api/deployments' && options && options.method === 'POST') {
        return JSON.parse(options.body).strategy_id === 62 ? response({error: 'This strategy can’t be deployed.'}, 400) : response({id: 900});
      }
      return response({counts: {total: 3, passed: 3}, matched: 3, pages: 1, strategies: rows});
    }});
    f.location.pathname = '/strategies'; f.location.search = '?status=';
    await f.viewStrategies(); await flush();
    const tick = (i) => { const p = f.root.querySelectorAll('.pick')[i]; p.checked = true; p.onchange(); };
    tick(0); tick(1);
    assert.match(f.root.querySelector('#bulkbar').innerHTML, /2 selected/);
    f.root.querySelector('#bulk-clear').onclick();
    assert.equal(f.root.querySelector('#bulkbar').hidden, true);
    assert.ok(hasFocus(f, f.root.querySelectorAll('.pick')[0]), 'Clear hands focus to the first box, not the top of the page');
    // Two picked, one refused: the list reads again to show the one that landed, and the bar keeps what was said.
    tick(0); tick(1);
    const dep = f.root.querySelector('#bulk-dep');
    await dep.onclick({target: dep}); for (let i = 0; i < 4; i++) await flush();
    assert.equal(f.requests.filter(({path, options}) => path === '/api/deployments' && options && options.method === 'POST').length, 2, 'one write each, never again');
    assert.ok(f.requests.filter(({path}) => path.startsWith('/api/strategies?')).length >= 2, 'the list read again');
    const bar = f.root.querySelector('#bulkbar');
    assert.equal(bar.hidden, false);
    assert.equal(plain(bar.innerHTML), '1 deployed · 1 failed: This strategy can’t be deployed.'.replace(' · ', ' · '));
    assert.equal(bar.querySelector('#bulk-dep'), null, 'nothing is picked after the read, so no Deploy button');
    assert.ok(hasFocus(f, bar.querySelector('#bulkflash')), 'focus goes to what it said, not the top of the page');
    // The next pick starts a fresh bar.
    tick(2);
    assert.match(bar.innerHTML, /1 selected/); assert.doesNotMatch(bar.innerHTML, /failed/);
  });

  test(`${name}: emptying the search box with Escape or its clear button lists everything again at once`, async () => {
    // Walked 2026-10-31: those fire no change event until the box loses focus, and the list stayed filtered under an empty box.
    const f = frontend({fetchImpl: () => response(listOf(2))});
    f.location.pathname = '/strategies'; f.location.search = '?status=&q=idea';
    await f.viewStrategies(); await flush();
    const box = f.root.querySelector('#strat-q');
    box.value = ''; box.onsearch(); await flush();
    assert.equal(f.navigations.at(-1), '/strategies?status=');
    // The search event Enter fires beside change asks nothing twice.
    const g = frontend({fetchImpl: () => response(listOf(2))});
    g.location.pathname = '/strategies'; g.location.search = '?status=';
    await g.viewStrategies(); await flush();
    const q = g.root.querySelector('#strat-q');
    q.value = 'fade'; q.onchange(); q.onsearch(); await flush();
    assert.deepEqual(g.navigations, ['/strategies?q=fade&status=']);
  });

  test(`${name}: a row the search found by its thesis shows the thesis, so the match is on screen`, () => {
    // Walked 2026-10-31 in Meridian: the search reads the name and the thesis, and a Meridian row showed only the name.
    const f = frontend({fetchImpl: () => response({})});
    const s = detailStrategy({id: 47, title: 'Fade the close', thesis: 'Late takers **overpay** near the close.'});
    const shown = (q) => /<div class="sub-fig cellwrap">Late takers <b>overpay<\/b> near the close\.<\/div>/.test(f.strategySlip(s, null, {q}));
    assert.equal(shown('overpay'), true);
    // Tau's rows carry the thesis whatever the search; Meridian's only when the name doesn't hold the words.
    assert.equal(shown('FADE'), name === 'Tau');
    assert.equal(shown(''), name === 'Tau');
    assert.equal(shown(undefined), name === 'Tau');
  });
}
