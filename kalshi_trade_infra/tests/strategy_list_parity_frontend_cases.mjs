// The Strategies list (/strategies) draws byte for byte what it drew before it became one file for both themes
// (page-strategies.js, shared page files step: app-strategies.js and app.meridian-strategies.js each held their
// theme's own copy). Each state below is drawn in the offline harness, at desk and phone width, and its whole DOM
// (every string the page wrote, every element's attributes and hidden/checked/value state), the reads and writes it
// sent and where it went are compared with the snapshot taken from the two per-theme files before the move. The
// repo keeps each state's fingerprint (strategy_list_parity.json, a sha256 of the state's whole record), not the
// records themselves (about 3MB).
//
// A change that means to alter the list's markup writes the records out before and after it, to see what moved:
//   TAU_DUMP_STRATEGY_SNAPSHOTS=/some/dir node --test tests/test_frontend_merge.mjs tests/test_meridian_workspace.mjs
// and then takes the fingerprints again (TAU_WRITE_STRATEGY_SNAPSHOTS=1, one test file at a time: both write the one file).
import assert from './assert_text.mjs';
import {createHash} from 'node:crypto';
import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {test} from 'node:test';

const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

// The element tree as the page left it: one line per element (its tag, attributes, and the state a script sets
// as a property), and the markup of every element a script wrote into, so text between children is in too.
function dump(el) {
  const out = [];
  const walk = (e, depth) => {
    const pad = '  '.repeat(depth);
    const attrs = Object.entries(e.attributes).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([k, v]) => ` ${k}=${JSON.stringify(v)}`).join('');
    const state = [e.hidden ? 'hidden' : '', e.checked ? 'checked' : '', e.disabled ? 'disabled' : '', e.value ? 'value=' + JSON.stringify(e.value) : '',
      Object.keys(e.style || {}).length ? 'style=' + JSON.stringify(e.style) : '', e.text !== undefined ? 'text=' + JSON.stringify(e.text) : ''].filter(Boolean).join(' ');
    out.push(`${pad}<${e.tag}${attrs}>${state ? ' {' + state + '}' : ''}`);
    if (e.writes) out.push(`${pad}  html=${JSON.stringify(e.html || '')}`);
    if (e.outer !== undefined) out.push(`${pad}  outer=${JSON.stringify(e.outer)}`);
    e.children.forEach(c => walk(c, depth + 1));
  };
  walk(el, 0);
  return out.join('\n');
}

const SNAP = new URL('./strategy_list_parity.json', import.meta.url);
const sha = (o) => createHash('sha256').update(JSON.stringify(o)).digest('hex');

export function strategyListParityCases({name, frontend, detailStrategy}) {
  const theme = name === 'Tau' ? 'tau' : 'meridian';
  const oos = {pnl: 3.1, trades: 40, win_rate: 0.6, days: 9};
  const MARKETS = [{key: 'btc15m', category: 'Crypto'}, {key: 'btc_daily', category: 'Crypto'}, {key: 'eth15m', category: 'Crypto'}];
  const ROWS = [
    detailStrategy({id: 61, title: 'Cleared pass', status: 'passed', out_of_sample: oos, hypotheses_tried: 18}),
    detailStrategy({id: 62, title: 'Missed final', status: 'passed', verdict: 'missed_final', out_of_sample: oos}),
    detailStrategy({id: 63, title: 'Held back', status: 'passed', verdict: 'held_back', out_of_sample: oos}),
    detailStrategy({id: 64, title: 'On paper', status: 'passed', deployed: true, books: ['paper'], real: {pnl: 1.25, trades: 3, open: 1, mode: 'paper'}}),
    detailStrategy({id: 65, title: 'On demo', status: 'passed', deployed: true, books: ['demo'], real: {pnl: -0.4, trades: 2, open: 0, mode: 'demo'}}),
    detailStrategy({id: 66, title: 'Live and paper', status: 'passed', deployed: true, deploy_live: true, books: ['live', 'paper'], real: {pnl: 2, trades: 1, open: 0, mode: 'live', live: true}}),
    detailStrategy({id: 67, title: 'Paused paper', status: 'passed', deployed: true, books: ['paper'], real: {pnl: 0, trades: 0, open: 0, mode: 'paper', paused: true}}),
    detailStrategy({id: 68, title: 'Removed from paper', status: 'passed', past: {paper: {pnl: -1.5, trades: 4}, demo: {pnl: 0.3, trades: 1}}}),
    detailStrategy({id: 69, title: 'Research only', status: 'passed', research_only: true}),
    detailStrategy({id: 70, title: 'Perpetual', status: 'passed', market: 'btc_perp', direction: 'momentum'}),
    detailStrategy({id: 71, title: 'Void one', status: 'failed', out_of_sample: oos, no_gatekeeper_record: true}),
    detailStrategy({id: 72, title: 'Rejected one', status: 'rejected', out_of_sample: null}),
    detailStrategy({id: 73, title: 'Backtest only', status: 'backtest-only', out_of_sample: oos, parent_id: 61, hypotheses_tried: null}),
    detailStrategy({id: 74, title: 'Shared to me', status: 'passed', shared_from: 'maya', by_autopilot: true}),
    detailStrategy({id: 75, title: 'Example', status: 'passed', example: true, by_autopilot: true}),
  ];
  const COUNTS = {total: 40, passed: 12, not_cleared: 2, failed: 9, failed_no_record: 3, rejected: 7, 'backtest-only': 1, deployed: 4};
  const list = (o = {}) => ({counts: COUNTS, matched: ROWS.length, pages: 1, strategies: ROWS, ...o});

  // name -> {search, autopilot, answer(path, options, n), act(f)}: each draws the list, then does what `act` says.
  const STATES = {
    'empty, a new account': {answer: () => response({counts: {total: 0}, matched: 0, pages: 0, strategies: []})},
    'empty, autopilot on': {autopilot: true, answer: () => response({counts: {total: 0}, matched: 0, pages: 0, strategies: []})},
    'none kept yet': {answer: () => response({counts: {total: 4, failed: 2, rejected: 2}, matched: 0, pages: 0, strategies: []})},
    'none kept yet, autopilot on': {autopilot: true, answer: () => response({counts: {total: 4, failed: 2, rejected: 2}, matched: 0, pages: 0, strategies: []})},
    'Passed with none passed': {search: '?status=passed', answer: () => response({counts: {total: 3, failed: 3}, matched: 0, pages: 0, strategies: []})},
    'a filter that matches none': {search: '?status=&q=zzz', answer: () => response({counts: {total: 5, passed: 2}, matched: 0, pages: 0, strategies: []})},
    'research-only rows': {answer: () => response(list({strategies: ROWS.slice(8, 10), matched: 2, counts: {total: 2, passed: 2}}))},
    'paper, demo and live rows': {answer: () => response(list())},
    'no paper column': {answer: () => response(list({strategies: [ROWS[0], ROWS[10], ROWS[11]], matched: 3}))},
    'every filter on': {search: '?status=passed&market=btc15m&q=Momentum&deployed=1&sort=best', answer: () => response(list({counts: {...COUNTS, total: 4, passed: 4}}))},
    'not cleared chip': {search: '?status=not_cleared', answer: () => response(list({strategies: ROWS.slice(1, 3), matched: 2}))},
    'void and rejected chips': {search: '?status=failed', answer: () => response(list({strategies: ROWS.slice(10, 12), matched: 2}))},
    'sorted by later-period P&L': {search: '?status=&sort=best', answer: () => response(list())},
    'page 2 of 3': {search: '?status=&page=2', answer: () => response(list({pages: 3, matched: 140}))},
    'a remembered page past the end': {search: '?status=&page=4', answer: (path) => response(new URLSearchParams(path.split('?')[1]).get('page') === '0' ? list() : list({strategies: []}))},
    'a read that failed': {answer: () => response({error: 'Something went wrong on our side. It’s been logged.'}, 500)},
    'a read that failed, then Try again': {answer: (path, options, n) => n === 1 ? response({error: 'Bad request.'}, 400) : response(list()),
      act: async (f) => { f.root.querySelector('#slips [data-retry]').onclick(); await settle(); }},
    'filters pressed': {act: async (f, snap) => {
      f.root.querySelectorAll('[data-f="status"]').find(b => b.dataset.v === 'passed').onclick(); await settle(); snap();
      f.root.querySelector('[data-toggle="deployed"]').onclick(); await settle(); snap();
      const m = f.root.querySelector('#strat-market'); m.value = 'eth15m'; m.onchange(); await settle(); snap();
      const s = f.root.querySelector('#strat-sort'); s.value = 'best'; s.onchange(); await settle(); snap();
      const q = f.root.querySelector('#strat-q'); q.value = '  thesis '; q.onchange(); await settle();
    }},
    'next and previous page': {search: '?status=&page=2', answer: () => response(list({pages: 3, matched: 140})), act: async (f, snap) => {
      f.root.querySelector('[data-sp="2"]').onclick(); await settle(); snap();
      f.root.querySelector('[data-sp="1"]').onclick(); await settle(); snap();
      f.root.querySelector('[data-sp="0"]').onclick(); await settle();
    }},
    'rows picked for bulk deploy': {act: async (f, snap) => {
      const pick = f.root.querySelector('.pick'); pick.checked = true; pick.onchange(); await settle(); snap();
      const all = f.root.querySelector('#pick-all'); all.checked = true; all.onclick(); await settle(); snap();
      all.checked = false; all.onclick(); await settle(); snap();
      pick.checked = true; pick.onchange(); await settle(); snap();
      f.root.querySelector('#bulk-clear').onclick(); await settle();
    }},
    'bulk deploy that lands': {answer: (path, options) => options && options.method === 'POST' ? response({id: 900}) : response(list({strategies: [ROWS[0], ROWS[13]]})), act: async (f, snap) => {
      f.root.querySelectorAll('.pick').forEach(p => { p.checked = true; p.onchange(); }); await settle(); snap();
      await f.root.querySelector('#bulk-dep').onclick({target: f.root.querySelector('#bulk-dep')}); await settle();
    }},
    'bulk deploy that partly fails': {answer: (path, options) => {
      if (!(options && options.method === 'POST')) return response(list({strategies: [ROWS[0], ROWS[13]]}));
      return JSON.parse(options.body).strategy_id === 61 ? response({id: 901}) : response({error: 'This strategy can’t be deployed.'}, 400);
    }, act: async (f, snap) => {
      f.root.querySelectorAll('.pick').forEach(p => { p.checked = true; p.onchange(); }); await settle(); snap();
      await f.root.querySelector('#bulk-dep').onclick({target: f.root.querySelector('#bulk-dep')}); await settle();
    }},
  };

  const draw = async (state, phone) => {
    let n = 0;
    const answer = state.answer || (() => response(list()));
    const f = frontend({matchMedia: () => ({matches: phone}), fetchImpl: (path, options) => path.startsWith('/api/strategies') || path === '/api/deployments' && options && options.method === 'POST' ? answer(path, options, ++n) : response({})});
    f.S.me.markets = MARKETS;
    if (state.autopilot) f.S.me.user.autopilot = true;
    f.location.pathname = '/strategies'; f.location.search = state.search ?? '?status=';
    const drawing = f.viewStrategies();
    for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }
    await drawing; await settle();
    // What it drew, then each step of what `act` does (snap), then what was left once it was done, unless it went on to
    // another page (Deploy, after a bulk deploy that landed), whose markup isn't this page's.
    const doms = [dump(f.document.body)];
    if (state.act) {
      await state.act(f, () => doms.push(dump(f.document.body)));
      for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }
      if (f.location.pathname === '/strategies') doms.push(dump(f.document.body));
    }
    const requests = f.requests.filter(({path}) => path.startsWith('/api/strategies') || path === '/api/deployments')
      .map(({path, options}) => [path, (options && options.method) || 'GET', (options && options.body) || null]);
    const shot = {doms, requests, navigations: f.navigations};
    f.clearTimers();
    return shot;
  };

  test(`${name}: the Strategies list draws what it drew before it was one file for both themes, in every state and at both widths`, async () => {
    const shots = {};
    for (const [label, state] of Object.entries(STATES)) {
      for (const [width, phone] of [['desk', false], ['phone', true]]) shots[`${label} @ ${width}`] = await draw(state, phone);
    }
    // The same state drawn twice is the same (no clock or order in it), so a difference below is the page's.
    assert.deepEqual(await draw(STATES['paper, demo and live rows'], false), shots['paper, demo and live rows @ desk']);
    // Each state drew a list page, not a page-file failure.
    for (const [key, shot] of Object.entries(shots)) assert.match(shot.doms[0], /<div id="slips"/, key);
    const dir = process.env.TAU_DUMP_STRATEGY_SNAPSHOTS;
    if (dir) { mkdirSync(dir, {recursive: true}); writeFileSync(`${dir}/${theme}.json`, JSON.stringify(shots, null, 1) + '\n'); }
    const got = Object.fromEntries(Object.entries(shots).map(([key, shot]) => [key, sha(shot)]));
    if (process.env.TAU_WRITE_STRATEGY_SNAPSHOTS) {
      const all = existsSync(SNAP) ? JSON.parse(readFileSync(SNAP, 'utf8')) : {};
      all[theme] = got;
      writeFileSync(SNAP, JSON.stringify(Object.fromEntries(Object.keys(all).sort().map((k) => [k, all[k]])), null, 1) + '\n');
      return;
    }
    assert.ok(existsSync(SNAP), 'the fingerprints are in the repo');
    const want = JSON.parse(readFileSync(SNAP, 'utf8'))[theme];
    assert.deepEqual(Object.keys(got), Object.keys(want), 'the same states');
    for (const key of Object.keys(want)) assert.equal(got[key], want[key], `${name}: ${key} draws otherwise than before`);
  });
}
