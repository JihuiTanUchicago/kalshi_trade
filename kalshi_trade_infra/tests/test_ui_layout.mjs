// Desktop table layout with long content, both bundles: long strategy titles, big signed figures and long
// market names at 1024-1920px, without changing the 390px stacked phone tables. Checked in a browser with
// Playwright at 1024, 1280, 1440, 1920 and 390 against seeded long titles and five-figure P&L; these
// tests pin the rules that fixed it, read from the stylesheets.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {bundleSource} from './bundle_source.mjs';

// A theme bundle reads with its page files (bundle_source.mjs), wherever a view's code now lives.
const read = (name) => (/^app(?:\.meridian)?\.js$/.test(name) ? bundleSource(name) : readFileSync(new URL(`../app/static/${name}`, import.meta.url), 'utf8'));

// Every style rule as {media, sel, body}; `media` is the enclosing @media prelude ('' at the top level).
function rules(css) {
  const src = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const out = [];
  const walk = (text, media) => {
    let i = 0;
    while (i < text.length) {
      const open = text.indexOf('{', i);
      if (open < 0) break;
      const prelude = text.slice(i, open).trim();
      let depth = 1, j = open + 1;
      while (j < text.length && depth) { if (text[j] === '{') depth++; else if (text[j] === '}') depth--; j++; }
      const body = text.slice(open + 1, j - 1);
      if (prelude.startsWith('@media') || prelude.startsWith('@container') || prelude.startsWith('@supports')) walk(body, prelude);
      else if (!prelude.startsWith('@')) out.push({media, sel: prelude.replace(/\s+/g, ' '), body});
      i = j;
    }
  };
  walk(src, '');
  return out;
}
const sels = (r) => r.sel.split(',').map((s) => s.trim());
// The declarations that apply to `selector` (an exact selector in a rule's list) under `media`.
function decl(all, selector, prop, media = '') {
  const hits = all.filter((r) => r.media === media && sels(r).includes(selector))
    .map((r) => (r.body.match(new RegExp(`(?:^|;|\\s)${prop}\\s*:\\s*([^;]+)`)) || [])[1]).filter(Boolean);
  return hits.length ? hits[hits.length - 1].trim() : undefined;
}
const DESKTOP = '@media (min-width: 761px)';
const PHONE = '@media (max-width: 760px)';

for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  const css = read(file);
  const all = rules(css);

  test(`${bundle}: the stylesheet's braces balance`, () => {
    const src = css.replace(/\/\*[\s\S]*?\*\//g, '');
    assert.equal((src.match(/\{/g) || []).length, (src.match(/\}/g) || []).length);
  });

  test(`${bundle}: a long title keeps a readable Strategy column on the Strategies list (desktop only)`, () => {
    // The one-line Market and Status cells used to squeeze a 70-character title to a word a line.
    const min = decl(all, '.t-strat td.name', 'min-width', DESKTOP);
    assert.ok(min && parseFloat(min) >= 12 && min.endsWith('em'), `t-strat title min-width ${min}`);
    assert.equal(decl(all, '.t-strat td[data-lab="Market"]', 'white-space', DESKTOP), 'normal');
    assert.equal(decl(all, '.t-strat td.st', 'white-space', DESKTOP), 'normal');
    // Not at the top level, where it would also size the phone's stacked cell.
    assert.equal(decl(all, '.t-strat td.name', 'min-width'), undefined);
  });

  test(`${bundle}: the Deploy board's Strategy column holds its width and the short cells wrap first`, () => {
    if (bundle === 'Tau') {
      const min = decl(all, '.t-dep td.name', 'min-width', DESKTOP);
      assert.ok(min && parseFloat(min) >= 12 && min.endsWith('em'), `t-dep title min-width ${min}`);
      for (const sel of ['.t-dep td[data-lab="Market"]', '.t-dep td[data-lab="Status"]', '.t-dep th.num', '.t-dep td.act']) {
        assert.equal(decl(all, sel, 'white-space', DESKTOP), 'normal', sel);
      }
    } else {
      // Meridian's board already held its title column; the phone resets it.
      assert.equal(decl(all, '.t-dep td.name', 'min-width'), '210px');
      assert.equal(decl(all, '.t-dep.stack tbody td.name', 'min-width', PHONE), '0');
    }
  });

  test(`${bundle}: the track record's By strategy titles wrap instead of scrolling the figures out of view`, () => {
    assert.equal(decl(all, '.trpanel td.name', 'white-space'), 'normal');
    assert.ok(parseFloat(decl(all, '.trpanel td.name', 'min-width')) >= 12);
  });

  test(`${bundle}: the Funds paper history gives the memo the room, and an amount never breaks`, () => {
    // Fixed layout split it into equal thirds; When and Amount now take a set width.
    assert.equal(decl(all, '.funds-page .funds-col table', 'table-layout'), 'fixed');
    assert.ok(decl(all, '.funds-page .t-ledger th:first-child', 'width'), 'When column width');
    assert.ok(decl(all, '.funds-page .t-ledger th.num', 'width'), 'Amount column width');
    assert.equal(decl(all, '.funds-page .t-ledger td.num', 'white-space'), 'nowrap');
    assert.equal(decl(all, '.funds-page .t-ledger td.num', 'overflow-wrap'), 'normal');
  });

  test(`${bundle}: a signed figure never breaks between its sign and the $ or inside the digits`, () => {
    for (const sel of ['span.gain', 'span.loss', 'b.gain', 'b.loss', '.amt']) assert.equal(decl(all, sel, 'white-space'), 'nowrap', sel);
  });

  test(`${bundle}: numeric columns stay right-aligned with tabular figures`, () => {
    assert.equal(decl(all, 'td.num', 'text-align'), 'right');
    assert.match(decl(all, 'td.num', 'font-variant-numeric'), /tabular-nums/);
  });

  test(`${bundle}: phone tables still stack, with each cell labelled from data-lab`, () => {
    assert.equal(decl(all, '.stack tbody td', 'display', PHONE), 'flex');
    assert.equal(decl(all, '.stack tbody td', 'white-space', PHONE), 'normal');
    assert.equal(decl(all, '.stack tbody td::before', 'content', PHONE), 'attr(data-lab)');
    assert.equal(decl(all, '.stack thead', 'position', PHONE), 'absolute');
  });
}

test('Meridian: a deployment monitor keeps each figure on one line in its own column', () => {
  // At 1280 a +$14,444.55 realized broke as "+$14,444.5 / 5" in a minmax(0, 1fr) column.
  const all = rules(read('app.meridian.css'));
  assert.equal(decl(all, '.monitor-metrics', 'grid-template-columns'), 'repeat(2, minmax(min-content, 1fr))');
  assert.equal(decl(all, '.monitor-metrics dd', 'overflow-wrap'), undefined);
});

test('Meridian: the research form\'s Options are one column, so the market picker and the model name have room', () => {
  // Walked 2026-10-26: `.research-compose .dispatch-tune` (the form's second column) also applied inside
  // Options and made a second column there: the market picker was ~90px wide ("Filter" cut, "Agent's
  // choice" on two lines) and the model select read "Claude" on a desktop, the same squeeze on a phone.
  const all = rules(read('app.meridian.css'));
  assert.equal(decl(all, '.research-compose .dispatch-tune', 'grid-column'), '2');  // the form's own layout, unchanged
  assert.equal(decl(all, '.research-compose .dispatch-opts-body > .dispatch-tune', 'grid-column'), '1');
  assert.equal(decl(all, '.research-compose .dispatch-opts-body > .dispatch-tune', 'grid-row'), 'auto');
});

test('Tau: with the markets rail open, every Deploy action fits on the board and nothing scrolls the page', () => {
  // Walked 2026-10-27 at 1024-1440, rail open and closed: at 1100-1280 with the rail open the ~935px board
  // had 745-920px, so Resume and Remove sat past the sheet's edge ("RESUM", "REMOV"), and their hidden
  // labels (position: absolute, outside the sheet's clip) scrolled the whole page sideways at 1100.
  const all = rules(read('app.css'));
  assert.match(read('app.js'), /const deploymentTable = [^\n]*<div class="sheet dep-sheet"><table class="stack t-dep">/);
  assert.equal(decl(all, '.dep-sheet', 'container'), 'deployments / inline-size');
  assert.equal(decl(all, '.dep-sheet', 'position'), 'relative');  // the sheet clips its hidden labels
  const NARROW = '@container deployments (max-width: 1040px)';
  // Desktop only: the phone stacks the rows, and its sparkline and cells keep their own sizes.
  const narrow = all.filter((r) => r.media === NARROW);
  assert.ok(narrow.length && /@media \(min-width: 761px\) \{\s*@container deployments/.test(read('app.css').replace(/\/\*[\s\S]*?\*\//g, '')));
  for (const sel of ['.t-dep td[data-lab="Backtest estimate"]', '.t-dep td[data-lab="Since"]', '.t-dep th']) {
    assert.equal(decl(all, sel, 'white-space', NARROW), 'normal', sel);
  }
  assert.ok(parseFloat(decl(all, '.t-dep th', 'padding-left', NARROW)) < 12);
  assert.ok(parseFloat(decl(all, '.t-dep td.name', 'min-width', NARROW)) >= 10);  // the title still reads
  assert.ok(parseFloat(decl(all, '.t-dep .spark', 'width', NARROW)) < parseFloat(decl(all, '.spark', 'width')));
});

test('Tau: the dashboard paper line keeps its all-time figure whole, and a clamped session title has a tooltip', () => {
  const js = read('app.js');
  assert.match(js, /<span class="amt">\$\{usd\(p\.realized_pnl, true\)\}<\/span> realized all time/);
  assert.match(js, /<span class="run-title"><b title="\$\{esc\(sessionTitle\(r\)\)\}">/);
});

// Tap targets from the accessibility pass (2026-10-27, Playwright at 390px with a coarse pointer, both
// themes): links set in a line of figures (the "Since your last visit" strip, the autopilot card) and a
// held contract's ticker measured 16-20px tall, Tau's research result titles 20px and a post's Reply, Edit
// and reactions 25-28px. Each reaches 40px under a coarse pointer, the inline ones without moving the line;
// Tau's small buttons (Pause, Remove) reach WCAG 2.2's 24px on a desktop.
const COARSE = '@media (pointer: coarse)';
const px = (v) => parseFloat(v);
for (const [bundle, file, extra] of [['Tau', 'app.css', ['.ri-why a']], ['Meridian', 'app.meridian.css', []]]) {
  const all = rules(read(file));
  test(`${bundle}: links in a line of figures and a contract's ticker are 40px tall to a thumb, the line left alone`, () => {
    for (const sel of ['.since-row dd a', '.apcard-figs dd a', '.tick a', ...extra]) {
      const pad = decl(all, sel, 'padding-block', COARSE), margin = decl(all, sel, 'margin-block', COARSE);
      assert.ok(pad && 16 + 2 * px(pad) >= 40, `${sel}: padding-block ${pad}`);
      assert.equal(px(margin), -px(pad), `${sel}: the margin gives the padding back`);
    }
    assert.ok(24 + 2 * px(decl(all, 'a.apcard-alt', 'padding-block', COARSE)) >= 40);  // "or research by hand", 24px tall
    assert.equal(decl(all, '.dispatch-go .ex-run', 'min-height', COARSE), '40px');
  });
}

test('Tau: a research result\'s title and a post\'s Reply, Edit and reactions are 40px to a thumb; a small button is 24px on a desktop', () => {
  const all = rules(read('app.css'));
  const pad = px(decl(all, '.ri-title', 'padding-block', COARSE));
  assert.ok(20 + 2 * pad >= 40);
  assert.equal(px(decl(all, '.ri-title', 'margin-block', COARSE)), -pad);
  assert.equal(decl(all, '.post-actions .thread-link', 'min-height', COARSE), '40px');
  assert.equal(decl(all, '.reactions .rx', 'min-height', COARSE), '40px');
  assert.equal(decl(all, '.btn.sm', 'min-height'), '24px');
});

// Walk 2026-10-27 (Meridian, 390x844, Tau the same): the open autopilot sheet's close button reaches 2px from the
// screen's right edge and 1px from its top (its 44px target's negative margin into the header's padding), so the
// focus ring drawn 2px outside it was cut off on the right and at the top. The ring sits inside the button there.
const SHEET = '@media (max-width: 600px)';
for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  test(`${bundle}: on a phone the open autopilot sheet's close button shows its whole focus ring`, () => {
    const all = rules(read(file));
    const [padTop, padRight] = decl(all, '.apf-head', 'padding').split(/\s+/).map(px);
    const [marginTop, marginRight] = decl(all, '.apf-x', 'margin', COARSE).split(/\s+/).map(px);
    const room = Math.min(padTop + marginTop, padRight + marginRight);  // between the button and the screen's edges
    assert.ok(room >= 0 && room < 4, `the button sits ${room}px from the edge`);
    const width = px(decl(all, ':focus-visible', 'outline'));
    const offset = px(decl(all, '.apf.open .apf-x:focus-visible', 'outline-offset', SHEET) ?? decl(all, ':focus-visible', 'outline-offset'));
    assert.ok(width + offset <= room, `the ring reaches ${width + offset}px outside the button, ${room}px from the edge`);
    assert.ok(width + offset <= 0 && -offset < 22, 'inside the button and clear of its icon');
  });
}

// Walk 2026-10-27 (390px phone): content sat under the floating autopilot pill (Billing's "Add another card" form,
// a market page's settlement note). The room under every page is now worked out from the pill's own offset and
// height, which the pill itself is placed and sized by, so the two can't drift apart; the pill keeps to one line
// so its height is that figure, and an iPhone's home-indicator strip is added on top. Tau's collapsed pill floats;
// Meridian's sits in the masthead (in the page's flow), so nothing there can cover a page's foot.
const PHONE_SHEET = '@media (max-width: 600px)';
const tokens = (all, media = '') => Object.fromEntries(all.filter((r) => r.media === media && sels(r).includes(':root'))
  .flatMap((r) => [...r.body.matchAll(/(--apf-[\w-]+)\s*:\s*([^;]+)/g)].map((m) => [m[1], m[2].trim()])));
test('Tau: every page leaves room under its last line for the floating autopilot pill, its offset and height, on a phone and a desktop', () => {
  const all = rules(read('app.css'));
  const desk = tokens(all), phone = {...desk, ...tokens(all, PHONE_SHEET)}, thumb = {...phone, ...tokens(all, COARSE)};
  // The pill is placed by the offset and, to a thumb, sized by the height the padding counts.
  assert.equal(decl(all, '.apf', 'position'), 'fixed');
  assert.equal(decl(all, '.apf', 'bottom'), 'var(--apf-gap)');
  assert.equal(decl(all, '.apf', 'right'), 'var(--apf-gap)');
  assert.equal(decl(all, '.apf-pill', 'min-height', COARSE), 'var(--apf-h)');
  assert.equal(decl(all, '.apf-pill', 'white-space'), 'nowrap', 'one line, so its height is --apf-h');
  assert.equal(decl(all, '.apf', 'bottom', PHONE_SHEET), undefined, 'a phone moves the pill by the token, not a fixed number');
  const pad = decl(all, 'body:not(.landing-body)', 'padding-bottom');
  const m = /^calc\(var\(--apf-gap\) \+ var\(--apf-h\) \+ (\d+)px \+ env\(safe-area-inset-bottom, 0px\)\)$/.exec(pad || '');
  assert.ok(m, `padding-bottom ${pad}`);
  for (const [where, t] of [['desktop', desk], ['phone', phone], ['phone, thumb', thumb]]) {
    const room = px(t['--apf-gap']) + px(t['--apf-h']) + +m[1];
    const pill = px(t['--apf-gap']) + px(t['--apf-h']) + 8;  // apYield's 8px margin round the pill
    assert.ok(room >= pill + 12, `${where}: ${room}px of room under a ${pill}px pill strip`);
  }
  assert.equal(phone['--apf-gap'], '10px'); assert.equal(thumb['--apf-h'], '40px');
  // The pill's measured height (Playwright, 390px): 40px to a thumb, 37px with a mouse.
  assert.ok(px(desk['--apf-h']) >= 37);
});
test('Meridian: the collapsed autopilot pill sits in the masthead, so it never covers a page\'s foot', () => {
  const all = rules(read('app.meridian.css'));
  assert.equal(decl(all, '.apf', 'position'), 'relative');
  assert.equal(decl(all, '.apf.open', 'position'), 'fixed', 'only the opened panel floats, over the page by choice');
  assert.match(read('app.meridian.js'), /root\.querySelector\('\.masthead-in'\)\.appendChild\(box\)/);
});
