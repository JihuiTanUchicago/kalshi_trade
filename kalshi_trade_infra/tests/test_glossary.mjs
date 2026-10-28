// The info bubbles (GLOSSARY in app.js and app.meridian.js) say the same words in both themes, every marker a page
// draws names a term its theme defines, and each definition is plain. Walk 2026-10-28: "Realized", "Unrealized",
// "Later-period P&L" and "instant fill" had no bubble at all, and "Unseen data" said "This is the P&L that counts"
// beside a strategy whose later-period figure was not held out.
import assert from './assert_text.mjs';
import {readdirSync, readFileSync} from 'node:fs';
import {test} from 'node:test';

const DIR = new URL('../app/static/', import.meta.url);
const read = (f) => readFileSync(new URL(f, DIR), 'utf8');
const glossary = (bundle) => {
  const src = read(bundle), at = src.indexOf('const GLOSSARY = {');
  assert.ok(at > 0, bundle);
  const body = src.slice(at + 'const GLOSSARY = '.length, src.indexOf('\n  };', at) + 4);
  return new Function(`return ${body};`)();
};
const THEMES = {
  tau: ['app.js', (f) => f === 'app.js' || (f.startsWith('app-') && f.endsWith('.js'))],
  meridian: ['app.meridian.js', (f) => f.startsWith('app.meridian') && f.endsWith('.js')],
};
const files = readdirSync(DIR);
// The keys a theme's pages draw a marker for: glo('k'), gloSep('k', ...) and gl(label, 'k').
const used = (pick) => {
  const keys = new Set();
  for (const f of files.filter(pick)) {
    const src = read(f);
    for (const m of src.matchAll(/\bglo(?:Sep)?\('([a-z0-9]+)'/g)) keys.add(m[1]);
    for (const m of src.matchAll(/\bgl\((?:'[^']*'|`[^`]*`|[A-Z_]+), '([a-z0-9]+)'\)/g)) keys.add(m[1]);
  }
  return keys;
};

test('both themes define the same terms in the same words', () => {
  const tau = glossary('app.js'), mer = glossary('app.meridian.js');
  assert.deepEqual(Object.keys(mer).sort(), Object.keys(tau).sort());
  for (const k of Object.keys(tau)) assert.deepEqual(mer[k], tau[k], k);
});

test('every marker a page draws names a term its theme defines', () => {
  for (const [theme, [bundle, pick]] of Object.entries(THEMES)) {
    const defined = glossary(bundle), keys = used(pick);
    assert.ok(keys.size >= 8, `${theme}: ${[...keys]}`);
    assert.deepEqual([...keys].filter((k) => !(k in defined)), [], theme);
  }
});

test('the money words a customer meets are defined, plainly', () => {
  const g = glossary('app.js');
  for (const k of ['realized', 'unrealized', 'unseen', 'laterperiod', 'insample', 'instantfill', 'paperfills']) assert.ok(g[k], k);
  assert.equal(g.unseen[0], 'Later-period P&L (unseen data)');
  assert.equal(g.laterperiod[0], 'Later-period P&L');
  // Later-period P&L is the slice that picked the strategy; only unseen data is held out.
  assert.match(g.laterperiod[1], /wasn’t held out/);
  assert.match(g.unseen[1], /held-out slice of history the agent never looked at/);
  assert.doesNotMatch(g.unseen[1], /wasn’t held out/);
  // "after typical live slippage" (slipEst, beside paper P&L) is said and sized in the paper fills bubble.
  assert.match(g.paperfills[1], /price moving in the second or two before a real order lands\. Where a page shows an estimate after typical live slippage/);
  for (const [k, [title, words]] of Object.entries(g)) {
    assert.doesNotMatch(`${title} ${words}`, /[A-Za-z]'[A-Za-z]/, `${k}: a straight apostrophe`);
    assert.doesNotMatch(`${title} ${words}`, /\b[a-z0-9]+_[a-z0-9_]+\b|\b[A-Z]{2,}_[A-Z_]{2,}|`/, `${k}: a code name`);
    assert.match(words, /\.$/, `${k}: a whole sentence`);
  }
});

// Where the walk found a term with no bubble, there is one now, in both themes.
test('the Deploy table and the strategy page carry the new markers in both themes', () => {
  for (const f of ['app.js', 'app.meridian.js']) {
    const src = read(f);
    assert.match(src, /<th class="num">\$\{gl\('Realized(?: P&amp;L)?', 'realized'\)\}<\/th><th class="num">\$\{gl\('Unrealized', 'unrealized'\)\}<\/th>/, f);
    assert.match(src, /left out of this record \(\$\{usd\(\+r\.excluded_instant_pnl \|\| 0, true\)\}\)`, 'instantfill'\)/, f);
    assert.match(src, /left out \(\$\{INSTANT_WHY\}\)`, 'instantfill'\)\}\$\{esc\(trLeftGap\(m\)\)\}/, f);  // the track record's caveat
  }
  for (const f of ['app-strategies.js', 'app.meridian-strategies.js']) {
    const src = read(f);
    for (const k of ['laterperiod', 'unseen', 'insample']) assert.match(src, new RegExp(`gl\\('[^']+ P&L(?: \\([a-z ]+\\))?', '${k}'\\)`), `${f}: ${k}`);
  }
});

// The autopilot card's "Furthest on paper" and its panel said "instant-fill paper trades left out (…)" with no
// bubble; both carry the instant-fill one now, glued to the note's last word (gl), in both themes.
test('the autopilot card and panel give the instant-fill note its bubble in both themes', () => {
  for (const f of ['app.js', 'app.meridian.js']) {
    assert.match(read(f), /\$\{paperCount\(prog\)\}<\/a> <small>\$\{gl\(PAPER_COUNT_WHY, 'instantfill'\)\}<\/small>/, f);
  }
  for (const f of ['app-autopilot.js', 'app.meridian-autopilot.js']) {
    assert.match(read(f), /net on them\. <small>\$\{gl\(PAPER_COUNT_WHY_SAID, 'instantfill'\)\}<\/small>/, f);
  }
});
