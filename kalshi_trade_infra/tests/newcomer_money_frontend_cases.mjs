// Shared cases from a new customer's first ten minutes, run against each bundle's offline harness (Tau and Meridian):
// the dashboard's money reads plainly. Walk 2026-10-30: three paper P&L figures on one screen counted three stretches
// of time (the strip's last 24 hours, the autopilot card's all time, Meridian's today in UTC) with nothing saying which;
// "realized", "after typical live slippage" and "Stake not set" had no bubble; and the autopilot's week ended in a
// dense paragraph on how its rows are counted. Display only: every figure is the server's, unchanged.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const text = (html) => html.replace(/<button[\s\S]*?<\/button>/g, '').replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
// A term's bubble, as gl() and glo() draw it.
const bubble = (k) => new RegExp(`<button type="button" class="info" data-glo="${k}"`);
const EST = {pnl: 1.2, per_fill_cents: 0.5};
const NOTE = 'Research counts every session, yours and the autopilot’s. The two paper rows count only what the autopilot put on paper itself; strategies you deploy yourself count in the running total and on the Deploy page, not here.';
const WEEK = {research_credits: 0.62, checkin_credits: 0, tested: 6, passed: 0, not_cleared: 0, paper_started: 1, paper_trades: 2,
  paper_pnl: 0.8, card_charged: false, paper_slippage_estimate: EST};
const STATUS = {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 6, passed_7d: 0}, paper_running: 1, demo_running: 0,
  live_running: 0, today_paper_pnl: 0.55, today_live_pnl: 0, today_paper_slippage_estimate: {pnl: 0.5, per_fill_cents: 0.5},
  focus: [], idle: null, story: ['It is trading on paper.'], week: WEEK};

export function newcomerMoneyCases({name, frontend, dashboard}) {
  const PAPER = {realized_pnl: 1.35, closed_trades: 3, total_pnl: 1.35, today_pnl: 0.55, open_positions: 0, slippage_estimate: EST};
  const board = (paper = {}) => ({...dashboard(), paper: {...dashboard().paper, ...PAPER, ...paper}});
  const open = async (status = STATUS, data = board()) => {
    const box = {data};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(box.data);
      if (path === '/api/autopilot/status') return response(status);
      return response({messages: [], models: []});
    }});
    f.S.me.user.autopilot = true; f.S.ap = status;
    await f.viewDashboard(); await settle();
    f.S.ap = status; f.paintDashAp();
    return {f, box};
  };
  const panel = async (status) => {
    const f = frontend({fetchImpl: () => response({messages: [], models: []})});
    f.S.me.user.autopilot = true;
    const box = new (f.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl><div id="apf-week"></div>';
    await f.apUpdate(box, status); await settle();
    f.clearTimers();
    return box;
  };

  test(`${name}: every paper P&L figure on the dashboard says its window first, in the same words`, async () => {
    const {f} = await open();
    const card = f.root.querySelector('#dash-ap').innerHTML;
    const dts = [...card.matchAll(/<dt>([\s\S]*?)<\/dt>/g)].map((m) => text(m[1]));
    assert.ok(dts.includes('Since you started: paper P&amp;L, realized'), dts.join(' | '));
    assert.ok(dts.includes('Last 7 days: autopilot’s paper P&amp;L'), dts.join(' | '));
    assert.doesNotMatch(card, /realized all time|Autopilot’s paper P&amp;L/);
    // The money band's paper figure, in each theme's words, leads with the window too.
    const band = text(f.root.querySelector('.figures').innerHTML);
    assert.match(band, /Since you started: (?:\+\$1\.35 realized|realized P&amp;L \+\$1\.35)/);
    assert.doesNotMatch(band, /realized all time|Realized P&amp;L, all time/);
    // The panel's day.
    const stats = (await panel(STATUS)).querySelector('#apf-stats').innerHTML;
    assert.ok([...stats.matchAll(/<dt>([\s\S]*?)<\/dt>/g)].map((m) => text(m[1])).includes('Today (UTC): paper realized'));
    // The strip's Money row: the last 24 hours on a first visit, since the last visit after that, said before its books.
    for (const [first, win] of [[true, 'Last 24 hours'], [false, 'Since your last visit']]) {
      const strip = f.sinceStrip({...board(), deployments: [], since: {at: '2026-10-30T08:00:00Z', first, books: {paper: {pnl: 0.55, trades: 1}},
        passed: {n: 0, items: []}, autopilot: {}, runs: {}}}, '#dash-deps');
      const money = /<dt>Money<\/dt><dd>([\s\S]*?)<\/dd>/.exec(strip)[1];
      assert.match(money, new RegExp(`^<span class="pnl-win">${win}:</span> <span class="since-book" data-book="paper">`));
      assert.match(strip, new RegExp(`aria-label="${win}"`));
    }
    f.clearTimers();
  });

  test(`${name}: the dashboard's money terms carry a bubble a keyboard and a thumb can open`, async () => {
    const {f} = await open();
    const card = f.root.querySelector('#dash-ap').innerHTML;
    // "realized" on the card's paper figure; the estimate beside it and the week's carry the slippage bubble, glued to
    // their last word, inside the estimate's own muted line.
    const cell = /<dt><span class="pnl-win">Since you started:<\/span>[\s\S]*?<\/dt><dd>([\s\S]*?)<\/dd>/.exec(card);
    assert.match(cell[0], bubble('realized'));
    assert.match(cell[1], /<span class="slip-est">≈\s\+\$1\.20 after typical live slippage \(estimate: 0\.5¢ a contract each time an order <span class="nobr">fills\)<button type="button" class="info" data-glo="slippage" aria-label="What does “After typical live slippage” mean\?">/);
    assert.equal((card.match(/data-glo="slippage"/g) || []).length, 2, 'the card’s figure and its week’s');
    const band = f.root.querySelector('.figures').innerHTML;
    assert.match(band, bubble('realized')); assert.match(band, bubble('slippage'));
    // The panel's day: "realized" and its estimate.
    const stats = (await panel(STATUS)).querySelector('#apf-stats').innerHTML;
    assert.match(stats, bubble('realized')); assert.match(stats, bubble('slippage'));
    // The bubbles are buttons, so Tab and a tap reach them; each names its term for a screen reader.
    for (const b of f.root.querySelectorAll('#dash-ap .info[data-glo]')) {
      assert.equal(b.tag, 'button'); assert.match(b.attributes['aria-label'], /^What does “.+” mean\?$/);
    }
    f.clearTimers();
  });

  test(`${name}: the week's note on how its rows are counted folds behind a disclosure, its words unchanged`, async () => {
    const {f} = await open();
    const how = f.root.querySelector('#dash-ap .ap-week-how');
    assert.equal(how.tag, 'details'); assert.equal('open' in how.attributes, false, 'shut at first');
    assert.equal(how.querySelector('summary').textContent, 'How these are counted');
    assert.equal(how.querySelector('.ap-week-note').textContent, NOTE);
    // The panel's week folds it the same way.
    const week = (await panel(STATUS)).querySelector('#apf-week');
    assert.equal(week.querySelector('.ap-week-how summary').textContent, 'How these are counted');
    assert.equal(week.querySelector('.ap-week-how .ap-week-note').textContent, NOTE);
    // An empty week has no rows to explain: no disclosure.
    const quiet = (await panel({...STATUS, week: {...WEEK, research_credits: 0, tested: 0, paper_started: 0, paper_trades: 0, paper_pnl: 0}})).querySelector('#apf-week');
    assert.equal(quiet.querySelector('.ap-week-how'), null);
    f.clearTimers();
  });

  // The card is repainted on every poll: an opened disclosure shut, and focus fell back to the page, under a reader.
  test(`${name}: a poll keeps the week's disclosure open and focus on its summary, and leaves unchanged markup alone`, async () => {
    const {f, box} = await open();
    let host = f.root.querySelector('#dash-ap');
    const writes = host.writes;
    f.paintDashAp();  // the same status, nothing opened: nothing is written
    assert.equal(host.writes, writes);
    host.querySelector('.ap-week-how').open = true;
    const summary = host.querySelector('.ap-week-how summary'); summary.focus(); f.document.activeElement = summary;
    f.S.ap = {...STATUS, today_paper_pnl: 0.6, week: {...WEEK, tested: 7}}; f.paintDashAp();
    host = f.root.querySelector('#dash-ap');
    const how = host.querySelector('.ap-week-how');
    assert.equal('open' in how.attributes, true, 'drawn open, as the reader left it');
    how.open = true;  // a browser reflects the attribute in the property; the harness doesn't
    const again = how.querySelector('summary');
    assert.notEqual(again, summary);
    assert.ok(again.focused || f.document.activeElement === again, 'focus is back on the summary');
    assert.equal(again.focusOptions.preventScroll, true);
    // The dashboard's own poll rewrites the board around the card: the same card stays, open, with focus in it.
    const replaceWith = Object.getPrototypeOf(host).replaceWith;
    Object.getPrototypeOf(host).replaceWith = function (node) {
      const i = this.parent.children.indexOf(this); this.parent.children[i] = node; node.parent = this.parent; node.removed = false; this.removed = true;
    };
    try {
      const card = host; f.document.activeElement = again; again.focused = false;
      box.data = board({realized_pnl: 1.9, closed_trades: 4, total_pnl: 1.9});
      for (const tick of [...f.intervals.values()]) await tick();
      await settle();
      assert.match(text(f.root.querySelector('.figures').innerHTML), /1\.90/, 'the board was rewritten');
      assert.equal(f.root.querySelector('#dash-ap'), card, 'the same card, put back');
      assert.equal('open' in card.querySelector('.ap-week-how').attributes || card.querySelector('.ap-week-how').open === true, true);
      const now = card.querySelector('.ap-week-how summary');
      assert.ok(now.focused || f.document.activeElement === now);
    } finally {
      Object.getPrototypeOf(host).replaceWith = replaceWith;
    }
    f.clearTimers();
  });
}
