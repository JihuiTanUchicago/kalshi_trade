// A line never starts with "·". Pieces of one line are joined by SEP (a no-break space, "·", a plain space), so
// a line that wraps ends on the separator. The old " ·\u00a0" glued "·" to what followed it, and at 390px lines
// began "· 3 trades", "· Max 2 open" or "· +$3.80 on paper". This renders every main page of both bundles from
// the view fuzz's replies (and the whole states it renders: new accounts, older rows) and reads what each page
// wrote, then checks the bundles' own source, so a page the fixtures don't reach can't bring the pattern back.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {pageFiles} from './bundle_source.mjs';
import {loadBundle, renderPage} from './view_fuzz_harness.mjs';
import {me, replies, scenarios} from './view_fuzz_fixtures.mjs';

const PAGES = ['/', '/research', '/research/5', '/strategies', '/strategies/42', '/deploy', '/funds', '/billing',
  '/settings', '/explore', '/explore?m=KXBTC15M-26OCT251815-15', '/community', '/system', '/admin'];
const NBSP = '(?:\u00a0|&nbsp;|&#160;|\\\\u00a0)', DOT = '(?:·|&middot;|&#183;|\\\\u00b7)';
// A breakable space, then "·" glued to the next word: a wrap there starts the next line with "·".
const LEADING = new RegExp(`[ \\t\\n]${DOT}${NBSP}`);
// The hot-markets rail's "· See all markets" is its own marker, kept as designed.
const KEPT = new RegExp(`${DOT}${NBSP}(?:<a href="/explore">)?See all markets`, 'g');

// Every element the page wrote into (a part painted later doesn't re-serialize its parent), tags taken out so a
// separator split across them (" <span>·\u00a0…") is seen too, and the kept marker left out.
function written(root) {
  const out = [];
  const visit = (el) => {
    if (el.writes || el.text !== undefined) out.push((el.text !== undefined ? el.text : el.html || '').replace(KEPT, '').replace(/<[^>]*>/g, ''));
    el.children.forEach(visit);
  };
  visit(root);
  return out;
}
const offending = (texts) => texts.flatMap((t) => {
  const m = LEADING.exec(t);
  return m ? [JSON.stringify(t.slice(Math.max(0, m.index - 40), m.index + 40))] : [];
});

for (const bundle of ['app.js', 'app.meridian.js']) {
  const source = loadBundle(bundle);
  test(`${bundle}: no rendered page has a separator that can start a line with "·"`, async () => {
    const r = replies(), seen = [];
    for (const page of PAGES) {
      const {crashes, root} = await renderPage(source, page, (url) => r[url.split('?')[0]], {me: me()});
      assert.deepEqual(crashes.map((e) => e.message || String(e)), [], page);
      seen.push(...offending(written(root)).map((s) => `${page}: ${s}`));
    }
    for (const [name, page, changed] of scenarios()) {
      const all = {...r, ...changed};
      const {root} = await renderPage(source, page, (url) => all[url.split('?')[0]], {me: me()});
      seen.push(...offending(written(root)).map((s) => `${name} (${page}): ${s}`));
    }
    assert.deepEqual(seen, []);
  });

  // The source: every page file whole, and the bundle but for its signed-out landing page (its demo reel is
  // left as it is) and the rail's kept marker.
  test(`${bundle}: the bundle and its page files join pieces with SEP, never " ·\\u00a0"`, () => {
    const dir = new URL('../app/static/', import.meta.url);
    const own = readFileSync(new URL(bundle, dir), 'utf8');
    const land = own.indexOf('  // ---------- landing (pre-login) ----------'), dash = own.indexOf('  // ---------- dashboard ----------');
    assert.ok(land > 0 && dash > land, 'the landing section is where it was');
    assert.match(own, /\n {2}const SEP = '\\u00a0\\u00b7 ';\n/);
    const files = [[bundle, own.slice(0, land) + own.slice(dash)], ...pageFiles(bundle).map((f) => [f, readFileSync(new URL(f, dir), 'utf8')])];
    const seen = files.flatMap(([f, src]) => src.replace(KEPT, '').split('\n').flatMap((line, i) => (
      LEADING.test(line) && !/^\s*(\/\/|\*)/.test(line) ? [`${f}:${i + 1}: ${line.trim().slice(0, 120)}`] : [])));
    assert.deepEqual(seen, []);
  });
}

test('the check finds the old separator, in a page and in source', () => {
  assert.deepEqual(offending(['Removed from paper: +$1.00 ·\u00a03 trades']).length, 1);
  assert.deepEqual(offending(['since deploying <span>·&nbsp;2 trades</span>'.replace(/<[^>]*>/g, '')]).length, 1);
  assert.ok(LEADING.test("x ? ' \\u00b7\\u00a0' + y : ''"));
  assert.deepEqual(offending(['Removed from paper: +$1.00\u00a0· 3 trades', 'Updated 1 min ago ·\u00a0See all markets'.replace(KEPT, '')]), []);
});
