// A signed amount never breaks between its sign and "$": the browser may end a line on "−" (a prefix character to
// the line breaker) and start the next with "$13.56". usd() in each bundle puts a word joiner (U+2060, invisible and
// zero width) between them. It is for the screen only: no attribute (aria-label, title), no tab title, nothing a
// copy puts on the clipboard and no CSV ever carries it. Checked with plain node:assert, so the joiner itself is
// what is compared (the other tests read text as a person sees it, through assert_text.mjs).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {loadBundle, pageText, renderPage} from './view_fuzz_harness.mjs';
import {me, replies} from './view_fuzz_fixtures.mjs';

const WJ = '⁠';
const PAGES = ['/', '/research', '/research/5', '/strategies', '/strategies/42', '/deploy', '/funds', '/billing',
  '/settings', '/explore', '/explore?m=KXBTC15M-26OCT251815-15', '/community', '/system', '/admin'];
const answer = (r) => (url) => r[url.split('?')[0]];
// Every element under `el`, with the attributes the page gave it.
const walk = (el, out = []) => { out.push(el); el.children.forEach((c) => walk(c, out)); return out; };
// The attributes written in a page's markup, read from the markup itself (the harness parses most, and an SVG's
// in a chart string too).
const markupAttrs = (html) => [...html.matchAll(/\s([\w:-]+)="([^"]*)"/g)].map(([, k, v]) => [k, v]);

for (const bundle of ['app.js', 'app.meridian.js']) {
  const source = loadBundle(bundle);

  test(`${bundle}: usd() glues its sign to "$" with a word joiner, and plain() takes it out`, async () => {
    const {t} = await renderPage(source, '/settings', answer(replies()), {me: me()});
    assert.equal(t.usd(-13.56), '−' + WJ + '$13.56');
    assert.equal(t.usd(2, true), '+' + WJ + '$2.00');
    assert.equal(t.usd(-250000), '−' + WJ + '$250,000');
    // Unsigned and zero have no sign to keep, so nothing is added.
    assert.equal(t.usd(5), '$5.00');
    assert.equal(t.usd(0, true), '$0.00');
    assert.equal(t.usd(null), '—');
    assert.equal(t.plain(t.usd(-13.56)), '−$13.56');
    assert.equal(t.plain(null), '');
  });

  test(`${bundle}: every page keeps each signed amount whole, and no attribute or tab title carries the joiner`, async () => {
    let joined = 0;
    for (const page of PAGES) {
      const {crashes, root, document} = await renderPage(source, page, answer(replies()), {me: me()});
      assert.deepEqual(crashes.map((e) => e.message || String(e)), [], page);
      const text = pageText(root);
      // A sign straight before "$" is one a line could end on.
      assert.doesNotMatch(text, /[−+]\$/, `${page}: a sign without its joiner`);
      joined += (text.match(/[−+]⁠\$/g) || []).length;
      for (const el of walk(root)) {
        for (const [k, v] of [...Object.entries(el.attributes), ...markupAttrs(el.html || '')]) {
          assert.ok(!String(v).includes(WJ), `${page}: <${el.tag} ${k}="${v}"> carries the joiner`);
        }
      }
      assert.ok(!document.title.includes(WJ), `${page}: the tab title`);
    }
    assert.ok(joined > 10, `signed amounts drawn with the joiner: ${joined}`);
  });

  test(`${bundle}: copying a signed amount puts it on the clipboard without the joiner`, async () => {
    const {documentListeners, window} = await renderPage(source, '/deploy', answer(replies()), {me: me()});
    const copy = documentListeners.copy || [];
    assert.equal(copy.length, 1, 'one copy handler');
    const set = {};
    let prevented = false;
    const event = {clipboardData: {setData: (type, value) => { set[type] = value; }}, preventDefault: () => { prevented = true; }};
    const range = {cloneContents: () => ({tag: 'span', children: []})};
    window.getSelection = () => ({toString: () => 'Realized −' + WJ + '$13.56 · +' + WJ + '$2.00', rangeCount: 1, getRangeAt: () => range});
    copy[0](event);
    assert.ok(prevented, 'the copy is the page’s own');
    assert.equal(set['text/plain'], 'Realized −$13.56 · +$2.00');
    assert.ok(!String(set['text/html']).includes(WJ));
    // A selection without a signed amount is left to the browser.
    const plainEvent = {clipboardData: {setData: () => { throw new Error('should not be set'); }}, preventDefault: () => { throw new Error('should not be prevented'); }};
    window.getSelection = () => ({toString: () => '$5.00 a trade', rangeCount: 1, getRangeAt: () => range});
    copy[0](plainEvent);
  });

  test(`${bundle}: the market page's CSV download is plain numbers`, () => {
    // Built from the raw points, never from a formatter: no joiner, no sign glyph, no "$".
    const csv = /const csv = '([^']*)' \+ d\.points\.map\(\(p\) => `([^`]*)`\)/.exec(readFileSync(new URL(`../app/static/${bundle}`, import.meta.url), 'utf8'));
    assert.ok(csv, 'the CSV line');
    assert.equal(csv[1], 'time_utc,unix_ts,yes_price,volume\\n');
    assert.doesNotMatch(csv[2], /usd\(|cents\(|\$\{(?!new Date|p\.t|p\.yes|Math\.round)/);
  });
}

test('the page files glue their own signed amounts (Billing’s sub-cent charges) and share WJ from the bundle', () => {
  for (const f of ['app-billing.js', 'app.meridian-billing.js']) {
    const src = readFileSync(new URL(`../app/static/${f}`, import.meta.url), 'utf8');
    assert.match(src, /\(n < 0 \? '−' : '\+'\) \+ WJ \+ '\$'/, f);
  }
  for (const f of ['app.js', 'app.meridian.js']) {
    const src = readFileSync(new URL(`../app/static/${f}`, import.meta.url), 'utf8');
    // No hand-built sign before "$" outside usd(), except the signed-out landing's static demo and chart axis text.
    const loose = src.split('\n').filter((l) => /['`]\s*:\s*'[−+]'\)?\}?\s*\$\$\{|'[−+]'\) \+ '\$'/.test(l) && !/paper → live|pnlEl|wholePaperAxis/.test(l));
    assert.deepEqual(loose, [], f);
  }
});
