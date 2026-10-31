// Desktop table layout with long content, both bundles: long strategy titles, big signed figures and long
// market names at 1024-1920px, without changing the 390px stacked phone tables. Checked in a browser with
// Playwright at 1024, 1280, 1440, 1920 and 390 against seeded long titles and five-figure P&L; these
// tests pin the rules that fixed it, read from the stylesheets.
import assert from './assert_text.mjs';
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

  test(`${bundle}: the Strategies list's Backtest P&L line wraps under its figure, so Status stays on the sheet at 1280`, () => {
    // "later-period P&L over 9 days after the split date, which picked it: not held out" ran on one line (~440px):
    // with Tau's markets rail open at 1280 it pushed Ideas tested and Status past the sheet's edge (walked 2026-10-27).
    assert.equal(decl(all, '.t-strat td.num .sub-fig', 'white-space', DESKTOP), 'normal');
    const max = decl(all, '.t-strat td.num .sub-fig', 'max-width', DESKTOP);
    assert.ok(max && max.endsWith('ch') && parseFloat(max) >= 20 && parseFloat(max) <= 30, `max-width ${max}`);
    assert.equal(decl(all, '.t-strat td.num .sub-fig', 'margin-left', DESKTOP), 'auto');  // right-aligned under its figure
  });

  test(`${bundle}: a phone's Strategies card reads the Backtest P&L line's short form, and the full one stays for a screen reader`, () => {
    // At 390px the full line ("later-period P&L over 9 days after the split date, which picked it: not held out") ran
    // about five lines in its third of the card, saying "P&L" again under "BACKTEST P&L" (walked 2026-10-28).
    assert.equal(decl(all, '.bt-sub .bt-short', 'display'), 'none');  // desktop keeps the full sentence
    assert.equal(decl(all, '.t-strat.stack tbody td.num .bt-short', 'display', PHONE), 'inline');
    // Hidden only visually on a phone (as .vh is), never display:none, so the sentence is still what is read out.
    const long = '.t-strat.stack tbody td.num .bt-long';
    assert.equal(decl(all, long, 'display', PHONE), undefined);
    assert.equal(decl(all, long, 'position', PHONE), 'absolute');
    assert.equal(decl(all, long, 'clip', PHONE), 'rect(0 0 0 0)');
    assert.equal(decl(all, long, 'width', PHONE), '1px'); assert.equal(decl(all, long, 'overflow', PHONE), 'hidden');
    assert.equal(decl(all, '.bt-sub .bt-long', 'display'), undefined);
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
    // The clipped header row keeps its column names for a screen reader, but not its (i) buttons: Tab landed on
    // Deploy's Realized, Unrealized and Backtest estimate there, drawn nowhere, their definitions beside nothing.
    assert.equal(decl(all, '.stack thead .info', 'display', PHONE), 'none');
    assert.equal(decl(all, '.stack thead .info', 'display'), undefined, 'a desktop table keeps them');
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
  assert.match(js, /\$\{pnlWin\('all'\)\} <span class="amt">\$\{usd\(p\.realized_pnl, true\)\}<\/span> \$\{gl\('realized', 'realized'\)\}/);
  // The card shows the title cut at a whole word (clipWords, test_word_clip.mjs); the tooltip has it whole.
  assert.match(js, /const title = sessionTitle\(r\);/);
  assert.match(js, /<span class="run-title"><b title="\$\{esc\(title\)\}">\$\{esc\(clipWords\(title, RUN_TITLE_MAX\)\)\}<\/b>/);
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
    // The since strip's links are boxes in their own lines now (the overlap tests at the end of this file).
    for (const sel of ['.apcard-figs dd a', '.tick a', ...extra]) {
      const pad = decl(all, sel, 'padding-block', COARSE), margin = decl(all, sel, 'margin-block', COARSE);
      assert.ok(pad && 16 + 2 * px(pad) >= 40, `${sel}: padding-block ${pad}`);
      assert.equal(px(margin), -px(pad), `${sel}: the margin gives the padding back`);
    }
    assert.ok(24 + 2 * px(decl(all, 'a.apcard-alt', 'padding-block', COARSE)) >= 40);  // "or research by hand", 24px tall
    assert.equal(decl(all, '.dispatch-go .ex-run', 'min-height', COARSE), '44px');
  });
}

test('Tau: a research result\'s title and a post\'s Reply, Edit and reactions are 44px to a thumb; a small button is 24px on a desktop', () => {
  const all = rules(read('app.css'));
  const pad = px(decl(all, '.ri-title', 'padding-block', COARSE));
  assert.ok(20 + 2 * pad >= 44);
  assert.equal(px(decl(all, '.ri-title', 'margin-block', COARSE)), -pad);
  assert.equal(decl(all, '.post-actions .thread-link', 'min-height', COARSE), '44px');
  assert.equal(decl(all, '.reactions .rx', 'min-height', COARSE), '44px');
  assert.equal(decl(all, '.reactions .rx', 'min-width', COARSE), '44px');  // the "+" add-a-reaction was 43px wide
  assert.equal(decl(all, '.composer-post textarea', 'min-height', COARSE), '44px');
  assert.equal(decl(all, '.btn.sm', 'min-height'), '24px');
});

// Walk 2026-10-30 at 390px: Tau's pinned Community composer took about a quarter of the screen and covered the bottom of
// an open thread, its reply box with it, until the feed was scrolled. On a phone, while a thread or an edit box is open,
// the composer is unpinned (it waits at the feed's end); desktop keeps it pinned. Meridian's composer is never pinned:
// it opens from "New post" above the feed, so nothing floats over a thread there.
test('Tau: on a phone the Community composer stops floating over an open thread or edit box; desktop keeps it pinned', () => {
  const all = rules(read('app.css'));
  const FEED_PHONE = '@media (max-width: 680px)';
  assert.equal(decl(all, '.composer-post', 'position'), 'sticky');
  assert.equal(decl(all, '.composer-post', 'bottom'), '12px');
  for (const sel of ['.feedwrap:has(#feed .comments:not([hidden])) .composer-post', '.feedwrap:has(#feed .edit-form) .composer-post']) {
    assert.equal(decl(all, sel, 'position', FEED_PHONE), 'static', sel);
    assert.equal(decl(all, sel, 'position'), undefined, `${sel} only on a phone`);
    for (const r of all.filter((x) => sels(x).includes(sel))) assert.equal(r.media, FEED_PHONE, sel);
  }
});

test('Meridian: the Community composer is never pinned over the feed', () => {
  const all = rules(read('app.meridian.css'));
  for (const r of all.filter((x) => /\.composer-post|\.community-compose/.test(x.sel))) {
    assert.doesNotMatch(r.body, /position\s*:\s*(sticky|fixed)/, `${r.media} ${r.sel}`);
  }
  // Its New post form sits above the feed in the page's markup (page-community.js, Meridian's layout of it).
  const page = readFileSync(new URL('../app/static/page-community.js', import.meta.url), 'utf8');
  assert.match(page, /\n {4}const composer = `<form class="panel composer-post" id="composer-post"/);
  assert.match(page, /\n {4}const feedHtml = `<div id="feed-note"><\/div>\n {8}<div id="feed">/);
  const meridian = page.slice(page.indexOf('<div class="feedwrap"><div class="community-heading">'));
  assert.ok(meridian.indexOf('${composer}') > 0 && meridian.indexOf('${composer}') < meridian.indexOf('${feedHtml}'), 'the form comes before the feed');
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

// Walk 2026-10-30 (390px phone, Meridian): the open autopilot sheet is one scroll (page-autopilot.js scrolls the sheet to
// a sent message and its answer), but Meridian's activity feed kept the research log's 52vh cap, so it was a 440px scroll
// of its own inside the sheet: a long reply scrolled in that box while the sheet scrolled around it. On the phone sheet
// neither bundle caps the feed; it takes its full height and the sheet scrolls it.
for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  test(`${bundle}: on a phone the open autopilot sheet is the one scroll, its activity feed uncapped`, () => {
    const all = rules(read(file));
    assert.equal(decl(all, '.apf.open', 'overflow-y', SHEET), 'auto', 'the sheet scrolls');
    assert.equal(decl(all, '.apf.open .apf-session', 'flex', SHEET), 'none', 'the session takes its own height');
    const cap = decl(all, '.apf.open .log.stream.apf-log', 'max-height', SHEET) ?? decl(all, '.apf .log.stream.apf-log', 'max-height')
      ?? decl(all, '.log.stream', 'max-height');
    assert.ok(cap === undefined || cap === 'none', `the feed is capped at ${cap} inside the sheet`);
    assert.equal(decl(all, '.apf .log.stream.apf-log', 'height'), 'auto', 'and sized by what it holds');
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
// Walk 2026-10-27 at 390px: a stacked Deploy card set its seven figures three across, which left Since alone on a
// fourth row under two empty columns. The backtest estimate (its two-line label over a two-line figure, the card's
// tallest cell) spans two rows, so Since sits under Market beside it and the card is a row shorter. The rule is the
// phone's only, inside the card's grid (three columns); Meridian's Deploy rows have no such grid and are unchanged.
test('Tau: on a phone a Deploy card tucks Since under Market beside the two-row backtest estimate, not alone on a row', () => {
  const all = rules(read('app.css'));
  assert.equal(decl(all, '.t-dep.stack tbody td[data-lab="Backtest estimate"]', 'grid-row', PHONE), 'span 2');
  assert.equal(decl(all, '.t-dep.stack tbody tr', 'grid-template-columns', PHONE), 'repeat(3, minmax(0, 1fr))');
  // Money first: the backtest estimate keeps its place in the first column after the three money figures.
  assert.equal(decl(all, '.t-dep.stack tbody td[data-lab="Since"]', 'order', PHONE), '1');
  assert.equal(decl(all, '.t-dep.stack tbody td[data-lab="Backtest estimate"]', 'order', PHONE), undefined);
  assert.equal(decl(all, '.t-dep.stack tbody td[data-lab="Backtest estimate"]', 'grid-row'), undefined, 'not on a desktop table');
  assert.ok(!rules(read('app.meridian.css')).some((r) => /td\[data-lab="Backtest estimate"\]/.test(r.sel) && /grid-row/.test(r.body)));
});

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
  assert.equal(phone['--apf-gap'], '10px'); assert.equal(thumb['--apf-h'], '44px');
  // The pill's measured height (Playwright, 390px): 44px to a thumb, 37px with a mouse.
  assert.ok(px(desk['--apf-h']) >= 37);
});
test('Meridian: the collapsed autopilot pill sits in the masthead, so it never covers a page\'s foot', () => {
  const all = rules(read('app.meridian.css'));
  assert.equal(decl(all, '.apf', 'position'), 'relative');
  assert.equal(decl(all, '.apf.open', 'position'), 'fixed', 'only the opened panel floats, over the page by choice');
  assert.match(read('app.meridian.js'), /root\.querySelector\('\.masthead-in'\)\.appendChild\(box\)/);
});

// Walk 2026-10-27 at 390px: the System map was a fixed 640px picture scrolled sideways inside its frame (the research
// box at x 537). It now draws a phone layout as wide as the column (sysPhoneLayout), so on a phone the picture is the
// frame's width, as on a desktop, and nothing in the frame scrolls sideways; turned to landscape it keeps to a
// phone's width rather than growing huge. Its stage arrows are drawn as lines, not filled shapes.
for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  test(`${bundle}: on a phone the System map fits its frame instead of scrolling sideways in it`, () => {
    const all = rules(read(file));
    assert.equal(decl(all, '.sys-wrap svg', 'width'), '100%');
    assert.equal(decl(all, '.sys-wrap svg', 'width', PHONE), undefined, 'no fixed phone width');
    assert.equal(decl(all, '.sys-wrap svg', 'max-width', PHONE), undefined);
    for (const media of ['', PHONE]) assert.equal(decl(all, '.sys-wrap', 'overflow-x', media), undefined, 'the frame does not scroll sideways');
    assert.equal(decl(all, '.sys-wrap svg.sys-stack', 'max-width'), '420px');
    assert.equal(decl(all, '.sys-tier', 'fill'), 'none');
  });
}

// Walk 2026-10-27 at 390px: on Deploy's stacked open-position cards each Unrealized figure's "as of" time sat on a
// row of its own under the card's labels. It is in the figure's own block (pos-unreal), set close under the figure.
for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  test(`${bundle}: a stacked open position's mark time sits close under its Unrealized figure`, () => {
    const all = rules(read(file));
    assert.equal(decl(all, '.stack tbody td .pos-unreal .sub-fig', 'margin-top', PHONE), '1px');
    assert.equal(decl(all, '.stack tbody td .pos-unreal', 'display', PHONE), undefined, 'a block: its time goes under the figure, not beside it');
  });
}

// Walk 2026-10-27 at 390px: Meridian's Strategies title read "Strategie / s". h1.page wrapped with overflow-wrap:
// anywhere, which lets a flex item shrink below its longest word, so beside the pass-rate summary the title took one
// letter's width. Every page title (h1.page, both themes) now breaks only an overlong token, and only at the column's edge.
for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  test(`${bundle}: a page title wraps between words and never shrinks below its longest word`, () => {
    const all = rules(read(file));
    assert.equal(decl(all, 'h1.page', 'overflow-wrap'), 'break-word');
    assert.equal(decl(all, 'h1.page', 'max-width'), '100%', 'one overlong token still breaks inside the column');
    for (const media of ['', PHONE]) {
      assert.ok(!all.some((r) => r.media === media && sels(r).some((s) => /h1\b/.test(s)) && /overflow-wrap\s*:\s*anywhere|word-break\s*:\s*break-all/.test(r.body)),
        'no title rule breaks inside words');
    }
  });
}

// A Void, Rejected or missed-final strategy's page figure is drawn untinted inside .pnl-nopass: it takes the muted ink
// its Strategies row and Community card use, from the theme's own token, never a hard-coded colour.
for (const [bundle, file, sel] of [['Tau', 'app.css', '.fig .pnl-nopass'], ['Meridian', 'app.meridian.css', '#figs .fig .pnl-nopass']]) {
  test(`${bundle}: a strategy that did not pass has its page figure muted with the theme’s ink`, () => {
    const all = rules(read(file));
    assert.equal(decl(all, sel, 'color'), 'var(--ink-3)');
    assert.equal(decl(all, '.t-strat .pnl-nopass', 'color'), 'var(--ink-3)');
  });
}

// Walk 2026-10-28, Meridian's Overview at 390px: inside a closed Details (.dep-evidence), each .dep-fact measured past
// the right edge (to 440px). That box is the closed details' hidden content, sized to the 84px "Details" summary, with
// each fact unbreakable inside: nothing shows there and the page never scrolls sideways. Opened, the details takes the
// card's whole row (358px of 390, 288 of 320) and every fact fits, wrapping only between facts. These rules keep it so.
test('Meridian: an opened deployment Details takes its row and wraps between facts, never inside one', () => {
  const all = rules(read('app.meridian.css'));
  assert.equal(decl(all, '.dep-evidence[open]', 'display'), 'block', 'opened, it is no longer the inline summary’s width');
  assert.equal(decl(all, '.dep-evidence > div', 'white-space'), 'normal', 'the line wraps between facts');
  assert.equal(decl(all, '.dep-evidence .dep-fact', 'white-space'), 'nowrap', '“Deployed” stays with its date');
  assert.equal(decl(all, '.dep-monitor .dep-evidence[open]', 'flex-basis'), '100%');
  assert.equal(decl(all, '.monitor-footer:has(.dep-evidence[open])', 'grid-column'), '1 / -1', 'an Overview card gives it the full width');
  assert.equal(decl(all, '.dep-monitor .dep-evidence > div', 'overflow-wrap'), 'anywhere', 'an overlong token still breaks at the edge');
  assert.ok(!all.some((r) => sels(r).some((s) => /\.dep-evidence > div$/.test(s)) && /white-space\s*:\s*nowrap/.test(r.body)),
    'no rule, at any width, stops the details line wrapping');
});

// Walk 2026-10-28, Meridian's Overview at 390px: opening a card's Details pushed Realized and Unrealized P&L below it.
// The wide card's opened footer takes "grid-row: 3" through :has, which outranked the one-column card's "grid-row: auto",
// so in one column the footer sat in row 3 and the figures fell to row 4. One column, it follows the figures in order.
test('Meridian: opening an Overview card’s Details keeps its Realized and Unrealized P&L above it at any width', () => {
  const all = rules(read('app.meridian.css'));
  const ONE = '@container deployment-ledger (max-width: 399px)', TWO = '@container deployment-ledger (max-width: 639px)';
  const opened = '.dep-monitor .monitor-footer:has(.dep-evidence[open])';
  assert.equal(decl(all, opened, 'grid-row', ONE), 'auto', 'one column: after the figures, as the page orders it');
  assert.equal(decl(all, opened, 'grid-column', ONE), '1');
  assert.equal(decl(all, '.monitor-metrics', 'grid-row', ONE), 'auto');
  // Wider, the figures keep rows 1–2 beside the name and setup, and the opened Details takes row 3 under all of them.
  assert.equal(decl(all, '.monitor-metrics', 'grid-row'), '1 / span 2');
  assert.equal(decl(all, '.monitor-footer:has(.dep-evidence[open])', 'grid-row'), '3');
  assert.equal(decl(all, '.monitor-footer', 'grid-row', TWO), '3');
  assert.equal(decl(all, '.monitor-metrics', 'grid-row', TWO), undefined, 'two columns: the figures keep their rows');
});

// The same walk: a demo card's “after Kalshi fees, in Tau’s demo book: not real money” (.book-net) ran four lines at the
// Realized figure's 20px under “−$2.10”. It is the small print the paper card's “after Kalshi fees and the spread” is.
test('Meridian: a demo or live Overview card’s book line under Realized P&L is small print, not a figure', () => {
  const all = rules(read('app.meridian.css'));
  for (const sel of ['.monitor-metrics dd.paper-net', '.monitor-metrics dd.book-net']) {
    assert.match(decl(all, sel, 'font') || '', /^400 12px\/16px /, sel);
    assert.equal(decl(all, sel, 'color'), 'var(--ink-3)', sel);
  }
});

// Tau's empty track-record tab is a dashed box, and its caveat line pulls up 4px to sit close under the figures: under
// the box that ran its first line through the bottom border (walked 2026-10-28). Meridian's empty state has no border.
test('Tau: a track-record caveat keeps clear of an empty tab’s dashed box', () => {
  const tau = rules(read('app.css'));
  assert.equal(decl(tau, '.tr-caveat', 'margin'), '-4px 0 12px');
  assert.ok(parseFloat(decl(tau, '.empty + .tr-caveat', 'margin-top')) > 0);
  assert.match(decl(tau, '.empty', 'border') || '', /dashed/);
  assert.equal(decl(rules(read('app.meridian.css')), '.empty', 'border'), undefined);
});

// Walk 2026-10-28, Meridian's Strategies at 360 and 390px: the Research results summary sat beside the title, so its
// "N% pass rate, of the N strategies here" ran two lines there, and opened, its figures (an absolute popover) covered
// the intro line and the filters. On a phone the summary takes its own row under the intro, and its figures open in
// the page's flow, pushing the filters down. A desktop keeps the summary beside the title and the popover.
test('Meridian: on a phone the Strategies summary sits under the intro and opens in the page, covering nothing', () => {
  const all = rules(read('app.meridian.css'));
  assert.equal(decl(all, '.strategy-heading', 'grid-template-columns', PHONE), 'minmax(0, 1fr)', 'one column: nothing beside the title');
  assert.equal(decl(all, '.strategy-heading > .page-lede', 'grid-row', PHONE), '2');
  assert.equal(decl(all, '.strategy-heading > .strategy-summary', 'grid-row', PHONE), '3', 'under the intro, not between the title and it');
  assert.equal(decl(all, '.strategy-heading > .strategy-summary', 'justify-self', PHONE), 'stretch');
  assert.equal(decl(all, '.strategy-summary #sfigs', 'position', PHONE), 'static', 'opened, it pushes the filters down');
  assert.equal(decl(all, '.strategy-summary #sfigs', 'width', PHONE), 'auto');
  // A desktop keeps the summary at the title's right (how its figures open there is the next test's).
  assert.equal(decl(all, '.strategy-heading', 'grid-template-columns'), 'max-content minmax(0, 1fr)');
  assert.equal(decl(all, '.strategy-heading > .strategy-summary', 'justify-self'), 'end');
  assert.equal(decl(all, '.strategy-summary #sfigs', 'position'), 'absolute');
  // A thumb's 44px to open it.
  assert.ok(all.some((r) => r.media === '@media (hover: none), (pointer: coarse)' && sels(r).includes('.strategy-summary > summary') && /min-height\s*:\s*44px/.test(r.body)));
});

// Walk 2026-10-28, Meridian's Strategies at 1024 and 1280px: opened, the Research results figures (an absolute popover)
// still covered the intro line and the filters there. On a desktop they open in the page: the summary spans the title's
// row and a flexible row its figures fill, the intro drops under them, and the filters move down. The flexible row
// takes all the figures' height, so the title's row keeps its closed height (31px, the closed summary's; 44px to a
// coarse pointer) and neither the title nor the summary moves. Every rule waits for [open], so closed is as before.
test('Meridian: on a desktop the opened Strategies summary pushes the intro and filters down, covering nothing', () => {
  const all = rules(read('app.meridian.css'));
  const OPEN = '.strategy-heading:has(> .strategy-summary[open])';
  assert.equal(decl(all, OPEN, 'grid-template-rows', DESKTOP), 'auto 1fr auto', 'the figures fill a flexible row of their own');
  assert.equal(decl(all, '.strategy-heading > .strategy-summary[open]', 'grid-column', DESKTOP), '2', 'still beside the title');
  assert.equal(decl(all, '.strategy-heading > .strategy-summary[open]', 'grid-row', DESKTOP), '1 / span 2');
  assert.equal(decl(all, '.strategy-heading > .strategy-summary[open]', 'align-self', DESKTOP), 'start');
  assert.equal(decl(all, `${OPEN} > .page-lede`, 'grid-row', DESKTOP), '3', 'the intro sits under the figures');
  assert.equal(decl(all, '.strategy-summary[open] #sfigs', 'position', DESKTOP), 'static', 'in the page, not over it');
  // The summary keeps its place at the right edge, at its own width, as the figures widen the box under it.
  assert.equal(decl(all, '.strategy-summary[open] > summary', 'margin-left', DESKTOP), 'auto');
  assert.equal(decl(all, '.strategy-summary[open] > summary', 'width', DESKTOP), 'fit-content');
  // The title's line box is the closed summary's height, so the title's row (and the title) stays put.
  assert.equal(decl(all, `${OPEN} > h1.page`, 'line-height', DESKTOP), '31px');
  assert.equal(decl(all, `${OPEN} > h1.page`, 'line-height', '@media (min-width: 761px) and (hover: none), (min-width: 761px) and (pointer: coarse)'), '44px');
  // Closed it is the layout it was: the summary beside the title, the figures a popover nothing opens.
  assert.equal(decl(all, '.strategy-summary #sfigs', 'position'), 'absolute');
  assert.ok(!all.some((r) => r.media === DESKTOP && /strategy-(heading|summary)/.test(r.sel) && !/\[open\]/.test(r.sel)), 'every desktop rule here waits for [open]');
});

// Walk 2026-10-28 at 360 and 390px: Tau's Strategies figure "VOID ON UNSEEN DATA" broke "DATA" onto a second line,
// dropping its count below its neighbour's, and Meridian's "Void on unseen data" did the same at 360, with the phone
// grid's divider flush against the label. Tau's labels there track tighter at the stacked tables' 10.5px; Meridian's
// box drops the divider for its own gap and trims its side padding. Each reads on one line at 360 and up; narrower
// still, a long one breaks into even lines. The words are unchanged.
test('Strategies: a phone keeps "Void on unseen data" on one line, in both themes', () => {
  const tau = rules(read('app.css'));
  const NARROW = '@media (max-width: 480px)';
  assert.equal(decl(tau, '#sfigs .lab', 'font-size', NARROW), '10.5px');
  assert.ok(parseFloat(decl(tau, '#sfigs .lab', 'letter-spacing', NARROW)) <= 0.04, 'tracked tighter than .11em');
  assert.equal(decl(tau, '#sfigs .lab', 'text-wrap', NARROW), 'balance');
  assert.equal(decl(tau, '#sfigs .lab', 'letter-spacing'), undefined, 'a desktop keeps the labels as they were');
  const mer = rules(read('app.meridian.css'));
  assert.equal(decl(mer, '.strategy-summary #sfigs > .m:nth-child(even)', 'border-left', PHONE), '0', 'no divider flush against the label');
  assert.equal(decl(mer, '.strategy-summary #sfigs', 'padding', PHONE), '4px 16px');
  assert.equal(decl(mer, '.strategy-summary #sfigs', 'column-gap', PHONE), '16px');
  assert.equal(decl(mer, '.strategy-summary #sfigs .lab', 'text-wrap', PHONE), 'balance');
  // The list is one file for both themes (page-strategies.js): one figure, its label's words once.
  assert.equal((read('page-strategies.js').match(/gl\('Void on unseen data', 'void'\)/g) || []).length, 1, 'the label\'s words');
});

// Walk 2026-10-28 (Playwright, 390x844, touch, both themes, every main page, the bell, the account menu and the
// autopilot sheet): the bell's "Try again" was 17px tall, the account menu's items 31-35px, a glossary (i) 40x40,
// every <summary> 40-41px, a table's strategy link 40-42px, a held contract's market link 39-43px, Tau's pill 40px,
// the sheet's message box 41px and Meridian's Send 42px wide. Each is 44px to a thumb now, under (pointer: coarse)
// only, so a desktop is unchanged; a text control grows by padding a matching negative margin gives back.
for (const [bundle, file] of [['Tau', 'app.css'], ['Meridian', 'app.meridian.css']]) {
  const all = rules(read(file));
  test(`${bundle}: to a thumb the bell's Try again, the account menu, a glossary (i), a disclosure and the autopilot sheet's controls are 44px`, () => {
    for (const sel of ['.profile-menu a', '.profile-item', 'details > summary', '.apf-composer-row textarea', '.dispatch-go .ex-run', '.demo-bar .replay', '.switch']) {
      assert.equal(decl(all, sel, 'min-height', COARSE), '44px', sel);
    }
    for (const sel of ['.switch', '.btn']) assert.equal(decl(all, sel, 'min-width', COARSE), '44px', sel);
    assert.equal(decl(all, 'input[type=range]', 'height', COARSE), '44px');
    assert.equal(decl(all, '.profile-menu a', 'min-height'), undefined, 'a desktop menu keeps its size');
    // "Try again" sits at the end of a 12px line (17px tall): its padding makes 44px, its margin gives it back, and
    // the line's own padding holds the grown button inside the line, clear of the bell's list under it.
    const [padY] = decl(all, '.bell-again', 'padding', COARSE).split(/\s+/).map(px);
    const [marginY] = decl(all, '.bell-again', 'margin', COARSE).split(/\s+/).map(px);
    assert.ok(17 + 2 * padY >= 44, `.bell-again padding ${padY}`);
    assert.equal(marginY, -padY);
    assert.ok(px(decl(all, '.bell-stale', 'padding-block', COARSE)) >= padY);
    assert.equal(decl(all, '.bell-again', 'padding'), '0', 'a desktop keeps the plain text button');
    // The (i): 44px square, its 14px icon still 5px after its word and the line's height unchanged.
    assert.equal(decl(all, '.info', 'width', COARSE), '44px'); assert.equal(decl(all, '.info', 'height', COARSE), '44px');
    const [mt, mr, mb, ml] = decl(all, '.info', 'margin', COARSE).split(/\s+/).map(px);
    assert.equal(44 + mt + mb, 14); assert.equal(44 + ml + mr, 14 + 5); assert.equal(ml + (44 - 14) / 2, 5);
    // A table's strategy link (20px) and a held contract's market link (15px), the line box left alone.
    const name = bundle === 'Tau' ? 'td.name > a:not(.btn)' : 'td.name > a:not(.btn):not(.market-name)';
    for (const [sel, h] of [[name, 20], ['.pos-name a', 15]]) {
      const pad = px(decl(all, sel, 'padding-block', COARSE));
      assert.ok(h + 2 * pad >= 44, `${sel}: padding-block ${pad}`);
      assert.equal(px(decl(all, sel, 'margin-block', COARSE)), -pad, `${sel}: the margin gives it back`);
    }
    // The autopilot line's "Change" (21px line): 44px, and in the sheet its line keeps it clear of "Model and markets".
    const change = px(decl(all, '.ap-focus button', 'padding-block', COARSE));
    assert.ok(21 + 2 * change >= 44);
    assert.ok(px(decl(all, '.apf-top > .ap-focus', 'margin-bottom', COARSE)) >= change);
  });

  // Keyboard walk at 1280px, same day: a ring drawn 2px outside its control (2px wide) was cut off where a box
  // scrolls: a first-column link in a table's sheet lost its left side, Meridian's masthead tabs their top and bottom.
  test(`${bundle}: a keyboard focus ring is not cut off by a table's sheet or the scrolling tab strip`, () => {
    const ring = px(decl(all, ':focus-visible', 'outline')) + px(decl(all, ':focus-visible', 'outline-offset'));
    assert.ok(px(decl(all, '.sheet', 'padding-inline', DESKTOP)) >= ring, 'room for the ring');
    assert.equal(px(decl(all, '.sheet', 'margin-inline', DESKTOP)), -px(decl(all, '.sheet', 'padding-inline', DESKTOP)), 'the table stays where it was');
    assert.equal(decl(all, '.svc-link:focus-visible', 'outline-offset'), '-2px', 'drawn inside the tab');
  });
}

test('Tau: the markets rail\'s See all markets link is underlined after its Updated line, not told apart by a grey alone', () => {
  // axe link-in-text-block (walk 2026-10-30, 1280px): the link's ink beside the line's grey was 2.86:1.
  const all = rules(read('app.css'));
  assert.equal(decl(all, '.hot-ft a', 'text-decoration'), 'underline');
});

test('Tau: the markets rail and the theme picker draw the ring inside, light on the ink-filled chosen theme', () => {
  const all = rules(read('app.css'));
  assert.equal(decl(all, '.hot-row:focus-visible', 'outline-offset'), '-2px');
  assert.equal(decl(all, '.theme-opt:focus-visible', 'outline-offset'), '-4px');
  assert.equal(decl(all, '.theme-opt.on', 'background'), 'var(--ink)');
  assert.equal(decl(all, '.theme-opt.on:focus-visible', 'outline-color'), '#F1F3ED');
});

test('Meridian: Explore\'s search box shows focus with the field\'s border, as every other field does', () => {
  const all = rules(read('app.meridian.css'));
  // `.explore-filters .input` set its own border colour after `.input:focus`, so a focused search looked unfocused.
  assert.equal(decl(all, '.explore-filters .input', 'border-color'), 'var(--rule-2)');
  assert.equal(decl(all, '.explore-filters .input:focus', 'border-color'), decl(all, '.input:focus', 'border-color'));
  assert.equal(decl(all, '.t-explore .xlink a:focus-visible', 'outline-offset'), '-4px');
});

// Explore's All markets / Bitcoin choice: its own full-width row over the list in Meridian's heading grid (row 4 on a
// desktop, row 5 under the search and freshness rows of a phone's two-column grid), wrapping, never wider than the
// page; a touch pointer gets 44px tabs. Tau's sits in the filter row, which wraps at 390px.
test('both themes: a research session row shows its whole cost, at 390px and in the 120px Market column at 1280px', () => {
  // Walked 2026-10-30 at 1280px: Meridian's queued session read "Spent so far: none y", the cost kept to one line
  // (white-space: nowrap) in the 120px column. It wraps there, its last line never one word ("Spent so far:" over
  // "none yet"); on a phone it wraps beside the market. Tau's card says it in its meta line, which wraps.
  const m = rules(read('app.meridian.css')), t = rules(read('app.css'));
  assert.equal(decl(m, '.research-history .run-card', 'grid-template-columns'), 'minmax(0, 1fr) 120px 88px 140px');
  assert.equal(decl(m, '.research-history .run-cost', 'display'), 'block');
  assert.equal(decl(m, '.research-history .run-cost', 'white-space'), 'normal');
  assert.equal(decl(m, '.research-history .run-cost', 'text-wrap'), 'pretty');
  assert.equal(decl(m, '.research-history .run-meta', 'white-space'), 'normal');
  assert.equal(decl(m, '.research-history .run-cost', 'display', '@container research-work (max-width: 759px)'), 'inline');
  for (const r of m.concat(t).filter((r) => sels(r).some((s) => /\.run-(cost|meta|cred)\b/.test(s)))) {
    assert.doesNotMatch(r.body, /white-space\s*:\s*nowrap|text-overflow\s*:\s*ellipsis/, `${r.media} ${r.sel}`);
  }
  assert.equal(decl(t, '.run-meta', 'overflow-wrap'), 'anywhere');
});

test('both themes: Explore\'s Bitcoin choice takes its own row and wraps, so 390px and desktop never scroll sideways', () => {
  const m = rules(read('app.meridian.css')), t = rules(read('app.css'));
  assert.equal(decl(m, '.explore-filters .xshow', 'grid-column'), '1 / -1');
  assert.equal(decl(m, '.explore-filters .xshow', 'grid-row'), '4');
  assert.equal(decl(m, '.explore-filters .xshow', 'min-width'), '0');
  assert.equal(decl(m, '.explore-filters .xshow', 'grid-row', '@container work (max-width: 599px)'), '5');
  assert.equal(decl(m, '.explore-freshness', 'grid-row', '@container work (max-width: 599px)'), '4');
  assert.equal(decl(m, '.chips', 'flex-wrap'), 'wrap');
  assert.equal(decl(m, '.explore-filters .xshow .chip', 'min-height', '@media (hover: none), (pointer: coarse)'), '44px');
  assert.equal(decl(m, '.explore-filters .xshow .chip', 'text-transform'), 'none');
  assert.equal(decl(t, '.section-head', 'flex-wrap'), 'wrap');
  assert.equal(decl(t, '.chips', 'flex-wrap'), 'wrap');
  for (const name of ['app.js', 'app.meridian.js']) {
    assert.match(read(name), /class="chips xshow" role="group" aria-label="Show"/, name);
  }
});

// Overlap walk 2026-10-28 (Playwright at 360, 390 and 768px with a touch pointer, both themes, every signed-in page,
// the bell, the account menu and the autopilot sheet, seeded with 80-character strategy titles and one 82-character
// title with no spaces): every interactive box was checked against every other one and against every text line,
// every text box for a cut without an ellipsis, the page for sideways scroll, and fixed bars for what they cover.
// Before: 44 overlapping pairs of targets, the session page scrolling 217-254px sideways at 360/390 (both themes) and
// Deploy 24px at 768 (Tau), and Tau's markets rail open over the left 306px of every page at 768. After: none.
for (const [bundle, file, js] of [['Tau', 'app.css', 'app.js'], ['Meridian', 'app.meridian.css', 'app.meridian.js']]) {
  const all = rules(read(file));
  const src = read(js);

  test(`${bundle}: the since strip's links are each 44px to a thumb inside their own line, a list of them stacked`, () => {
    // "4 strategies passed: A, B, C, 1 more": 44px boxes on a 21px line reached 26-27px into the next line's link.
    assert.equal(decl(all, '.since-row dd a', 'display', COARSE), 'inline-block');
    assert.equal(decl(all, '.since-row dd a', 'margin-block', COARSE), '0', 'no negative margin: the line holds the box');
    const pad = px(decl(all, '.since-row dd a', 'padding-block', COARSE));
    const line = px(decl(all, '.since-row dd', 'font-size')) * parseFloat(decl(all, '.since-row dd', 'line-height'));
    assert.ok(line + 2 * pad >= 44, `${line}px line + 2 x ${pad}px`);
    assert.equal(decl(all, '.since-row dd a', 'max-width', COARSE), '100%', 'a long title wraps inside its box');
    // Two or more links in a row stack one under another; their commas (the list's only text) take no room.
    assert.equal(decl(all, '.since-links', 'display', COARSE), 'flex');
    assert.equal(decl(all, '.since-links', 'flex-direction', COARSE), 'column');
    assert.equal(decl(all, '.since-links', 'font-size', COARSE), '0');
    assert.equal(decl(all, '.since-links > a', 'font-size', COARSE), decl(all, '.since-row dd', 'font-size'));
    assert.ok(!all.some((r) => r.media !== COARSE && /since-links/.test(r.sel)), 'a mouse reads the line as before');
    assert.match(src, /const sinceLinks = \(links\) => \(links\.length > 1 \? `<span class="since-links">\$\{links\.join\(', '\)\}<\/span>` : links\.join\(''\)\);/);
    assert.match(src, /passed: \$\{sinceLinks\(\[\.\.\.pass\.items\.map\(/);
    assert.match(src, /const fwdText = `\$\{sinceLinks\(fwd\)\} passed/);
  });

  test(`${bundle}: a link wrapped under a glossary (i) starts clear of the (i)'s 44px`, () => {
    // "…and the spread (i) · Download trades (CSV)": the (i) reached 25px into the CSV link on the next line (Tau, 360/390).
    const sel = '.nobr:has(> .info) + a.csv-link';
    assert.equal(decl(all, sel, 'display', COARSE), 'inline-block', 'the link’s box sets its line');
    const below = -px(decl(all, '.info', 'margin', COARSE).split(/\s+/)[2]);  // the (i)'s 44px under its 14px icon
    assert.ok(px(decl(all, sel, 'margin-top', COARSE)) >= below - 2, `margin-top vs the (i)'s ${below}px`);
    assert.equal(decl(all, 'a.csv-link', 'padding', COARSE), '13px 4px', 'the link stays 44px');
  });

  test(`${bundle}: a deploy hint's link keeps clear of the button or fold next to it, and Research's totals of the first session`, () => {
    assert.ok(px(decl(all, '.btn + .hint:has(a)', 'margin-top', COARSE)) >= 4, 'Deploy on demo over a demo-key hint’s "Funds page"');
    if (bundle === 'Tau') {
      // "See them on the Deploy page" over "Open this market on Kalshi ↗": two hint lines 12px apart (an inline margin), 11px overlap.
      assert.match(read('app-strategy.js'), /<p class="hint" style="margin-top:12px">\$\{deployedOn\(s\.deployments\)\} <a href="\/deploy">/);
      assert.ok(12 + px(decl(all, 'p.hint:has(a) + p.hint:has(a)', 'padding-top', COARSE)) >= 26);
    } else {
      assert.ok(px(decl(all, '.hint.on-paper + .deployment-environments', 'margin-top', COARSE)) >= 4, '"See it on Deploy" over Demo & live');
      assert.ok(px(decl(all, '.research-total', 'padding-bottom', COARSE)) >= 8, '"Passed (i)" over the first session at 768');
    }
  });

  test(`${bundle}: two track-record rows' strategy links don't meet when their titles wrap`, () => {
    const [top, bottom] = decl(all, '.trpanel td.name', 'padding-block', COARSE).split(/\s+/).map(px);
    assert.ok(top + bottom >= 21, `${top} + ${bottom}: was 10 + 9, 1px short`);
  });

  test(`${bundle}: a title with no spaces breaks in a session's result line, and an open position's market cell wraps`, () => {
    assert.equal(decl(all, '.run-next', 'overflow-wrap'), 'anywhere');
    assert.equal(decl(all, '#openpos td.pos-name', 'white-space'), 'normal');
    assert.ok(decl(all, '#openpos td.pos-name', 'min-width'));
  });

  test(`${bundle}: a focused text field, select or message box shows the ring a button does, 3:1 or more`, () => {
    const ring = all.find((r) => r.media === '' && /:focus-visible$/.test(r.sel) && r.sel.includes(':is(.input, select, textarea, input:is([type=text]'));
    assert.ok(ring, 'the field ring rule');
    assert.match(ring.sel, /^:where\(body:not\(\.landing-body\)\) /, 'not on the landing page');
    assert.match(ring.sel, /:not\(\.linput, \.wl-ifield input\)/, 'not the landing or card form fields');
    for (const t of ['[type=email]', '[type=number]', '[type=password]', '[type=search]', ':not([type])']) assert.ok(ring.sel.includes(t), t);
    assert.match(ring.body, /outline: 2px solid var\(--ink\)/);
    assert.match(ring.body, /outline-offset: 2px/);
    assert.equal(decl(all, ':focus-visible', 'outline'), '2px solid var(--ink)', 'as every button');
    assert.equal(decl(all, '.input:focus', 'border-color'), 'var(--ink)', 'the darker border stays');
    // The ring against every surface a field sits on.
    const root = read(file).match(/:root\s*\{([^}]*)\}/)[1];
    const raw = Object.fromEntries([...root.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
    const hex = (k) => { let v = raw[k]; while (v && v.startsWith('var(')) v = raw[v.slice(4, -1)]; return v; };
    const lum = (h) => { const [r, g, b] = h.replace('#', '').match(/../g).map((x) => parseInt(x, 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    for (const bg of ['--stock', '--stock-raised', '--stock-sunk']) {
      const [a, b] = [lum(hex('--ink')), lum(hex(bg))];
      assert.ok((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= 3, `--ink on ${bg}`);
    }
  });
}

test('Tau: a 768px tablet\'s Deploy board fits its sheet, and the markets rail opens over a tablet page only when asked', () => {
  const all = rules(read('app.css'));
  const NARROWER = '@container deployments (max-width: 760px)';
  assert.ok(/@media \(min-width: 761px\) \{[\s\S]*@container deployments \(max-width: 760px\)/.test(read('app.css').replace(/\/\*[\s\S]*?\*\//g, '')));
  assert.ok(px(decl(all, '.t-dep th', 'padding-left', NARROWER)) <= 5);
  assert.ok(parseFloat(decl(all, '.t-dep td.name', 'min-width', NARROWER)) >= 8, 'the title still reads');
  // The rail is an overlay up to 1080px (app.css) and opens there only on a saved "1" (test_frontend_merge.mjs).
  assert.equal(decl(all, 'body.hot-open .hotrail', 'z-index', '@media (max-width: 1080px)'), '60');
  assert.match(read('app.js'), /const hotOver = \(\) => !!\(window\.matchMedia && window\.matchMedia\('\(max-width: 1080px\)'\)\.matches\);/);
  // A hot market's title is cut at two lines: its whole name is the row's tooltip, as Meridian's.
  assert.equal(decl(all, '.hot-title', '-webkit-line-clamp'), '2');
  assert.match(read('app.js'), /<span class="hot-title" title="\$\{esc\(mktLabel\(m\)\)\}">/);
});

for (const [name, css, js] of [['Tau', 'app.css', 'app.js'], ['Meridian', 'app.meridian.css', 'app.meridian.js']]) test(`${name}: the dashboard autopilot card's Try again sizes to its words, at 390px and on a desk`, () => {
  // Walk 2026-10-31: the card's main column is a grid (.apcard-main), which stretched its Try again (status unread)
  // the card's full width, at 390px and at 1280px. It starts at the left and sizes to its words, as a .btn.sm does in
  // any other card, and no rule gives it a width (both themes).
  const all = rules(read(css)), again = '.apcard-main > [data-apcard="again"]';
  assert.equal(decl(all, '.apcard-main', 'display'), 'grid');
  assert.equal(decl(all, again, 'justify-self'), 'start');
  assert.deepEqual(all.filter((r) => sels(r).includes(again) && /(?:^|;|\s)(?:width|justify-self\s*:\s*stretch)/.test(r.body)).map((r) => r.media), []);
  // The card draws it straight inside that column.
  assert.match(read(js), /<div class="apcard-main">\$\{notice\(AP_CARD_UNREAD\)\}<button type="button" class="btn sm" data-apcard="again">Try again<\/button><\/div>/);
});
