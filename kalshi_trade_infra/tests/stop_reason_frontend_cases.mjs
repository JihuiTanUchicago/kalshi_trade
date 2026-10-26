// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian):
// - the research list says why a finished session stopped (the server's stop_reason), and the newest
//   session that ran out of credits offers Add credits;
// - a Deploy row says why it is paused in plain words (the server's status_why);
// - a Funds write repaints the page and keyboard focus comes back to the same control.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const run = (over) => ({id: 1, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea',
  hypotheses_tried: 9, strategies_passed: 1, spent_usd: 4.2, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit', ...over});
const counts = {research_running: 0, research_queued: 0, research_paused: 0};
const fundsData = (over = {}) => ({kalshi: {connected: false}, kalshi_dev: {connected: false},
  demo: {capital: 1000, equity: 1001, realized: 1}, paper: {cash: 1000, ledger: []}, ...over});

export function stopReasonCases({name, frontend}) {
  const research = (runs) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/runs') return response({runs, counts, policy: null, totals: {tried: 9, passed: 1}});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    return f;
  };

  test(`${name}: a research row says why its session stopped, in plain words`, () => {
    const f = frontend();
    for (const [over, said] of [
      [{stop_reason: 'credits', run_forever: 1}, /Out of credits/],
      [{stop_reason: 'complete', run_forever: 1}, /Finished/],
      [{stop_reason: 'limit'}, /Finished/],
      [{status: 'cancelled', stop_reason: 'user'}, /Stopped by you/],
      [{status: 'failed', stop_reason: 'error', error: 'The model provider is busy.'}, /<span class="loss">Stopped on an error<\/span>/],
    ]) {
      const row = f.runRow(run(over));
      assert.match(row, said, JSON.stringify(over));
      assert.doesNotMatch(row, /\bDone\b|>Cancelled<|>Failed</, JSON.stringify(over));
    }
    // A credits stop says how many passed too; the newest one alone offers Add credits, beside the card.
    const credits = run({stop_reason: 'credits', run_forever: 1});
    assert.match(f.runRow(credits), /1<\/b>|1 of 9 passed/);
    assert.doesNotMatch(f.runRow(credits), /href="\/billing"/);
    assert.doesNotMatch(f.runRow(credits, 0), /href="\/billing"/);  // a map index is not "newest"
    const newest = f.runRow(credits, true);
    assert.match(newest, /^<div class="run-cell"><a class="run-card [^"]*" href="\/research\/1">[\s\S]*<\/a><a class="run-add" href="\/billing">Add credits<span class="vh"> to keep researching<\/span><\/a><\/div>$/);
    assert.doesNotMatch(f.runRow(run({stop_reason: 'user', status: 'cancelled'}), true), /href="\/billing"/);
    // An older server without stop_reason keeps the old words.
    assert.match(f.runRow(run({status: 'cancelled', stop_reason: undefined})), /Cancelled/);
    // Credits are never written as money made or lost: the cost stays "Cost", not P&L.
    assert.doesNotMatch(newest, /P&amp;L|realized|\+\$4\.20/);
  });

  test(`${name}: the research list offers Add credits only on the newest session, and not while one runs`, async () => {
    const out = run({id: 9, stop_reason: 'credits', run_forever: 1, created_at: '2026-10-26T08:00:00Z'});
    const older = run({id: 5, stop_reason: 'credits', run_forever: 1});
    const mine = run({id: 3, status: 'cancelled', stop_reason: 'user'});
    let f = research([out, older, mine]);
    await f.viewResearch(); await settle();
    let list = f.root.querySelector('#runs').innerHTML;
    assert.equal((list.match(/Out of credits/g) || []).length, 2);
    assert.equal((list.match(/class="run-add" href="\/billing"/g) || []).length, 1);
    assert.match(list, /href="\/research\/9">[\s\S]*?<\/a><a class="run-add"/);
    assert.match(list, /Stopped by you/);
    f.clearTimers();
    // A session running now: research goes on, so no row asks for credits.
    f = research([run({id: 10, status: 'running', stop_reason: null}), out, older]);
    await f.viewResearch(); await settle();
    list = f.root.querySelector('#runs').innerHTML;
    assert.match(list, /Out of credits/);
    assert.doesNotMatch(list, /run-add/);
    f.clearTimers();
  });

  test(`${name}: a paused Deploy row says who or what paused it in plain words`, async () => {
    const dep = {id: 1, strategy_id: 1, title: 'Dep one', market: 'btc15m', mode: 'paper', status: 'paused', status_reason: 'By you',
      status_why: 'You paused it', realized_pnl: 1, closed_trades: 5, open_positions: 0, unrealized_pnl: null,
      created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1, backtest: {out_of_sample: null}};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments') return response({deployments: [dep], open_positions: []});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const html = f.root.querySelector('#deps').innerHTML;
    assert.match(html, /You paused it/);
    assert.doesNotMatch(html, /By you/);
    f.clearTimers();
  });

  // Funds: each write repaints the page. Focus a control the way a keyboard user would, write, and
  // the repainted twin of that control (or what replaced it) has focus.
  const fundsPage = (connectedAfter = false) => {
    let connected = false;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/funds') return response(fundsData(connected ? {kalshi: {connected: true, key_id: 'abcd', balance: 10, funding_url: 'https://kalshi.com'}} : {}));
      if (path === '/api/funds/paper' || path === '/api/funds/demo') return response({ok: true});
      if (path === '/api/kalshi-key') { connected = connectedAfter; return response({ok: true, balance: 10}); }
      return response({});
    }});
    f.location.pathname = '/funds';
    return f;
  };
  const focusOn = (f, el) => { el.focus(); f.document.activeElement = el; };

  test(`${name}: after Add on Funds, focus comes back to the same control`, async () => {
    for (const [pick, again] of [
      [(form) => form.querySelector('input[name=amount]'), '#paper input[name=amount]'],
      [(form) => form.querySelector('[data-kind="deposit"]'), '#paper [data-kind="deposit"]'],
    ]) {
      const f = fundsPage();
      await f.viewFunds(); await settle();
      const form = f.root.querySelector('#paper'); form.amount = {value: '500'};
      const control = pick(form); focusOn(f, control);
      await form.onsubmit({preventDefault() {}}); await settle();
      const twin = f.root.querySelector(again);
      assert.notEqual(twin, control, 'the page repainted');
      assert.equal(twin.focusOptions && twin.focusOptions.preventScroll, true, again);
      assert.match(f.root.querySelector('#pflash').innerHTML, /Added to your paper account\./);
    }
    // Reload demo, from its button.
    const f = fundsPage();
    await f.viewFunds(); await settle();
    const df = f.root.querySelector('#demo'); df.amount = {value: '1000'};
    focusOn(f, df.querySelector('button'));
    await df.onsubmit({preventDefault() {}}); await settle();
    assert.equal(f.root.querySelector('#demo button').focusOptions.preventScroll, true);
  });

  test(`${name}: after a key connects, focus goes to Disconnect, which replaced the form`, async () => {
    const f = fundsPage(true);
    await f.viewFunds(); await settle();
    const kf = f.root.querySelector('#kalshi');
    kf.key_id = {value: 'a952bcbe-ec3b-4b5b-8c1d-000000000000'};
    kf.private_key = {value: '-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----'};
    focusOn(f, kf.querySelector('button'));
    await kf.onsubmit({preventDefault() {}}); await settle();
    assert.equal(f.root.querySelector('#kalshi'), null);
    assert.equal(f.root.querySelector('#disconnect').focusOptions.preventScroll, true);
  });

  test(`${name}: a Funds write leaves focus alone when it was not on a control`, async () => {
    const f = fundsPage();
    await f.viewFunds(); await settle();
    f.document.activeElement = f.document.body;
    const form = f.root.querySelector('#paper'); form.amount = {value: '500'};
    await form.onsubmit({preventDefault() {}}); await settle();
    for (const el of f.root.querySelectorAll('#paper input, #paper button')) assert.equal(el.focusOptions, undefined);
  });
}
