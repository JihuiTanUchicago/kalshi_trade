// Shared cases for the Deploy board's actions, bulk deploy, the community feed and the research draft,
// run against each bundle's offline DOM/transport harness (Tau and Meridian).
import assert, {visible} from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const dep = (overrides = {}) => ({id: 1, strategy_id: 1, title: 'Dep one', market: 'btc15m', mode: 'paper', status: 'running',
  status_reason: null, realized_pnl: 1, closed_trades: 5, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z',
  curve: [], stake: 5, max_positions: 1, backtest: {out_of_sample: null}, ...overrides});
export const memorySession = () => {
  const stored = new Map();
  return {stored, getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, String(value)), removeItem: key => stored.delete(key)};
};

export function deployActionCases({name, frontend, strategyFrontend, detailStrategy, postRequests, source}) {
  // The board re-reads after an action; that re-read failing is not the action failing.
  const board = ({reread = true} = {}) => {
    let reads = 0, sent = 0;
    const f = frontend({fetchImpl: (path, options) => {
      if (path === '/api/deployments') {
        reads++;
        return reads > 1 && !reread ? response({error: 'busy'}, 503) : response({deployments: [dep({status: sent ? 'paused' : 'running'})], open_positions: []});
      }
      if (path === '/api/deployments/1/pause') { sent++; return response({ok: true}); }
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    return f;
  };

  test(`${name}: a Pause that landed while the board's re-read failed confirms it and says to reload`, async () => {
    const f = board({reread: false});
    await f.viewDeploy(); await settle();
    const pause = f.root.querySelector('#deps [data-act="pause"]');
    pause.onclick(); await settle();
    assert.equal(postRequests(f).length, 1);
    const flash = f.root.querySelector('#flash').innerHTML;
    assert.match(flash, /class="notice good"/);
    assert.match(flash, /Deployment paused\. The page didn’t refresh, so reload to see it\./);
    assert.doesNotMatch(flash, /notice bad|Tau is having trouble/);
    // The row still offers Pause for a deployment that is now paused: it stays locked, so no second send.
    assert.equal(pause.disabled, true);
    pause.onclick(); await settle();
    assert.equal(postRequests(f).length, 1);
    f.clearTimers();
  });

  test(`${name}: a double press on Pause sends it once, and a refreshed board repaints the row`, async () => {
    const f = board();
    await f.viewDeploy(); await settle();
    const pause = f.root.querySelector('#deps [data-act="pause"]');
    pause.onclick(); pause.onclick(); await settle();
    assert.equal(postRequests(f).length, 1);
    assert.ok(f.root.querySelector('#deps [data-act="resume"]'));
    assert.doesNotMatch(f.root.querySelector('#flash').innerHTML, /didn’t refresh/);
    f.clearTimers();
  });

  test(`${name}: a poll that repaints the board while Pause is on its way draws that row locked, not idle`, async () => {
    let paused = false, land, reads = 0;
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/deployments?') || path === '/api/deployments') {
        reads++;  // a trade closed between reads, so each read repaints the board
        return response({deployments: [dep({status: paused ? 'paused' : 'running', closed_trades: 5 + reads}), dep({id: 2, strategy_id: 2, title: 'Dep two'})], open_positions: []});
      }
      if (path === '/api/deployments/1/pause') return new Promise(resolve => { land = () => { paused = true; resolve(response({ok: true})); }; });
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const first = f.root.querySelector('#deps [data-dep="1"][data-act="pause"]');
    first.onclick(); await settle();
    for (const tick of [...f.intervals.values()]) await tick();
    await settle();
    const pause = f.root.querySelector('#deps [data-dep="1"][data-act="pause"]'), remove = f.root.querySelector('#deps [data-dep="1"][data-act="stop"]');
    assert.notEqual(pause, first, 'the poll repainted the row');
    assert.equal(pause.disabled, true); assert.ok(pause.classList.contains('busy'));
    assert.equal(remove.disabled, true); assert.ok(!remove.classList.contains('busy'));
    assert.equal(f.root.querySelector('#deps [data-dep="2"][data-act="pause"]').disabled, false);  // another row is free
    land(); await settle();
    const resume = f.root.querySelector('#deps [data-dep="1"][data-act="resume"]');
    assert.equal(resume.disabled, false); assert.ok(!resume.classList.contains('busy'));
    assert.equal(f.root.querySelector('#deps [data-dep="1"][data-act="stop"]').disabled, false);
    assert.equal(postRequests(f).length, 1);
    f.clearTimers();
  });

  // The engine sells what a paused or removed deployment holds: with positions open, Pause and Remove
  // say so on their first press, and only a second press sends the action.
  test(`${name}: Pause and Remove on a deployment holding positions say they sell them before acting`, async () => {
    const sent = [];
    const f = frontend({fetchImpl: path => {
      if (path === '/api/deployments') return response({deployments: [dep({open_positions: 2, unrealized_pnl: 0.4})], open_positions: []});
      if (/^\/api\/deployments\/1\/(pause|stop)$/.test(path)) { sent.push(path); return response({ok: true}); }
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const pause = f.root.querySelector('#deps [data-act="pause"]'), remove = f.root.querySelector('#deps [data-act="stop"]');
    pause.onclick(); await settle();
    assert.deepEqual(sent, []);
    assert.equal(pause.textContent, 'Pause and sell 2 open?');
    remove.onclick(); await settle();
    assert.deepEqual(sent, []);
    assert.equal(remove.textContent, 'Remove and sell 2 open?');
    f.elapse(500); pause.onclick(); await settle();
    assert.deepEqual(sent, ['/api/deployments/1/pause']);
    f.clearTimers();
    // Nothing open: Pause goes at once, and Remove keeps its plain confirm.
    const g = board();
    await g.viewDeploy(); await settle();
    const stop = g.root.querySelector('#deps [data-act="stop"]');
    stop.onclick(); await settle();
    assert.equal(stop.textContent, 'Confirm stop');
    g.root.querySelector('#deps [data-act="pause"]').onclick(); await settle();
    assert.equal(postRequests(g).length, 1);
    g.clearTimers();
  });

  test(`${name}: a Pause the server refuses still says why, as an error`, async () => {
    const f = frontend({fetchImpl: path => path === '/api/deployments/1/pause' ? response({error: 'Only a running deployment can be paused.'}, 409)
      : path === '/api/deployments' ? response({deployments: [dep()], open_positions: []}) : response({})});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    f.root.querySelector('#deps [data-act="pause"]').onclick(); await settle();
    const flash = f.root.querySelector('#flash').innerHTML;
    assert.match(flash, /notice bad/); assert.match(flash, /Only a running deployment can be paused\./);
    assert.doesNotMatch(flash, /didn’t refresh/);
    f.clearTimers();
  });

  test(`${name}: stopping a strategy's deployment that landed says so when the page can't re-read`, async () => {
    let stopped = 0;
    const f = frontend({fetchImpl: path => {
      if (path === '/api/strategies/42') return stopped ? response({error: 'busy'}, 503) : response(detailStrategy({deployments: [{id: 5, mode: 'paper', status: 'running'}]}));
      if (path === '/api/strategies/42/dev-curve') return response({dev_curve: []});
      if (path === '/api/deployments/5/stop') { stopped++; return response({ok: true}); }
      return response({});
    }});
    await f.viewStrategy(42); await settle();
    const stop = f.root.querySelector('#stop-dep');
    assert.ok(stop, 'the strategy page offers Stop deployment');
    stop.onclick(); stop.onclick(); await settle();  // a double-click arms; its second click does not confirm
    assert.equal(stopped, 0); assert.equal(stop.textContent, 'Confirm stop');
    f.elapse(500); stop.onclick(); await settle();  // a deliberate second press confirms
    assert.equal(stopped, 1);
    const main = f.root.querySelector('#main').innerHTML;
    assert.match(main, /class="notice good"[\s\S]*Deployment removed\. The page didn’t refresh, so reload to see it\./);
    assert.doesNotMatch(main, /notice bad|busy/);
    assert.ok(f.root.querySelector('[data-retry]'));
  });

  // Deploy's Realized sums the deployments it lists; the dashboard's all-time figure also counts the
  // removed ones. The label says what it sums, and a line names the removed deployments' total and the
  // two together (the server's realized_by_book), per book, never added across books.
  test(`${name}: Deploy's Realized says it sums the listed deployments and reconciles with the dashboard`, async () => {
    const board = async (body) => {
      const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({open_positions: [], ...body}) : response({})});
      f.location.pathname = '/deploy';
      await f.viewDeploy(); await settle();
      f.clearTimers();
      // Each signed amount sits in a no-wrap span (walk 2026-10-27 at 390px: "· −" ended a line, "$0.30 from …" began the
      // next); the words around it are read without the span.
      const html = visible(f.root.querySelector('#dfigs').innerHTML);
      for (const m of html.matchAll(/removed deployments?/g)) assert.match(html.slice(Math.max(0, m.index - 60), m.index), /<span class="nobr">[−+]?\$[\d.,]+<\/span> from \d+ $/);
      return html.replace(/<span class="nobr">([−+]?\$[\d.,]+)<\/span>/g, '$1');
    };
    const paper = await board({deployments: [dep({realized_pnl: 146.04})],
      realized_by_book: {paper: {listed: 146.04, removed: 5.72, removed_deployments: 2, all: 151.76}}});
    assert.match(paper, /<dt class="lab">Realized, listed below<\/dt>[\s\S]*\+\$146\.04/);
    assert.match(paper, /paper money, not real\u00a0· \+\$5\.72 from 2 removed deployments, \+\$151\.76 in all/);
    // One removed deployment, a loss: singular, signed.
    const one = await board({deployments: [dep({realized_pnl: 3})],
      realized_by_book: {paper: {listed: 3, removed: -1.25, removed_deployments: 1, all: 1.75}}});
    assert.match(one, /−\$1\.25 from 1 removed deployment, \+\$1\.75 in all/);
    // Nothing removed: no line about it.
    const none = await board({deployments: [dep({realized_pnl: 3})], realized_by_book: {paper: {listed: 3, removed: 0, removed_deployments: 0, all: 3}}});
    assert.doesNotMatch(none, /removed|in all/);
    // Demo has no "in all" (its dashboard figure counts from its last reload); live and paper stay apart.
    const books = await board({deployments: [dep({id: 1, mode: 'live', realized_pnl: 2}), dep({id: 2, mode: 'paper', realized_pnl: 40}), dep({id: 3, mode: 'demo', realized_pnl: -10})],
      realized_by_book: {live: {listed: 2, removed: 1, removed_deployments: 1, all: 3}, paper: {listed: 40, removed: 7, removed_deployments: 3, all: 47},
        demo: {listed: -10, removed: 4, removed_deployments: 1}}});
    assert.match(books, /Live realized, listed below[\s\S]*real money\u00a0· \+\$1\.00 from 1 removed deployment, \+\$3\.00 in all\u00a0· after Kalshi fees\u00a0· \+\$40\.00 on paper from the deployments listed, counted apart/);
    assert.match(books, /Demo realized, listed below[\s\S]*not real money\u00a0· \+\$4\.00 from 1 removed deployment\u00a0· after Kalshi fees\u00a0· a demo reload doesn’t reset it, so it can differ from the demo book’s P&amp;L since reload</);
    assert.doesNotMatch(books, /\$42\.00|\$32\.00|\$50\.00/);
    // Walk 2026-10-27 at 390px: "· +$0.75 from 1 removed deployment" and "· after Kalshi fees" began lines. Each "·" now
    // has a no-break space before it and a plain one after, so it ends its line.
    for (const html of [paper, books]) assert.ok(!/ ·/.test(html) && html.includes(' · '), html);
    // An empty board with removed deployments: no "listed below" over an empty list.
    const empty = await board({deployments: [], realized_by_book: {paper: {listed: 0, removed: 5.72, removed_deployments: 2, all: 5.72}}});
    assert.match(empty, /<dt class="lab">Realized<\/dt>[\s\S]*\+\$5\.72 from 2 removed deployments, \+\$5\.72 in all/);
  });

  // A demo copy the demo-copy sync paused while its paper deployment isn't running would be paused again
  // by the sync: its Resume is offered disabled with the server's reason, and its row says "paused".
  test(`${name}: a demo copy waiting on its paper deployment offers Resume disabled and says why`, async () => {
    const why = 'Waiting on its paper deployment, which is paused. Resume that one and this copy resumes with it';
    const block = 'Resume its paper deployment first: this demo copy resumes with it.';
    const sent = [];
    const f = frontend({fetchImpl: path => {
      if (path === '/api/deployments') return response({open_positions: [], deployments: [
        dep({id: 1, mode: 'paper', status: 'paused', status_reason: 'By you', status_why: 'You paused it'}),
        dep({id: 2, mode: 'demo', status: 'paused', demo_copy: true, status_why: why, resume_block: block,
             status_reason: 'Its paper strategy is no longer running, so the demo copy stopped too.'})]});
      if (/^\/api\/deployments\/\d+\/resume$/.test(path)) { sent.push(path); return response({ok: true}); }
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const deps = f.root.querySelector('#deps');
    const copy = deps.querySelector('[data-dep="2"][data-act="resume"]');
    assert.equal(copy.disabled, true);
    assert.equal(copy.getAttribute('title'), block);
    assert.match(copy.innerHTML, /Resume<span class="vh"> Dep one: Resume its paper deployment first: this demo copy resumes with it\.<\/span>/);
    assert.match(deps.innerHTML, /Waiting on its paper deployment, which is paused\. Resume that one and this copy resumes with it/);
    assert.doesNotMatch(deps.innerHTML, /demo copy stopped too/);
    copy.onclick(); await settle();
    assert.deepEqual(sent, []);
    // The paper deployment's own Resume works as before.
    const paper = deps.querySelector('[data-dep="1"][data-act="resume"]');
    assert.equal(paper.disabled, false); assert.equal(paper.getAttribute('title'), null);
    paper.onclick(); await settle();
    assert.deepEqual(sent, ['/api/deployments/1/resume']);
    f.clearTimers();
    // The dashboard's "since your last visit" names it in the same words, not the stored "stopped too".
    const strip = f.sinceStrip({since: {books: {}}, deployments: [dep({id: 2, mode: 'demo', status: 'paused', status_why: why,
      status_reason: 'Its paper strategy is no longer running, so the demo copy stopped too.'})]}, '#dash-deps');
    assert.match(strip, /is paused on demo<span class="since-sub">: Waiting on its paper deployment, which is paused/);
    assert.doesNotMatch(strip, /stopped too/);
  });

  // A strategy whose deployments were all removed still says what they did: book, dates, realized P&L.
  test(`${name}: a strategy page lists its removed deployments as past deployments`, async () => {
    const past = [
      {id: 9, mode: 'paper', created_at: '2026-10-02T08:00:00+00:00', removed_at: '2026-10-20T08:00:00+00:00', realized_pnl: 5.72, closed_trades: 14},
      {id: 8, mode: 'demo', created_at: '2026-09-28T08:00:00+00:00', removed_at: '2026-10-01T08:00:00+00:00', realized_pnl: -1.5, closed_trades: 1},
      {id: 7, mode: 'paper', created_at: '2026-09-20T08:00:00+00:00', removed_at: '2026-09-21T08:00:00+00:00', realized_pnl: 0, closed_trades: 0},
      {id: 6, mode: 'paper', created_at: '2026-09-10T08:00:00+00:00', removed_at: '2026-09-11T08:00:00+00:00', realized_pnl: 1, closed_trades: 1}];
    const f = strategyFrontend(detailStrategy({status: 'passed', deployments: [], past_deployments: past}), () => response({}));
    await f.viewStrategy(42); await settle();
    const rec = f.root.querySelector('.real-record');
    assert.ok(rec, 'the record section shows with only past deployments');
    const html = rec.innerHTML;
    assert.match(html, /<b>Past deployments:<\/b> (?:<span class="nobr">)?(?:<span class="mk ?">Paper<\/span>|Paper)/);
    assert.match(html, /Paper Oct 2–Oct 20(?:<\/span>)?, <span class="gain">\+\$5\.72<\/span> over 14 closed trades/);
    assert.match(html, /Demo Sep 28–Oct 1(?:<\/span>)?, <span class="loss">−\$1\.50<\/span> over 1 closed trade(?!s)/);
    assert.match(html, /Paper Sep 20–Sep 21(?:<\/span>)?, no closed trades, not real money\u00a0· 1 earlier/);
    assert.doesNotMatch(html, /Sep 10/);  // three shown, the rest counted
    // None removed: no line.
    const g = strategyFrontend(detailStrategy({status: 'passed', deployments: [], past_deployments: []}), () => response({}));
    await g.viewStrategy(42); await settle();
    assert.doesNotMatch(g.root.querySelector('#main').innerHTML, /Past deployments/);
  });

  // 5 contracts at 30.1¢ cost $1.5050, which the float 5 * 0.301 holds as 1.50499..: the board's own
  // product read $1.50 beside the dashboard's $1.51. It shows the server's cost for the row.
  test(`${name}: the Deploy board's open position shows the server's cost, not its own product`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments') return response({deployments: [dep()], open_positions: [{id: 5, deployment_id: 1, title: 'Dep one',
        mode: 'paper', ticker: 'KXBTC15M-26OCT27-T98', side: 'yes', qty: 5, entry_price: 0.301, entry_fee: 0, at_cost: 1.51, cost: 1.51,
        unrealized: null, market_close_time: '2026-10-28T08:00:00Z'}]});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const html = f.root.querySelector('#openpos').innerHTML;
    assert.match(html, /data-lab="Cost \+ fee">\$1\.51</);
    assert.doesNotMatch(html, /\$1\.50/);
    // The column says what it is, as each row's label and the strategy page do: "Unreal." read as "unreal".
    assert.deepEqual([...html.matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1]), ['Strategy', 'Market', 'Position', 'Cost + fee', 'Unrealized', 'Settles']);
    assert.doesNotMatch(html, /Unreal\./);
    f.clearTimers();
  });

  // Deploy's row said "BTC 15-min up/down" over its own open position in "Bitcoin up or down in 15 minutes" (and
  // Billing's research lines say the full name too). A market named on its own, as a row's market, is its full
  // label; the short one stays for chips. A position on a contract no market lists still says its deployment's
  // market in full.
  test(`${name}: Deploy names a row's market as its positions do, by its full label`, async () => {
    const pos = (id, ticker) => ({id, deployment_id: 1, title: 'Dep one', mode: 'paper', ticker, side: 'no', qty: 4, entry_price: 0.46,
      entry_fee: 0.07, at_cost: 1.91, cost: 1.91, unrealized: null, market_close_time: '2026-10-27T18:41:00Z', market: 'btc15m'});
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments') return response({deployments: [dep()], open_positions: [pos(5, 'KXBTC15M-26OCT271415-15'), pos(6, 'KXODD-26OCT27-T98')]});
      return response({});
    }});
    f.S.me.markets = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes', category: 'Crypto'}];
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const rows = f.root.querySelector('#deps').innerHTML, open = f.root.querySelector('#openpos').innerHTML;
    assert.match(rows, /Bitcoin up or down in 15 minutes/);
    assert.doesNotMatch(rows, /BTC 15-min/);
    assert.equal((open.match(/Bitcoin up or down in 15 minutes/g) || []).length, 2, 'both positions, listed or not');
    assert.doesNotMatch(open, /BTC 15-min/);
    f.clearTimers();
  });

  // Two paper deployments that made $0.0050 each: each row reads $0.01, so adding the rows read $0.02,
  // beside the strategies list's $0.01 (the exact $0.0100). The page shows the server's per-book total
  // (book_totals), the list's own figure, never its own sum of rounded rows.
  test(`${name}: a strategy page's per-book line is the server's exact total, not its rows added`, async () => {
    const deps = [dep({id: 3, realized_pnl: 0.01, closed_trades: 1}), dep({id: 4, status: 'paused', realized_pnl: 0.01, closed_trades: 2})];
    const f = strategyFrontend(detailStrategy({status: 'passed', deployments: deps, past_deployments: [],
      book_totals: {paper: {pnl: 0.01, trades: 3, open: 0, paused: true}}}), () => response({}));
    await f.viewStrategy(42); await settle();
    const html = f.root.querySelector('.real-record').innerHTML;
    assert.match(html, /\+\$0\.01<\/span> realized over 3 closed trades/);
    assert.doesNotMatch(html, /\$0\.02/);
  });

  test(`${name}: a research idea typed before the session ran out comes back for the same account on the same page`, async () => {
    const session = memorySession();
    const research = async (uid) => {
      const f = frontend({session, fetchImpl: path => {
        if (path === '/api/models') return response({models: [], default: ''});
        if (path === '/api/research/context') return response({markets: []});
        if (path === '/api/runs') return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null});
        if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
        return response({});
      }});
      f.S.me.user.id = uid; f.S.me.user.autopilot = false; f.location.pathname = '/research';
      await f.viewResearch(); await settle();
      f.clearTimers();
      return f.root.querySelector('textarea[name=prompt]');
    };
    const ta = await research(7);
    assert.equal(ta.value, '');
    ta.value = 'Fade the last-minute spike'; ta.dispatchEvent({type: 'input'});
    assert.equal((await research(7)).value, 'Fade the last-minute spike');
    // Another account signing in on this tab doesn't get it.
    assert.equal((await research(8)).value, '');
    // Clearing the box drops the draft.
    const again = await research(7); again.value = ''; again.dispatchEvent({type: 'input'});
    assert.equal((await research(7)).value, '');
    // Storage that throws (blocked or private) leaves the page working with an empty box.
    const f = frontend({session: {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); }},
      fetchImpl: path => path === '/api/runs' ? response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null}) : response({models: [], default: '', markets: []})});
    f.location.pathname = '/research';
    await f.viewResearch(); await settle(); f.clearTimers();
    const box = f.root.querySelector('textarea[name=prompt]');
    box.value = 'x'; box.dispatchEvent({type: 'input'});
    assert.equal(box.value, 'x');
    // A session that starts drops the draft before leaving the page.
    assert.match(source, /draft\.drop\(\);\n\s*go\('\/research\/' \+ r\.id\);/);
  });

  test(`${name}: bulk deploy shows a failure's own words once escaped, not as &amp;amp;`, () => {
    // flash() puts the text through notice(), which escapes it; the bulk line escaped it a second time.
    assert.match(source, /flash\('#bulkflash', `\$\{ok\} deployed\$\{errs\.length \? `\$\{SEP\}\$\{errs\.length\} failed: \$\{errs\[0\]\}` : ''\}`/);
    assert.doesNotMatch(source, /failed: \$\{esc\(errs\[0\]\)\}/);
  });

  test(`${name}: the community feed has no like handler, since no like button renders`, () => {
    assert.doesNotMatch(source, /\/like`/);
    assert.doesNotMatch(source, /data-act="like"|dataset\.act === 'like'/);
  });
}
