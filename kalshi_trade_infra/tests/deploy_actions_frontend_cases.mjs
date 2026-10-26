// Shared cases for the Deploy board's actions, bulk deploy, the community feed and the research draft,
// run against each bundle's offline DOM/transport harness (Tau and Meridian).
import assert from 'node:assert/strict';
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
    const main = f.root.querySelector('main').innerHTML;
    assert.match(main, /class="notice good"[\s\S]*Deployment stopped\. The page didn’t refresh, so reload to see it\./);
    assert.doesNotMatch(main, /notice bad|busy/);
    assert.ok(f.root.querySelector('[data-retry]'));
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
    assert.match(source, /flash\('#bulkflash', `\$\{ok\} deployed\$\{errs\.length \? ` ·\\u00a0\$\{errs\.length\} failed: \$\{errs\[0\]\}` : ''\}`/);
    assert.doesNotMatch(source, /failed: \$\{esc\(errs\[0\]\)\}/);
  });

  test(`${name}: the community feed has no like handler, since no like button renders`, () => {
    assert.doesNotMatch(source, /\/like`/);
    assert.doesNotMatch(source, /data-act="like"|dataset\.act === 'like'/);
  });
}
