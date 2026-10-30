// The info bubbles (GLOSSARY, in the shared core both themes take it from: core.js) are one set of words for both
// themes, every marker a page draws names a term the glossary defines, and each definition is plain. Walk 2026-10-28: "Realized", "Unrealized",
// "Later-period P&L" and "instant fill" had no bubble at all, and "Unseen data" said "This is the P&L that counts"
// beside a strategy whose later-period figure was not held out.
import assert from './assert_text.mjs';
import {readdirSync, readFileSync} from 'node:fs';
import {test} from 'node:test';

const DIR = new URL('../app/static/', import.meta.url);
const read = (f) => readFileSync(new URL(f, DIR), 'utf8');
const glossary = () => {
  const src = read('core.js'), at = src.indexOf('const GLOSSARY = {');
  assert.ok(at > 0);
  const body = src.slice(at + 'const GLOSSARY = '.length, src.indexOf('\n  };', at) + 4);
  return new Function(`return ${body};`)();
};
// Each theme's files: the core and the shared page files (what both themes draw with), the theme's bundle and page files.
const both = (f) => f === 'core.js' || (f.startsWith('page-') && f.endsWith('.js'));
const THEMES = {
  tau: ['app.js', (f) => both(f) || f === 'app.js' || (f.startsWith('app-') && f.endsWith('.js'))],
  meridian: ['app.meridian.js', (f) => both(f) || (f.startsWith('app.meridian') && f.endsWith('.js'))],
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

test('both themes say the same terms in the same words: one glossary, the core’s, that each takes', () => {
  assert.ok(Object.keys(glossary()).length >= 20);
  for (const [bundle, pick] of Object.values(THEMES)) {
    assert.match(read(bundle), /\n {4}[^\n]*\bGLOSSARY\b[^}]*\} = window\.TauCore;/, bundle);
    for (const f of files.filter(pick).filter((x) => x !== 'core.js')) assert.doesNotMatch(read(f), /\bconst GLOSSARY\b/, f);
  }
});

test('every marker a page draws names a term its theme defines', () => {
  for (const [theme, [bundle, pick]] of Object.entries(THEMES)) {
    const defined = glossary(), keys = used(pick);
    assert.ok(keys.size >= 8, `${theme}: ${[...keys]}`);
    assert.deepEqual([...keys].filter((k) => !(k in defined)), [], theme);
  }
});

test('the money words a customer meets are defined, plainly', () => {
  const g = glossary();
  for (const k of ['realized', 'unrealized', 'unseen', 'laterperiod', 'insample', 'instantfill', 'paperfills']) assert.ok(g[k], k);
  assert.equal(g.unseen[0], 'Later-period P&L (unseen data)');
  assert.equal(g.laterperiod[0], 'Later-period P&L');
  // Later-period P&L is the slice that picked the strategy; only unseen data is held out.
  assert.match(g.laterperiod[1], /wasn’t held out/);
  // A Void strategy's later stretch picked nothing (the first version's simple backtest judged it there and it failed):
  // its bubble says so, never laterperiod's "what picked it".
  assert.equal(g.latervoid[0], 'Later-period P&L');
  assert.match(g.latervoid[1], /after its split date, where it failed its checks\. There’s no record that stretch was held out/);
  assert.doesNotMatch(g.latervoid[1], /picked/);
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
    assert.match(src, /left out \(\$\{INSTANT_WHY\}\)`, 'instantfill'\)\}\$\{esc\(trLeftGap\(m\)\)\}/, f);  // the track record's caveat
    // The track record's per-strategy notes and a Deploy row's instant-fill note: drawn by the core for both themes.
    for (const n of ['trRowLeft', 'depInstant']) assert.match(src, new RegExp(`\\n {4}[^\\n]*\\b${n}\\b[^}]*\\} = window\\.TauCore;`), `${f}: ${n}`);
  }
  const core = read('core.js');
  assert.match(core, /left out of this record \(\$\{usd\(\+r\.excluded_instant_pnl \|\| 0, true\)\}\)`, 'instantfill'\)/);
  assert.match(core, /left out\$\{\+r\.excluded_instant_pnl \? ` \(\$\{usd\(\+r\.excluded_instant_pnl, true\)\}\)` : ''\}`, 'instantfill'\)\}<\/div>/);  // its per-strategy note
  assert.match(core, /of the count of realistic paper trades toward live\.`, 'instantfill'\)\}<\/div>/);  // a Deploy row's instant-fill note
  for (const f of ['app-strategies.js', 'app.meridian-strategies.js']) {
    const src = read(f);
    for (const k of ['laterperiod', 'latervoid', 'unseen', 'insample']) assert.match(src, new RegExp(`gl\\('[^']+ P&L(?: \\([^)']+\\))?', '${k}'\\)`), `${f}: ${k}`);
  }
});

// The autopilot card's "Furthest on paper" and its panel said "instant-fill paper trades left out (…)" with no
// bubble; both carry the instant-fill one now, glued to the note's last word (gl), in both themes.
test('the autopilot card and panel give the instant-fill note its bubble in both themes', () => {
  for (const f of ['app.js', 'app.meridian.js']) {
    assert.match(read(f), /\$\{paperCount\(prog\)\}<\/a> <small>\$\{gl\(PAPER_COUNT_WHY, 'instantfill'\)\}<\/small>/, f);
  }
  // The panel is one file both themes load (page-autopilot.js).
  assert.match(read('page-autopilot.js'), /net on them\. <small>\$\{gl\(PAPER_COUNT_WHY_SAID, 'instantfill'\)\}<\/small>/);
});

// A new account's walk (2026-10-30): "≈ after typical live slippage" and "Stake not set" had no bubble, a focused
// bubble below the fold shut as Tab scrolled it into view, and three paper figures named their windows three ways.
test('slippage and stake are defined plainly, and the estimate keeps its meaning', () => {
  const g = glossary();
  assert.equal(g.slippage[0], 'After typical live slippage');
  // An estimate beside paper P&L, never in its place: paper P&L and the checks toward live stay the figure.
  assert.match(g.slippage[1], /It is only an estimate: the paper P&amp;L beside it is the figure, and the checks toward live use that figure\.$/);
  assert.equal(g.stake[0], 'Stake');
  assert.match(g.stake[1], /“Stake not set” means/);
});

test('both themes name the dashboard’s paper P&L windows in the same words, and a focused bubble outlives a scroll', () => {
  // One set of words, in the core, that each theme takes.
  const m = /const PNL_WINDOW = (\{[^\n]*\});/.exec(read('core.js'));
  assert.ok(m);
  assert.deepEqual(new Function(`return ${m[1]};`)(), {day: 'Last 24 hours', visit: 'Since your last visit', week: 'Last 7 days', today: 'Today (UTC)', all: 'Since you started'});
  for (const f of ['app.js', 'app.meridian.js']) {
    assert.match(read(f), /\n {4}[^\n]*\bPNL_WINDOW\b[^}]*\} = window\.TauCore;/, f);
    assert.doesNotMatch(read(f), /const PNL_WINDOW\b/, f);
    assert.match(read(f), /addEventListener\('scroll', \(\) => \{ if \(current && document\.activeElement === current\) place\(current\); else hide\(\); \}, true\);/, f);
  }
  for (const f of ['app.css', 'app.meridian.css']) assert.match(read(f), /\n\.pnl-win \{ white-space: nowrap; \}/, f);
});
