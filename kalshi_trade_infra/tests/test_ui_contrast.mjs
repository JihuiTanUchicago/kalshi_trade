// Contrast and focus of the newest UI pieces, from the colour tokens both bundles define: the
// "Since your last visit" strip, the per-book backtest lines, the demo health notices, the phone
// folds and the example nudges, the research Options fold, the early "Deploy on paper" button and the
// outlined (ghost) buttons' borders. Body text needs 4.5:1, icons, borders and focus rings 3:1 (WCAG 2.1 AA). A token change that drops a pair
// below that fails here. The pages declare color-scheme light, so dark-mode browsers render the
// same tokens (checked in a browser at 390px and 1280px with Playwright: no difference).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

const read = (name) => readFileSync(new URL(`../app/static/${name}`, import.meta.url), 'utf8');

function tokens(css) {
  const root = css.match(/:root\s*\{([^}]*)\}/)[1];
  const raw = Object.fromEntries([...root.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
  const resolve = (v) => v.replace(/var\((--[\w-]+)\)/g, (_, k) => resolve(raw[k]));
  return Object.fromEntries(Object.keys(raw).map((k) => [k, resolve(raw[k])]));
}

function luminance(hex) {
  const [r, g, b] = hex.replace('#', '').match(/../g).map((h) => parseInt(h, 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => { const [x, y] = [luminance(a), luminance(b)]; return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

const PRIMARY_TEXT = '#F1F3ED';  // .btn.primary label on --ink, in both bundles
// [what, foreground token or colour, background token, needed ratio]
const PAIRS = [
  ['since strip heading, row labels, " · " and sub-lines', '--ink-3', '--stock-raised', 4.5],
  ['since strip figures and lines', '--ink', '--stock-raised', 4.5],
  ['since strip "Needs you" label', '--signal', '--stock-raised', 4.5],
  ['demo health line in a bad notice', '--ink', '--signal-wash', 4.5],
  ['demo health notice icon', '--signal', '--signal-wash', 3],
  ['demo health line on the ladder and in the strip', '--ink', '--stock-raised', 4.5],
  ['backtest line under a deployment', '--ink-3', '--stock', 4.5],
  ['backtest line on the strategy page record', '--ink-3', '--stock-raised', 4.5],
  ['backtest line on a sunk row', '--ink-3', '--stock-sunk', 4.5],
  ['example nudge text', '--ink-2', '--stock', 4.5],
  ['example and Deploy on paper buttons', PRIMARY_TEXT, '--ink', 4.5],
  ['Options title and phone fold titles', '--ink', '--stock-raised', 4.5],
  ['Options one-line summary', '--ink-3', '--stock-raised', 4.5],
  ['Options one-line summary (Meridian panel on the page)', '--ink-3', '--stock', 4.5],
  ['Deploy on paper hint', '--ink-3', '--stock', 4.5],
  ['focus ring on the page', '--ink', '--stock', 3],
  ['focus ring in a panel', '--ink', '--stock-raised', 3],
  ['focus ring on a sunk row', '--ink', '--stock-sunk', 3],
  ['focus ring on a chosen (ink) market row', '--stock-raised', '--ink', 3],
];

for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  const css = read(file);
  const t = tokens(css);
  const color = (v) => (v.startsWith('--') ? t[v] : v);

  test(`${bundle}: the new pieces' text, icons and focus rings meet WCAG AA contrast`, () => {
    const low = PAIRS.map(([what, fg, bg, need]) => [what, fg, bg, need, ratio(color(fg), color(bg))]).filter((p) => p[4] < p[3]);
    assert.deepEqual(low.map(([what, fg, bg, need, r]) => `${what}: ${fg} on ${bg} ${r.toFixed(2)} < ${need}`), []);
  });

  test(`${bundle}: an outlined (ghost) button's border meets 3:1, enabled or disabled, on every surface`, () => {
    // A ghost button is all outline, so its border is what shows it is a button (WCAG 1.4.11). Read the
    // border tokens from the rules themselves, so a rule that goes back to --rule-2 (under 2:1) fails here.
    const border = (re) => { const m = css.match(re); assert.ok(m, `missing rule ${re}`); return m[1]; };
    const states = [
      ['enabled', border(/^\.btn \{[^}]*border: 1px solid var\((--[\w-]+)\)/m)],
      ['disabled', border(/^\.btn\.ghost\[disabled\], \.btn\.ghost\[aria-disabled="true"\] \{ border-color: var\((--[\w-]+)\); \}/m)],
    ];
    const low = [];
    for (const [state, fg] of states) {
      for (const bg of ['--stock', '--stock-raised', '--stock-sunk']) {
        const r = ratio(color(fg), color(bg));
        if (r < 3) low.push(`${state} ghost border ${fg} on ${bg} ${r.toFixed(2)} < 3`);
      }
    }
    assert.deepEqual(low, []);
  });

  test(`${bundle}: switches, sliders and the chosen market row show keyboard focus`, () => {
    // `input:focus { outline: none }` is for fields, which show focus with their border. A switch and a
    // slider have no border to change, so they get their own ring; the chosen market row is ink-filled,
    // so its ring is light.
    assert.match(css, /\.input:focus, select:focus, input:focus \{[^}]*outline: none/);
    assert.match(css, /\.switch input:focus-visible, input\[type=range\]:focus-visible \{ outline: 2px solid var\(--ink\); outline-offset: 2px; \}/);
    assert.match(css, /\.mktrow-r:checked:focus-visible \+ \.mktrow-face \{ outline-color: var\(--stock-raised\); outline-offset: -4px; \}/);
    assert.match(css, /\.mktrow-r:checked \+ \.mktrow-face \{ background: var\(--ink\);/);
  });

  test(`${bundle}: only focus a script hands to a page or section drops its ring; every control keeps the ink ring`, () => {
    // <main> takes focus after a page change and a Skip to content target after the jump (tabindex -1); a
    // ring round the whole page says nothing. No other rule may switch the outline off for a control.
    assert.match(css, /^:focus-visible \{ outline: 2px solid var\(--ink\); outline-offset: 2px; \}$/m);
    const off = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{[^}]*outline: none/g)].map((m) => m[1].trim());
    assert.ok(off.includes('[tabindex="-1"]:focus'));
    assert.deepEqual(off.filter((sel) => /focus-visible|button|\.btn|a:focus|summary/.test(sel)), []);
  });
}

test('Meridian: a light chosen agent\'s-choice row keeps the ink ring', () => {
  const css = read('app.meridian.css');
  assert.match(css, /\.mktrow\.lead \.mktrow-r:checked \+ \.mktrow-face \{ background: var\(--stock-sunk\);/);
  assert.match(css, /\.mktrow\.lead \.mktrow-r:checked:focus-visible \+ \.mktrow-face \{ outline-color: var\(--ink\); \}/);
});

test('Meridian: the example nudge on Research takes its own full-width row, not the heading\'s second column', () => {
  const css = read('app.meridian.css'), js = read('app.meridian.js');
  assert.match(css, /\.research-page \{[^}]*grid-template-columns: minmax\(0, 1fr\) auto;/);
  assert.match(css, /\.research-page > #rexample \{ grid-column: 1 \/ -1; \}/);
  assert.match(js, /<div class="research-page"><h1 class="page">Research<\/h1>\$\{[^`]*`[^`]*`[^}]*\}<div id="rexample"><\/div>/);
});

test('the Alpaca paper and perps panels keep a disabled ghost button\'s 3:1 border over their own disabled rule', () => {
  // Both load after the theme stylesheet with their own `.btn:disabled { border-color: var(--rule-2) }`.
  assert.match(read('alpaca-paper.css'), /\.alpaca-paper \.btn\.ghost:disabled, \.alpaca-paper fieldset:disabled \.btn\.ghost \{ border-color: var\(--ink-3\); \}/);
  assert.match(read('kalshi-perps-live.css'), /\.kalshi-perps-live \.btn\.ghost:disabled, \.kalshi-perps-live fieldset:disabled \.btn\.ghost \{ border-color: var\(--ink-3\); \}/);
});

test('the page shell declares color-scheme light, so dark-mode browsers draw the same tested colours', () => {
  assert.match(read('index.html'), /<meta name="color-scheme" content="light">/);
  for (const file of ['app.css', 'app.meridian.css']) assert.doesNotMatch(read(file), /prefers-color-scheme/);
});
