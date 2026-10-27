// Shared cases from a brand-new Bitcoin trader's first hour, run against each bundle's offline harness (Tau
// and Meridian): the autopilot panel says what it is doing once, not twice in a row.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

const REVIEWING = "Right now it's reviewing the markets to pick its next move. Each move shows up in its activity feed.";
const FRESH_ON = {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 0, passed_7d: 0}, paper_running: 0, demo_running: 0,
  live_running: 0, today_paper_pnl: 0, today_live_pnl: 0, reviewing: true, focus: ['btc'],
  idle: {code: 'reviewing', line: "Nothing is on paper yet: no strategy has passed its research tests. It's reviewing the markets to pick its next move.", action: null},
  story: [REVIEWING, 'It sticks to the focus you set: Bitcoin.',
    'Nothing trades real money until a strategy makes money on paper over at least 30 trades from 20 separate events and 48 hours, and you turn on live autopilot.']};

export function freshWalkCases({name, frontend}) {
  const panel = async (status) => {
    const f = frontend({fetchImpl: () => response({messages: [], models: []})});
    f.S.me.user.autopilot = true;
    const box = new (f.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
    await f.apUpdate(box, status); await settle();
    f.clearTimers();
    return box;
  };
  const storyText = (box) => box.querySelectorAll('#apf-story p').map((p) => p.textContent.replace(/&#39;/g, "'"));

  // Right after a new user switched it on, the panel's lead line ended "It's reviewing the markets to pick its next
  // move." and the next line began "Right now it's reviewing the markets to pick its next move."
  test(`${name}: the autopilot panel says what it is doing right now once, under the line on why nothing is on paper`, async () => {
    const lines = storyText(await panel(FRESH_ON));
    assert.equal(lines.join(' ').split('pick its next move').length - 1, 1, lines.join('\n'));
    assert.deepEqual(lines.slice(0, 3), [FRESH_ON.idle.line, 'Each move shows up in its activity feed.', 'It sticks to the focus you set: Bitcoin.']);
    // An idle line that doesn't say it keeps the story's first line whole.
    const other = {...FRESH_ON, idle: {code: 'waiting', line: 'No trades right now: Fade is waiting for a contract that fits its entry rules.', action: null}};
    assert.equal(storyText(await panel(other))[1], REVIEWING);
    // With no idle line, the story is as the server sent it.
    assert.deepEqual(storyText(await panel({...FRESH_ON, idle: null})), FRESH_ON.story);
  });
}
