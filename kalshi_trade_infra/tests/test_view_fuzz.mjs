// No page breaks ("Something went wrong on this page") because a reply lacks an optional field, carries
// null where an object was, or comes from an older stored row. Every main view of both bundles renders
// from realistic replies (view_fuzz_fixtures.mjs), then again with fields taken away (view_fuzz_harness.mjs):
// each object's plain fields all missing, then all null, and each nested object or list alone. A crash
// is what the page itself reports to /admin (reportBroken('view')) or a promise it leaves rejected.
// TAU_VIEW_FUZZ=full takes every field away on its own instead (slower; for hunting, not CI).
import assert from './assert_text.mjs';
import {test} from 'node:test';
import {fuzzPage, loadBundle, pageText, renderPage} from './view_fuzz_harness.mjs';
import {me, replies, scenarios} from './view_fuzz_fixtures.mjs';

const MARKET = '/explore?m=KXBTC15M-26OCT251815-15';
const PAGES = ['/', '/research', '/research/5', '/strategies', '/strategies/42', '/deploy', '/funds', '/billing',
  '/settings', '/explore', MARKET, '/community', '/system', '/admin'];
// Replies every page reads (the bell, the autopilot panel): fuzzed on the dashboard only.
const SHARED = ['/api/notifications', '/api/autopilot/status'];

// Fields app/server.py builds on every request (never read back from a stored row) and always sends:
// the page may rely on them. Everything else a page reads must be survivable missing or null.
const KEPT = {
  '/api/dashboard': ['paper', 'demo', 'live', 'open_positions', 'recent_closed', 'deployments', 'agents', 'freshness',
    'since.books', 'since.passed.items', 'open_positions.*.side', 'recent_closed.*.side', 'open_positions.*.ticker', 'recent_closed.*.ticker'],
  '/api/track-record': ['generated_at', 'default_mode', 'modes', 'modes.live', 'modes.demo', 'modes.paper', 'method', 'thresholds',
    'modes.live.sample', 'modes.demo.sample', 'modes.paper.sample', 'modes.live.monthly', 'modes.demo.monthly', 'modes.paper.monthly',
    'modes.live.strategies', 'modes.demo.strategies', 'modes.paper.strategies', 'modes.demo.monthly.*.month', 'modes.paper.monthly.*.month',
    'modes.live.label', 'modes.demo.label', 'modes.paper.label'],
  '/api/runs': ['runs', 'counts'],
  '/api/research/scoreboard': ['trend.before', 'trend.after', 'tournament.book'],
  '/api/runs/5': ['run', 'events'],
  '/api/strategies': ['strategies'],
  '/api/strategies/42': ['rules', 'deployments', 'holdings.*.side'],
  '/api/deployments': ['deployments', 'open_positions', 'open_positions.*.side'],
  '/api/funds': ['paper', 'paper.ledger', 'kalshi'],
  '/api/billing': ['cards', 'ledger'],
  '/api/explore': ['markets'],
  '/api/explore/market': ['points', 'mine.open', 'mine.closed', 'mine.open.*.side', 'mine.closed.*.side'],
  '/api/community': ['posts'],
  '/api/admin/system': ['nodes', 'events'],
  '/api/admin': ['users', 'waitlist', 'orphaned_open.by_mode'],
};

const say = broke => broke.map(b => `${b.endpoint} ${b.path} ${b.op}: ${b.error && b.error.message || b.error}`).join('\n');

for (const bundle of ['app.js', 'app.meridian.js']) {
  const source = loadBundle(bundle);
  for (const page of PAGES) {
    test(`${bundle} ${page} renders with any optional field missing or null`, async () => {
      const full = process.env.TAU_VIEW_FUZZ === 'full';
      const broke = await fuzzPage(source, page, replies(), me(), {kept: KEPT, skip: page === '/' ? [] : SHARED, items: full ? 8 : 2, single: full});
      assert.equal(broke.length, 0, say(broke));
    });
  }
  test(`${bundle} renders whole states that older rows and new accounts produce`, async () => {
    for (const [name, page, changed] of scenarios()) {
      const r = {...replies(), ...changed};
      const {crashes, root} = await renderPage(source, page, url => r[url.split('?')[0]], {me: me()});
      assert.deepEqual(crashes.map(e => e.message || String(e)), [], name);
      // A missing figure reads as a dash or is left out, never as the word "undefined" or "NaN".
      assert.doesNotMatch(pageText(root), /\bundefined\b|\bNaN\b/, name);
    }
  });
}
