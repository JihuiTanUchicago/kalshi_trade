// Shared cases, run against each bundle's offline harness (Tau and Meridian): a brand-new customer's first
// session, walked on 2026-10-28 at 390px and 1280px from sign-up through turning on the autopilot, a research
// idea of their own, the autopilot putting what passed on paper, Deploy and the bell. Each case is a place the
// walk got stuck: a panel left over the next page's form, a bell that opened stale, a passed strategy with no
// word on what happens next, a Deploy button named for a list it didn't open, focus lost after Pause.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const AT = '2026-10-28T04:30:00Z';
const ago = (ms) => new Date(Date.now() - ms).toISOString();

export function firstSessionCases({name, frontend, dashboard, apStatus, storageFor}) {
  const meridian = name === 'Meridian';

  // Turning the autopilot on from the dashboard opens its panel on a wide screen. It stayed open on every page after,
  // over half of Research: the idea box, and the nav links under it. A panel the switch opened folds to its pill on
  // the next page; one the reader opened stays open.
  test(`${name}: the panel switching autopilot on opened folds on the next page; one the reader opened stays`, async () => {
    const store = new Map(), storage = storageFor(store);
    let status = {...apStatus, autopilot: false, mode: 'off'};
    const f = frontend({storage, fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dashboard());
      if (path === '/api/settings') { status = {...apStatus, autopilot: true}; return response({ok: true}); }
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      if (path === '/api/deployments') return response({deployments: [], open_positions: []});
      if (path.startsWith('/api/strategies')) return response({strategies: [], counts: {}});
      return response({});
    }});
    f.S.me.user.autopilot = false; f.S.ap = null;
    f.location.pathname = '/';
    await f.render(); await settle();
    await f.root.querySelector('#dash-ap [data-apcard="on"]').onclick(); await settle();
    assert.equal(store.get('tau_ap_open'), '1', 'switching on opens the panel on a wide screen');
    // The dashboard's own repaints (same page) leave it open.
    await f.render(); await settle();
    assert.equal(store.get('tau_ap_open'), '1');
    // Moving to another page folds it.
    f.location.pathname = '/deploy';
    await f.render(); await settle();
    assert.equal(store.get('tau_ap_open'), '0');
    assert.ok(f.document.getElementById('autopilot-float').querySelector('.apf-pill'), 'the pill, not the open panel');
    f.clearTimers();
    // Opened by the reader (the card's Open autopilot), it stays open from page to page.
    f.location.pathname = '/';
    await f.render(); await settle();
    f.root.querySelector('#dash-ap [data-apcard="open"]').onclick(); await settle();
    assert.equal(store.get('tau_ap_open'), '1');
    f.location.pathname = '/deploy';
    await f.render(); await settle();
    assert.equal(store.get('tau_ap_open'), '1');
    f.clearTimers();
  });

  // The autopilot put the first strategy on paper while the dashboard sat open: the board said "It put 1 on paper",
  // and the bell, opened a few seconds later, said "No notifications yet" (its own read comes once a minute).
  // Opening it re-reads a list older than 15 seconds, and focus lands on the first notice once it is in.
  test(`${name}: opening the bell re-reads a list kept from a while ago, and focus lands on what arrived`, async () => {
    const notes = {unread: 0, items: []};
    const f = frontend({notifications: notes, fetchImpl: (path) => {
      if (path === '/api/notifications/read') return response({ok: true});
      if (path === '/api/autopilot/status') return response({mode: 'off'});
      return response({});
    }});
    const reads = () => f.requests.filter(({path}) => path === '/api/notifications').length;
    f.location.pathname = '/';
    await f.render(); await settle();
    const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
    assert.equal(reads(), 1);
    // Opened at once, the list just read is the one shown: no second read.
    await trig.onclick({stopPropagation() {}}); await settle();
    assert.equal(reads(), 1);
    assert.match(menu.querySelector('.bell-empty').textContent, /No notifications yet/);
    await trig.onclick({stopPropagation() {}});
    notes.unread = 1;
    notes.items.push({id: 3, kind: 'deployed', body: 'Autopilot put “Late snap-back” on paper: it passed every research gate.',
      link: '/strategies/11', created_at: ago(5e3), read: false, more: 0});
    f.shiftClock(20e3);
    await trig.onclick({stopPropagation() {}}); await settle();
    assert.equal(reads(), 2, 'opened 20s later, it reads again');
    const first = menu.querySelector('a.notif');
    assert.ok(first, 'the new notice is listed');
    assert.equal(first.getAttribute('href'), '/strategies/11');
    assert.equal(first.focusOptions && first.focusOptions.preventScroll, true);  // focus went to it
    assert.doesNotMatch(menu.textContent, /No notifications yet/);
    f.clearTimers();
  });

  // Deploy with nothing deployed told a new account to "post it to the board" (Tau), and its See passed strategies
  // opened every strategy, not the passed ones.
  test(`${name}: an empty Deploy says to deploy a passed strategy here, and its button opens the passed ones`, async () => {
    const f = frontend({fetchImpl: (path) => path === '/api/deployments' ? response({deployments: [], open_positions: []})
      : path === '/api/strategies?status=passed' ? response({strategies: [], counts: {passed: 1}}) : response({})});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const empty = f.root.querySelector('#deps .empty');
    assert.match(empty.innerHTML, /Open a passed strategy and deploy it here\. Paper first: it trades the live market with paper money\./);
    assert.doesNotMatch(empty.innerHTML, /post it to the board/);
    assert.deepEqual(empty.querySelectorAll('a.btn').map((a) => [a.getAttribute('href'), a.textContent]), [['/strategies?status=passed', 'See passed strategies']]);
    f.clearTimers();
  });

  // Pause on a running session repainted its buttons (Pause became Resume) and focus fell to the top of the page;
  // Resume did the same, and a confirmed Cancel left nothing focused. Focus goes to the control that took the
  // pressed one's place, else the session's heading.
  test(`${name}: Pause, Resume and Cancel on a session keep focus on the control that replaces the pressed one`, async () => {
    let status = 'running';
    const f = frontend({fetchImpl: (path) => {
      const act = path.match(/^\/api\/runs\/9\/(pause|resume|cancel)$/);
      if (act) { status = {pause: 'paused', resume: 'running', cancel: 'cancelled'}[act[1]]; return response({ok: true}); }
      if (path.startsWith('/api/runs/9')) return response({run: {id: 9, prompt: 'Snap-back near the close', market: 'btc15m', status,
        run_forever: 1, created_at: AT, started_at: AT, hypotheses_tried: 1, strategies_passed: 0, ...(status === 'cancelled' ? {finished_at: AT, stop_reason: 'user'} : {})},
      events: [], strategies: []});
      return response({});
    }});
    f.location.pathname = '/research/9';
    await f.viewRun(9); await settle();
    const host = () => f.root.querySelector('#runact');
    const pause = host().querySelector('#pause');
    assert.equal(pause.focused, undefined, 'nothing is focused on a first paint');
    await pause.onclick({currentTarget: pause}); await settle();
    const resume = host().querySelector('#resume');
    assert.ok(resume, 'Pause became Resume');
    assert.equal(resume.focusOptions && resume.focusOptions.preventScroll, true);
    await resume.onclick({currentTarget: resume}); await settle();
    const again = host().querySelector('#pause');
    assert.equal(again.focusOptions && again.focusOptions.preventScroll, true);
    // A poll that repaints nothing moves nothing.
    again.focusOptions = undefined;
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.equal(again.focusOptions, undefined);
    f.clearTimers();
    // A press that failed keeps its button where it was and marks nothing for a later repaint.
    const g = frontend({fetchImpl: (path) => {
      if (/\/pause$/.test(path)) return response({error: 'Only a running session can be paused.'}, 409);
      if (path.startsWith('/api/runs/9')) return response({run: {id: 9, prompt: 'Idea', market: 'btc15m', status: 'running', created_at: AT, started_at: AT}, events: [], strategies: []});
      return response({});
    }});
    await g.viewRun(9); await settle();
    const p2 = g.root.querySelector('#runact #pause');
    await p2.onclick({currentTarget: p2}); await settle();
    assert.equal(g.root.querySelector('#runact').dataset.acted, undefined);
    g.clearTimers();
  });

  // Meridian's running session listed a passed strategy as "Status: Passed" and nothing else: no word on whether to
  // deploy it or wait for the autopilot, which Tau's Ideas tested row says. It says it under the title.
  test(`${name}: a session's passed strategy says what happens next, in Tau's words`, {skip: !meridian}, async () => {
    const strat = (o) => ({id: 42, title: 'Late snap-back', status: 'passed', market: 'btc15m', direction: 'mean_reversion',
      in_sample: {pnl: 14.2, trades: 60}, out_of_sample: {pnl: 8.52, trades: 30, days: 12}, deployed: false, ...o});
    const next = async (s) => {
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
        ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', status: 'running', run_forever: 1, created_at: AT, started_at: AT,
          hypotheses_tried: 2, strategies_passed: 1}, events: [], strategies: [s, {...strat({id: 43, title: 'Fade', status: 'rejected'})}]})
        : response({})});
      await f.viewRun(9); await settle(); f.clearTimers();
      return f.root.querySelector('#run-artifacts').querySelectorAll('.slip-next').map((el) => el.innerHTML);
    };
    assert.deepEqual(await next(strat({autopilot_next: true})), ['The autopilot puts it on paper at its next check-in<span data-ap-when></span>']);
    assert.deepEqual(await next(strat({deployed: true})), ['<a href="/deploy">Already deployed: see it on Deploy</a>']);
    // Its title above is the link to the page it deploys from, so the line is not a second one.
    assert.deepEqual(await next(strat()), ['Open it to deploy on paper']);
    // One that missed its final test says that instead (its own line), not a deploy.
    assert.deepEqual(await next(strat({verdict: 'missed_final', later_missed: [{label: 'Held up on the locked holdout'}]})), []);
  });
}
