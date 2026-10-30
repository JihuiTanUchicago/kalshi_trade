// The shared core (core.js): the pure helpers both themes draw with alike (escaping, money, counts, dates and
// times, markdown), written once. The page runs it before the theme's bundle, which takes each helper from
// window.TauCore under its own name. These checks keep it that way: each helper is defined in the core alone,
// never again in a bundle or a page file, every name a bundle takes is one the core gives, and the core reads
// no page, account or theme, so it can't draw one theme's way.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import {coreSource, pageFiles} from './bundle_source.mjs';

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
  // Its code, comments out: no DOM, no storage, no network, no page state (S), no other script's globals.
  const code = CORE.replace(/^\/\*[\s\S]*?\*\//, '').split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n').replace(/\s\/\/ .*$/gm, '');
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
  // Only Tau's bundle calls mdInline itself (its strategy table's thesis line).
  assert.deepEqual([...tau].filter((n) => !mer.has(n)), ['mdInline']);
  assert.deepEqual([...mer].filter((n) => !tau.has(n)), []);
});

test('the check finds a helper defined again', () => {
  assert.ok(defined('  const esc = (s) => s;\n').has('esc'));
  assert.ok(defined('  function usd(v) {}\n').has('usd'));
  assert.ok(defined("  const MD_ROW = /x/, MD_RULE = /y/;\n").has('MD_RULE'));
  assert.ok(!defined('    const esc = 1;\n').has('esc'), 'a local inside a function is its own');
  assert.deepEqual(taken('\n  const {\n    esc, usd\n  } = window.TauCore;\n'), ['esc', 'usd']);
});
