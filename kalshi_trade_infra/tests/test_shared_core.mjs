// The shared core (core.js): the pure helpers both themes draw with alike (escaping, money, counts, dates and
// times, markdown, icons, the glossary's words, P&L lines, the track record's, Explore's and the autopilot's
// words), written once. The page runs it before the theme's bundle, which takes each helper from window.TauCore
// under its own name. These checks keep it that way: each helper is defined in the core alone, never again in a
// bundle or a page file, every name a bundle takes is one the core gives and one it uses, every core name a
// bundle uses is one it takes (a miss is a ReferenceError that blanks the page), and the core reads no page,
// account or theme, so it can't draw one theme's way.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import {codeOnly, coreSource, pageFiles} from './bundle_source.mjs';

const DIR = new URL('../app/static/', import.meta.url);
const read = (f) => readFileSync(new URL(f, DIR), 'utf8');
const BUNDLES = ['app.js', 'app.meridian.js'];
const CORE = coreSource();

// window.TauCore as the core leaves it, run on its own: a window and the language's globals, no page.
function core() {
  const context = vm.createContext({window: {}});
  vm.runInContext(CORE, context);
  return context.window.TauCore;
}
// The names a bundle takes from the core: its `const { ... } = window.TauCore;`.
const taken = (src) => {
  const m = /\n {2}const \{\n([^}]*)\n {2}\} = window\.TauCore;\n/.exec(src);
  return m ? m[1].split(',').map((n) => n.trim()).filter(Boolean) : null;
};
// What a file defines at its top level (two spaces in, inside its IIFE or TauPage callback): const, let, function.
const defined = (src) => new Set([...src.matchAll(/^ {2}(?:const|let|(?:async )?function) ([\w$]+)/gm)].map((m) => m[1])
  .concat([...src.matchAll(/^ {2}const [\w$]+ = [^\n]*?, ([\w$]+) = /gm)].map((m) => m[1])));

test('the core gives its helpers frozen, and runs with no page at all', () => {
  const all = core();
  assert.ok(Object.isFrozen(all));
  assert.ok(Object.keys(all).length >= 40, Object.keys(all).length);
  // The ones each theme's money, dates and escaping go through.
  for (const n of ['esc', 'usd', 'money', 'cents', 'num', 'when', 'settleAt', 'sinceMin', 'dateFmt', 'clipWords', 'SEP', 'WJ', 'PAPER_NET', 'NOT_MARKED']) {
    assert.ok(n in all, n);
  }
  assert.equal(all.esc('<a href="x">\'&'), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;');
  assert.equal(all.usd(-13.555), '−⁠$13.56');
  assert.equal(all.money(2), '<span class="gain">+⁠$2.00</span>');
  assert.equal(all.num(1234567), '1,234,567');
  assert.equal(all.cents(0.999), '99.9¢');
  assert.equal(all.sinceMin(null), '—');
});

test('the core reads no page, account or theme: only the language and the reader’s locale and clock', () => {
  // Its code, comments and words out (a definition may say "history"): no DOM, no storage, no network, no page
  // state (S), no other script's globals.
  const code = codeOnly(CORE);
  assert.doesNotMatch(code, /\b(?:document|location|localStorage|sessionStorage|fetch|navigator|history|addEventListener|setTimeout|setInterval)\b/);
  assert.doesNotMatch(code, /\bS\.|\bwindow\.(?!TauCore = )/);
});

for (const bundle of BUNDLES) {
  test(`${bundle} takes the core's helpers by name, each one the core gives`, () => {
    const src = read(bundle), names = taken(src), all = core();
    assert.ok(names && names.length >= 40, 'the bundle takes the helpers from window.TauCore');
    for (const n of names) assert.ok(n in all, `${bundle} takes ${n}, which the core does not give`);
    // Before anything else in the bundle runs, so every line below can call them as before.
    assert.ok(src.indexOf('= window.TauCore;') < src.indexOf("const root = document.getElementById('app');"));
    // The bundle gets the very functions the core made: the bundle and core run as the page runs them.
    const context = vm.createContext({window: {}});
    vm.runInContext(CORE, context);
    vm.runInContext(`globalThis.got = (() => { const {${names.join(', ')}} = window.TauCore; return {${names.join(', ')}}; })();`, context);
    for (const n of names) assert.equal(context.got[n], context.window.TauCore[n], n);
  });

  test(`${bundle} and its page files define none of the core's helpers again`, () => {
    const all = Object.keys(core());
    for (const f of [bundle, ...pageFiles(bundle)]) {
      const again = all.filter((n) => defined(read(f)).has(n));
      assert.deepEqual(again, [], `${f} defines ${again.join(', ')} again: take it from the core (core.js)`);
    }
  });
}

test('every helper the core gives is one a bundle takes, and both bundles take the same ones', () => {
  const all = Object.keys(core());
  const [tau, mer] = BUNDLES.map((b) => new Set(taken(read(b))));
  assert.deepEqual(all.filter((n) => !tau.has(n) && !mer.has(n)), [], 'a helper no bundle takes');
  // Both call mdInline for a strategy row's thesis line (Meridian's when the search found the row by it); only
  // Meridian's draws Explore's spot distance from its parts (its rows' own markup).
  assert.deepEqual([...tau].filter((n) => !mer.has(n)), []);
  assert.deepEqual([...mer].filter((n) => !tau.has(n)), ['TARGET_IN', 'vsText', 'vsLab', 'rowVs']);
});

test('the core keeps no dead helper: each one it defines it gives, or calls itself', () => {
  // rxTitle (a reaction chip's names, unescaped) and dirTag (an empty string) sat in the core with nothing
  // calling them: a helper no bundle can take and the core never reads is code nobody runs.
  const gives = new Set(Object.keys(core())), code = codeOnly(CORE);
  const uses = (n) => (code.match(new RegExp(`(?<![\\w$.])${n}(?![\\w$]|:)`, 'g')) || []).length;
  const dead = [...defined(CORE)].filter((n) => !gives.has(n) && uses(n) < 2);
  assert.deepEqual(dead, [], `the core defines ${dead.join(', ')} and nothing uses it`);
});

// A bundle's code with its take from the core left out, comments and words blanked (codeOnly): where it reads a
// name, and where it declares one of its own (a local or a parameter of that name is its own, not the core's).
const own = (src) => codeOnly(src).replace(/\n {2}const \{\n[^}]*\n {2}\} = window\.TauCore;\n/, '\n');
const reads = (code, n) => new RegExp(`(?<![\\w$.])${n}(?![\\w$]|:)`).test(code);  // not a property, not a key
const declares = (code, n) => new RegExp([
  `\\b(?:const|let|var|function|class)\\s+${n}\\b`,  // const n, function n
  `\\b(?:const|let|var)\\s*[{[][^=;]*?(?<![\\w$.])${n}\\b`,  // const { a, n } = …, for (const [k, n] of …)
  `\\(([^()]*?(?<![\\w$.])${n}\\b[^()]*)\\)\\s*=>`,  // (a, n) => …
  `(?<![\\w$.])${n}\\s*=>`,  // n => …
  `\\bfunction\\b[^(]*\\(([^()]*?(?<![\\w$.])${n}\\b[^()]*)\\)`,  // function f(a, n)
  `\\bcatch\\s*\\(\\s*${n}\\s*\\)`,
].join('|')).test(code);

for (const bundle of BUNDLES) {
  test(`${bundle} uses every helper it takes from the core: no dead imports`, () => {
    const src = read(bundle), code = own(src);
    // Its own code or its shared() list (what its page files get) reads each one.
    const unused = taken(src).filter((n) => !reads(code, n));
    assert.deepEqual(unused, [], `${bundle} takes ${unused.join(', ')} from the core and never uses it`);
  });

  test(`${bundle} takes every core name its code uses (a miss is a ReferenceError that blanks the page)`, () => {
    const src = read(bundle), code = own(src), names = new Set(taken(src));
    // Every name the core defines, the ones it keeps to itself too: one a bundle reads must come from the core.
    const missing = [...defined(CORE)].filter((n) => reads(code, n) && !declares(code, n) && !names.has(n));
    assert.deepEqual(missing, [], `${bundle} uses ${missing.join(', ')} without taking it from the core`);
  });

  test(`${bundle} runs on the core as the page runs it: its top level, its shared() list and every page file`, async () => {
    // A stand-in page: every DOM object anything a script asks of it, no network (reads never answer, so the
    // signed-out boot waits on /api/me), no timers. What it proves is the names: the core, then the bundle's
    // whole top level (its take from the core, every declaration, the boot calls), then its shared() list, built
    // in full as the first page file runs, then each page file taking what it asks for from that list.
    const any = () => new Proxy(function () {}, {
      get: (t, k) => (k === Symbol.toPrimitive ? () => '' : k === 'then' ? undefined : k === 'length' ? 0 : k === Symbol.iterator ? function* () {} : any()),
      apply: () => any(), construct: () => any(), set: () => true, has: () => true,
    });
    const store = {getItem: () => null, setItem() {}, removeItem() {}};
    const context = vm.createContext({
      document: any(), history: any(), navigator: any(), getComputedStyle: any, location: {pathname: '/', search: '', hash: ''},
      localStorage: store, sessionStorage: store, addEventListener() {}, removeEventListener() {}, scrollTo() {},
      matchMedia: () => ({matches: false, addEventListener() {}}), innerWidth: 1280, innerHeight: 800,
      setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {}, requestAnimationFrame: () => 0,
      fetch: () => new Promise(() => {}), MutationObserver: class { observe() {} }, IntersectionObserver: class { observe() {} },
      URL, URLSearchParams, AbortController, Intl, Blob: class {}, Event: class {},
    });
    context.window = context;
    vm.runInContext(CORE, context);
    // The boot's render() is async: what it throws comes back as its promise's rejection.
    const boot = '\n  render();\n})();';
    const src = read(bundle);
    assert.equal(src.split(boot).length, 2, 'the bundle ends with its boot');
    vm.runInContext(src.replace(boot, '\n  globalThis.booted = render();\n})();'), context);
    await Promise.race([context.booted, new Promise((resolve) => setImmediate(resolve))]);
    assert.equal(typeof context.TauPage, 'function');
    let probe = null;
    context.TauPage('probe', (T) => { probe = T; return {}; });
    // Each core name the list shares is the core's own.
    const list = /\n {2}const shared = \(\) => shareMap \|\| \(shareMap = new Proxy\(\{\n([^}]*)\n {2}\}, \{ get:/.exec(src);
    assert.ok(list, 'the bundle shares its helpers with its page files through shared()');
    const sharedNames = list[1].split(',').map((n) => n.trim()).filter(Boolean);
    for (const n of taken(src).filter((k) => sharedNames.includes(k))) assert.equal(probe[n], context.TauCore[n], n);
    for (const f of pageFiles(bundle)) vm.runInContext(read(f), context);
    // A page file both themes load (page-<name>.js) draws this theme's way by the theme this bundle shares.
    assert.equal(probe.theme, bundle === 'app.js' ? 'tau' : 'meridian');
  });
}

test('a page file both themes load takes its theme from the bundle that runs it, never from the page', () => {
  const both = pageFiles('app.js').filter((f) => pageFiles('app.meridian.js').includes(f));
  assert.deepEqual(both, ['page-admin.js', 'page-autopilot.js', 'page-community.js', 'page-explore.js', 'page-research.js', 'page-strategies.js']);
  for (const f of both) {
    const src = read(f);
    assert.match(src, /\n {4}[^\n]*\btheme\b[^}]*\n {2}\} = T;\n/, f);
    // Its code and its words, comments out: no theme read off the page (the shell's attributes, the stylesheet, the
    // html element, the theme cookie or the stored choice), and a theme named only as what the bundle shares is.
    const code = src.replace(/^\/\*[\s\S]*?\*\/\n/, '').split('\n').filter((line) => !/^\s*\/\//.test(line)).join('\n');
    const compared = code.match(/\btheme === '(?:tau|meridian)'/g) || [];
    assert.ok(compared.length, f);
    // Each `theme` in its code (its words out: a column of the admin's page errors is named "Page, theme, build") is
    // the take from the bundle or a comparison, and no string names it (a stored choice's or an attribute's key).
    assert.equal(codeOnly(src).match(/\btheme\b/g).length, compared.length + 1, `${f} reads theme only to compare it`);
    assert.doesNotMatch(code, /['"`]theme['"`]/, f);
    assert.doesNotMatch(code.replace(/\btheme === '(?:tau|meridian)'/g, ''), /__TAU_UI__|tau_ui|tau-boot|documentElement|styleSheets|\.css\b|meridian/i, f);
  }
});

test('the check finds a name used and not taken, and one taken and not used', () => {
  assert.ok(reads(own('\n  const {\n    esc\n  } = window.TauCore;\n  x(usd(1));\n'), 'usd'));
  assert.ok(!reads(own('\n  const {\n    usd\n  } = window.TauCore;\n  x(1);\n'), 'usd'), 'its own take is no use');
  assert.ok(!reads(codeOnly("  x('usd', a.usd, {usd: 1});  // usd\n"), 'usd'), 'a word, a property, a key');
  assert.ok(reads(codeOnly('  x(a ? usd : 0, {usd});\n'), 'usd'), 'a ternary, a shorthand');
  assert.ok(declares('  const f = (a, mark) => mark;\n', 'mark'));
  assert.ok(declares('  for (const [k, mark] of xs) {}\n', 'mark'));
  assert.ok(!declares('  const f = (a) => mark(a);\n', 'mark'));
});

test('the check finds a helper defined again', () => {
  assert.ok(defined('  const esc = (s) => s;\n').has('esc'));
  assert.ok(defined('  function usd(v) {}\n').has('usd'));
  assert.ok(defined("  const MD_ROW = /x/, MD_RULE = /y/;\n").has('MD_RULE'));
  assert.ok(!defined('    const esc = 1;\n').has('esc'), 'a local inside a function is its own');
  assert.deepEqual(taken('\n  const {\n    esc, usd\n  } = window.TauCore;\n'), ['esc', 'usd']);
});

// Explore walk 2026-10-31: the hot rail's compact volume read "1000.0k" for 999,960 contracts traded.
test('a compact volume that rounds up into the next unit takes it', () => {
  const {kfmt} = core();
  assert.deepEqual([0, 88, 999.4, 999.6, 9045, 99949, 999949, 999960, 1234567].map(kfmt),
    ['0', '88', '999', '1.0k', '9.0k', '99.9k', '999.9k', '1.0M', '1.2M']);
});

// First-week walk 2026-10-31: day 4's dashboard read "Today (UTC): $0.00 realized" with its last paper trade two days
// back. closedToday says whether a book closed a trade today from the newest closed rows and the book's count, and
// says it can't tell (null) when those rows can't.
test('closedToday tells a book with no trade today from one that broke even, and says when it cannot tell', () => {
  const {closedToday} = core();
  const now = Date.UTC(2026, 9, 31, 13, 0), day = Date.UTC(2026, 9, 31);
  const row = (mode, at) => ({mode, closed_at: new Date(at).toISOString()});
  const older = [row('paper', day - 3600e3), row('paper', day - 2 * 864e5)];
  assert.equal(closedToday(older, 'paper', 2, now), false, 'every paper trade listed, none today');
  assert.equal(closedToday(older, 'paper', 40, now), false, 'the oldest row listed closed before today');
  assert.equal(closedToday([row('paper', day), ...older], 'paper', 3, now), true, 'one closed at midnight UTC counts');
  assert.equal(closedToday([row('demo', day + 1000), row('demo', day + 2000)], 'paper', 4, now), null, 'other books today, paper unlisted');
  assert.equal(closedToday([], 'paper', 0, now), false);
  assert.equal(closedToday(undefined, 'paper', undefined, now), false);
});
