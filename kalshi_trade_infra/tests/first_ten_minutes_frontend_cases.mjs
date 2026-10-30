// Shared cases, run against each bundle's offline harness (Tau and Meridian): a brand-new customer's first ten
// minutes, walked 2026-10-30 at 390px and 1280px. Once autopilot is on, the dashboard's autopilot card said
// "It's researching Bitcoin up or down in 15 minutes" with nothing to press, and the session itself was two pages
// away (Research, then the row); the card now ends on the server's link to it. The heading's "1 agent researching"
// is a link to Research in both themes (only Meridian's was). Billing says what a token is instead of "billed per token".
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));

export function firstTenMinutesCases({name, frontend, dashboard, apStatus, billingPage, cardedBilling}) {
  const open = async (board, status) => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(board);
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      if (path.startsWith('/api/track-record')) return response({});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    f.S.ap = status; f.paintDashAp();
    return f;
  };
  const researching = (action) => ({...apStatus, autopilot: true, mode: 'paper', paper_running: 0, research: {active: ['Bitcoin up or down in 15 minutes'], watch: 41},
    idle: {code: 'researching', line: 'Nothing is on paper yet: no strategy has passed its research tests. It’s researching Bitcoin up or down in 15 minutes.', action}});

  test(`${name}: while autopilot researches, its dashboard card links the session it is running`, async () => {
    const f = await open(dashboard(), researching({label: 'Watch it research', href: '/research/41'}));
    const card = f.root.querySelector('#dash-ap');
    const link = [...card.querySelectorAll('a')].find((a) => a.textContent === 'Watch it research');
    assert.ok(link, 'the card links the running session');
    assert.equal(link.getAttribute('href'), '/research/41');
    assert.match(card.textContent, /It’s researching Bitcoin up or down in 15 minutes\. Watch it research/);
    // Several sessions: the link is Research, worded for them.
    f.S.ap = researching({label: 'Watch them on Research', href: '/research'}); f.paintDashAp();
    const many = [...f.root.querySelectorAll('#dash-ap a')].find((a) => a.textContent === 'Watch them on Research');
    assert.equal(many && many.getAttribute('href'), '/research');
    // A line with no action (an older server) still reads as it did, with nothing added.
    f.S.ap = researching(null); f.paintDashAp();
    assert.ok(![...f.root.querySelectorAll('#dash-ap a')].some((a) => /^Watch/.test(a.textContent)));
    f.clearTimers();
  });

  test(`${name}: the dashboard heading's "1 agent researching" is a link to Research`, async () => {
    const f = await open({...dashboard(), agents: {research_running: 1, research_queued: 0, research_paused: 0, chat_active: 0}}, researching(null));
    const link = [...f.root.querySelectorAll('a')].find((a) => a.textContent.trim() === '1 agent researching');
    assert.ok(link, 'the count is a link');
    assert.equal(link.getAttribute('href'), '/research');
    f.clearTimers();
  });

  test(`${name}: Billing says what credits are billed by in words a new customer knows`, async () => {
    const f = billingPage(cardedBilling());
    await f.viewBilling(); await flush();
    const text = f.root.textContent.replace(/\s+/g, ' ');
    assert.match(text, /billed by how much text the model you pick reads and writes \(its tokens\)\. Paper and live trading/);
    assert.doesNotMatch(text, /per token/);
  });
}
