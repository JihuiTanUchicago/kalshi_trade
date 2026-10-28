// Strategies list (/strategies) cases, run against each bundle's offline DOM/transport harness.
import assert from './assert_text.mjs';
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
    assert.match(bt, /later-period P&amp;L over 30 days after the split date, which picked it: not held out/);
    assert.doesNotMatch(bt, /unseen/);
    assert.match(row(f, {status: 'passed', out_of_sample: oos}), /on unseen data over 30 days/);
    // With only in-sample figures, it says so, as before.
    assert.match(row(f, {status: 'backtest-only', out_of_sample: null, in_sample: {pnl: 3, trades: 9, days: 60}}), /on the history it searched over 60 days/);
  });

  // A passed strategy the server found no gatekeeper record for (no_gatekeeper_record, from the list's own reads) comes
  // from the old loose gate too: its page says "Later-period P&L" (#590), and so does its row now.
  test(`${name}: a passed row with no gatekeeper record says later-period, not unseen`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const oos = {pnl: 6.2, trades: 40, win_rate: 0.61, days: 30};
    const none = row(f, {status: 'passed', no_gatekeeper_record: true, out_of_sample: oos});
    assert.match(none, /later-period P&amp;L over 30 days after the split date, which picked it: not held out/);
    assert.doesNotMatch(none, /unseen/);
    assert.match(row(f, {status: 'passed', no_gatekeeper_record: false, out_of_sample: oos}), /on unseen data over 30 days/);
    assert.match(row(f, {status: 'passed', no_gatekeeper_record: true, out_of_sample: null, in_sample: {pnl: 3, trades: 9, days: 60}}),
      /on the history it searched over 60 days/);
  });
}
