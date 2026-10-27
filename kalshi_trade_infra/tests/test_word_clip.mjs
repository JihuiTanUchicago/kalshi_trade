// A cut title ends on a whole word. Walk 2026-10-27 at 390px and 1280px: a research session named by a long idea
// read "... when the spot pri…" on Tau's session list (the card's three-line clamp cuts wherever the line ends,
// mid-word in Chrome at most widths) and "... minutes of each fift…" in the browser tab of its page, on both
// bundles (the tab title's cut at 59 characters). Both now go through one helper, clipWords, which cuts at the
// last whole word that fits and adds "…"; the card keeps the whole idea on hover. Meridian's list shows it whole.
import assert from './assert_text.mjs';
import {test} from 'node:test';
import {loadBundle, renderPage} from './view_fuzz_harness.mjs';
import {me, replies} from './view_fuzz_fixtures.mjs';

const LONG = 'Fade the overreaction in the last three minutes of each fifteen-minute Bitcoin window when the spot price '
  + 'has moved more than two standard deviations from the open, but only while the book is thin';

// `shown` is the start of `full` up to the end of a word (then any comma or dash it dropped), and "…".
function cutOnWord(shown, full, most) {
  assert.match(shown, /…$/, shown);
  const head = shown.slice(0, -1);
  assert.ok(head.length <= most, `${head.length} characters, at most ${most}: ${shown}`);
  assert.ok(full.startsWith(head), `${shown} is the start of the idea`);
  assert.match(full.slice(head.length), /^[,;:.–—-]* /, `"${shown}" stops at the end of a word`);
}

for (const bundle of ['app.js', 'app.meridian.js']) {
  const source = loadBundle(bundle), tau = bundle === 'app.js';
  const withIdea = (r, idea) => ({...r,
    '/api/runs': {...r['/api/runs'], runs: r['/api/runs'].runs.map((x) => ({...x, prompt: idea}))},
    '/api/runs/5': {...r['/api/runs/5'], run: {...r['/api/runs/5'].run, prompt: idea}}});

  test(`${bundle}: a session's page names its tab with its idea cut at a whole word`, async () => {
    const r = withIdea(replies(), LONG);
    const {crashes, document} = await renderPage(source, '/research/5', (url) => r[url.split('?')[0]], {me: me()});
    assert.deepEqual(crashes.map((e) => e.message || String(e)), []);
    const m = /^(.*) · Tau$/.exec(document.title);
    assert.ok(m, document.title);
    cutOnWord(m[1], LONG, 59);
    assert.equal(m[1], 'Fade the overreaction in the last three minutes of each…');
    // A short one is whole, with no "…".
    const s = withIdea(replies(), 'Fade the favourite');
    const short = await renderPage(source, '/research/5', (url) => s[url.split('?')[0]], {me: me()});
    assert.equal(short.document.title, 'Fade the favourite · Tau');
  });

  test(`${bundle}: the session list ${tau ? 'cuts a long idea at a whole word, whole on hover' : 'shows a long idea whole'}`, async () => {
    const r = withIdea(replies(), LONG);
    const {crashes, root} = await renderPage(source, '/research', (url) => r[url.split('?')[0]], {me: me()});
    assert.deepEqual(crashes.map((e) => e.message || String(e)), []);
    const b = root.querySelector('.run-title b');
    assert.ok(b, 'the list has a session card');
    if (tau) {
      cutOnWord(b.textContent, LONG, 80);
      assert.equal(b.textContent, 'Fade the overreaction in the last three minutes of each fifteen-minute Bitcoin…');
      assert.equal(b.getAttribute('title'), LONG);
    } else {
      assert.equal(b.textContent, LONG);
    }
  });
}

// The helper itself, in each bundle: the same cut everywhere it is used (the tab title, Tau's session cards, a
// deployment's pause reason on the dashboard, an autopilot move).
for (const bundle of ['app.js', 'app.meridian.js']) {
  test(`${bundle}: clipWords cuts at a whole word, drops a dangling comma, and leaves short text alone`, () => {
    const src = loadBundle(bundle);
    const at = src.indexOf('  const clipWords = (s, n) => {');
    assert.ok(at > 0, 'the bundle defines clipWords');
    const body = src.slice(at, src.indexOf('\n  };', at) + 5);
    const clipWords = new Function(`${body}; return clipWords;`)();
    assert.equal(clipWords('Fade the favourite', 59), 'Fade the favourite');
    assert.equal(clipWords('Fade the overreaction in the last', 12), 'Fade the…');
    assert.equal(clipWords('Fade the overreaction', 8), 'Fade the…', 'a space just past the cut: the last word is whole');
    assert.equal(clipWords('Thin books, wide spreads and more', 11), 'Thin books…', 'no "books,…"');
    assert.equal(clipWords('Supercalifragilistic', 5), 'Super…', 'one long word is cut at the limit');
    assert.equal(clipWords('Closes Oct 28, 02:45 UTC today', 19), 'Closes Oct 28…', 'a no-break space keeps its words together');
    assert.equal(clipWords('  spread\n over  lines  ', 59), 'spread over lines');
    assert.equal(clipWords(null, 5), '');
  });
}
