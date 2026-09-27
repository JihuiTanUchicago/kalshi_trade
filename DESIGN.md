---
name: Kalshi BTC 15M Control Room
description: A Swiss station timetable for a single operator watching real money — ink on stock, hairline rules, one reserved signal colour.
colors:
  stock: "#E9EBE5"
  stock-live: "#EFE4E7"
  stock-sunk: "#DFE2DA"
  stock-raised: "#F1F3ED"
  ink: "#191B16"
  ink-2: "#444841"
  ink-3: "#5F645D"
  rule: "#C9CDC2"
  rule-2: "#B1B6AA"
  signal: "#C8102E"
  signal-wash: "#F8E4E6"
  signal-ink: "#FDF2F3"
  pos: "#D9E7D6"
  neg: "#F0DEDC"
  trace-ink: "#191B16"
  trace-umber: "#7A5C2E"
  trace-slate: "#31566F"
  trace-olive: "#55693F"
  trace-plum: "#6B4257"
typography:
  page-title:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(23px, 3vw, 30px)"
    fontWeight: 600
    lineHeight: 1.45
    letterSpacing: "-0.02em"
  said:
    fontFamily: "Archivo Narrow, Archivo, sans-serif"
    fontSize: "clamp(16px, 2.1vw, 20px)"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "0.01em"
  figure:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(21px, 2.6vw, 27px)"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.015em"
    fontFeature: "tabular-nums lining-nums"
  figure-sm:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.015em"
    fontFeature: "tabular-nums lining-nums"
  section-head:
    fontFamily: "Archivo Narrow, Archivo, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    letterSpacing: "0.13em"
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tabular-nums lining-nums"
  table:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tabular-nums lining-nums"
  column-head:
    fontFamily: "Archivo Narrow, Archivo, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.02em"
  label:
    fontFamily: "Archivo Narrow, Archivo, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    letterSpacing: "0.11em"
  wordmark:
    fontFamily: "Archivo Narrow, Archivo, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    letterSpacing: "0.16em"
rounded:
  hairline: "3px"
spacing:
  gutter: "clamp(14px, 2.2vw, 28px)"
  cell: "9px 12px 8px"
  measure: "14px 18px 13px"
  section: "32px"
  foot: "64px"
components:
  button:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "6px 13px 5px"
  button-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.stock-raised}"
  button-disabled:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.signal}"
    rounded: "{rounded.hairline}"
    padding: "6px 13px 5px"
  button-danger-hover:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.signal-ink}"
  button-sm:
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "4px 10px 3px"
  mark:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "2px 7px 1px"
  mark-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.stock-raised}"
  mark-armed:
    backgroundColor: "{colors.signal-wash}"
    textColor: "{colors.signal}"
  mark-halt:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.signal-ink}"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    rounded: "{rounded.hairline}"
    padding: "4px 9px 3px"
  chip-hover:
    textColor: "{colors.ink}"
  input:
    backgroundColor: "{colors.stock-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.table}"
    rounded: "{rounded.hairline}"
    padding: "6px 9px"
  input-focus:
    backgroundColor: "{colors.stock}"
    textColor: "{colors.ink}"
  nav-link:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    padding: "9px 16px 8px"
  nav-link-current:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
  figure-tint-pos:
    backgroundColor: "{colors.pos}"
    textColor: "{colors.ink}"
    typography: "{typography.figure}"
    rounded: "{rounded.hairline}"
    padding: "1px 7px"
  figure-tint-neg:
    backgroundColor: "{colors.neg}"
    textColor: "{colors.ink}"
    typography: "{typography.figure}"
    rounded: "{rounded.hairline}"
    padding: "1px 7px"
  plate:
    backgroundColor: "{colors.stock-raised}"
    textColor: "{colors.ink}"
    padding: "10px 12px 6px"
  notice:
    backgroundColor: "{colors.signal-wash}"
    textColor: "{colors.ink}"
    typography: "{typography.table}"
    padding: "12px 14px"
---

# Design System: Kalshi BTC 15M Control Room

## Overview

**Creative North Star: "The Station Timetable"**

This is a departures board for money, not a trading terminal. Everything is printed on a warm
grey stock, ruled with hairlines, and read top to bottom in a single column of sections. Figures
sit on a rule; they never sit in a card. The page has no shadow, no gradient, no glass, no
blur, and no rounded panel: the only radius in the system is a 3px hairline nick on small
inset objects. Depth is a printing problem, solved by rule weight and by two stock tints,
never by lifting anything off the page.

The world deliberately refuses the terminal look that trading software defaults to. **There is
no monospace anywhere in the build** — not in tables, not in chart axes, not in identifiers.
Alignment of figures is bought with `font-variant-numeric: tabular-nums lining-nums` set on
`body` and reasserted on every numeric cell, which is what a timetable actually does. Typography
is one family in two cuts (Archivo and Archivo Narrow) at two weights (400 and 600). The narrow
cut carries every label, head, chip, tab and status line; the normal cut carries sentences and
figures.

The page is built to be read by one operator at a glance, so the system spends its scarcity
budget on a single reserved red. Money direction is never told in that red; it rides a
desaturated tint field behind the figure instead. The whole surface is served as plain CSS and
vanilla JS embedded in Python string literals — there is no build step, no framework, no icon
package, and no runtime dependency beyond one Google Fonts import.

**Key Characteristics:**
- Ruled rows on stock; no cards, no shadows, no gradients, no glass.
- One reserved signal red, spent only on attention and on the live-money boundary.
- Two stocks — grey newsprint for paper, rose-tinted for real money.
- Archivo + Archivo Narrow, two weights, tabular lining figures everywhere.
- No monospace, anywhere, ever.
- One authored motion: a 180ms wash on a figure whose value just changed.

## Colors

A printed palette: warm grey-green newsprint, near-black ink in three steps, two rule greys,
and one reserved red that appears on perhaps two percent of any screen.

### Primary
- **Signal Red** (`{colors.signal}`): The reserved colour. It marks the status line when the
  operator is needed, the stale rule and stale note, the armed and halted state marks, the
  destructive button, notices, the caret in every input, the live masthead rule, and the
  dashed LIVE cutoff line drawn on the charts. Nothing else.
- **Signal Wash** (`{colors.signal-wash}`): The red's only fill, behind an armed mark and
  inside a notice box.
- **Signal Ink** (`{colors.signal-ink}`): The near-white that sits on a solid red fill
  (halt mark, danger button hover), warm enough not to vibrate against it.

### Secondary
- **Paper Stock** (`{colors.stock}`): The grey newsprint page. Simulation and pipeline.
- **Live Stock** (`{colors.stock-live}`): The rose-tinted page, applied by `body.live-service`,
  together with a red masthead rule and a red active-tab underline. Real money is a different
  sheet of paper, recognisable in peripheral vision before a word is read.
- **Raised Stock** (`{colors.stock-raised}`): Chart plates, input fields, row hover, and the
  knocked-out text on an ink fill. One step lighter than the page.
- **Sunk Stock** (`{colors.stock-sunk}`): Scrollbar tracks only.

### Tertiary
- **Positive Tint** (`{colors.pos}`) / **Negative Tint** (`{colors.neg}`): Desaturated fields
  laid behind a money figure to tell direction. They are fields, not text colours; the figure
  itself stays ink.
- **Trace Set** (`{colors.trace-ink}`, `{colors.trace-umber}`, `{colors.trace-slate}`,
  `{colors.trace-olive}`, `{colors.trace-plum}`): The five chart line colours, cycled in that
  order and always paired with a distinct dash pattern (`[]`, `[6,3]`, `[2,3]`, `[9,3,2,3]`,
  `[4,2]`) so a series is identifiable without colour.

### Neutral
- **Ink** (`{colors.ink}`): Body text, figures, section rules (2px), active tab, primary button
  border.
- **Ink 2** (`{colors.ink-2}`): Secondary prose, wrapped cell text, default mark text.
- **Ink 3** (`{colors.ink-3}`): Labels, column heads, sub-figures, as-of notes, captions,
  disabled text, chart axis text.
- **Rule** (`{colors.rule}`) / **Rule 2** (`{colors.rule-2}`): The hairline system. `rule` for
  row and section-body dividers; `rule-2` for the heavier divider under a column head, for
  input and chip borders, and for the wash keyframe's start colour.

### Named Rules

**The Reserved Signal Rule.** `{colors.signal}` means "this needs you" or "this is real money."
It is spent on: the attention state of the status line, the stale rule and note, the armed/halt
marks, the danger button, the notice box, the caret, the live masthead and live active-tab
underline, and the LIVE cutoff marker on a chart. Adding a sixth use dilutes the other five.

**The Money-Rides-a-Field Rule.** Profit and loss direction is told by a tint field behind the
figure (`{colors.pos}` / `{colors.neg}`) with the figure kept in ink — never by colouring the
figure, and never by the reserved red. A losing number is not an alarm; it is a number.

**The Two Stocks Rule.** Paper trading and pipeline sit on `{colors.stock}`. Real money sits on
`{colors.stock-live}` via `body.live-service`, which also swaps the masthead's bottom rule and
the active tab's underline to `{colors.signal}`. The two surfaces must never be confusable at a
glance.

**The State-Not-By-Colour Rule.** Every state that carries colour also carries a word or a
shape: the stale rule goes dashed and the figures get struck through, the marks read OFF / ON /
ARMED / HALT, the status line swaps a check glyph for a triangle. Remove all colour and the page
still reports correctly.

## Typography

**Display Font:** Archivo (with `ui-sans-serif`, `system-ui`, `sans-serif`)
**Body Font:** Archivo (same stack)
**Label Font:** Archivo Narrow (falling back to Archivo, then `sans-serif`)

**Character:** One grotesque family in two cuts and two weights (400, 600). Archivo Narrow is
the timetable voice — condensed, letterspaced, uppercase, used for anything that labels rather
than states. Archivo normal is the reading voice: sentences, figures, table data. There is no
third family and, emphatically, no monospace cut; `font-variant-numeric: tabular-nums
lining-nums` is declared on `body` and restated on numeric cells and inputs, which gives column
alignment without the terminal costume.

### Hierarchy
- **Page Title** (`h1.page`, 600, `clamp(23px,3vw,30px)`, `-0.02em`): One per page, sentence case.
- **Status Line** (`.said`, Narrow 600, `clamp(16px,2.1vw,20px)`, 1.35): The single dominant
  sentence under the title; drops to 15px under 640px.
- **Figure** (`.fig`, 600, `clamp(21px,2.6vw,27px)`, `-0.015em`, 1.1): The measured numbers in a
  `.measure` row. `.fig.sm` is the 17px variant for denser rows.
- **Section Head** (`.sect-head h2`, Narrow 600, 13px, `0.13em`, uppercase): Names a section
  above its 2px ink rule.
- **Body** (Archivo 400, 14px, 1.45): Page default. Prose is capped at 68ch (`.prose`, `.deck`),
  legends and notices at 66ch, wrapped table cells at 46ch, the status line at 104ch.
- **Table** (13px; column heads Narrow 600 12px `0.02em`, sentence case): Rows are 9px/12px/8px
  and baseline-aligned.
- **Micro-label** (`.lab`, Narrow 400, 11px, `0.11em`, uppercase): Above every figure and field.
- **Mark / Button / Chip** (Narrow 600, 11–11.5px, `0.07–0.1em`, uppercase).
- **Wordmark** (Narrow 600, 13px, `0.16em`, uppercase).

### Named Rules

**The No-Monospace Rule.** No monospace font is permitted anywhere, including chart axis labels
(`11px "Archivo Narrow"`) and code-like identifiers. Numeric alignment comes from tabular lining
figures, not from a fixed-pitch face. The terminal look is the rut this world was built to leave.

**The Short-Caps Rule.** Uppercase is reserved for short labels: section heads, micro-labels,
column-free field labels, chips, tabs, marks, buttons, the wordmark, and the stale mark.
Anything that reads as a sentence — decks, legends, notes, empty-state copy, status-line text,
notice bodies — is sentence case. The rule was tuned against the build: snake_case model names
in tables are left lowercase on purpose, because upper-casing a 29-character identifier costs
legibility and buys nothing.

**The Two-Weights Rule.** 400 and 600 only. There is no 300, 500 or 700 anywhere in the system;
emphasis is bought with the narrow cut, letterspacing, and case instead.

## Layout

A single centred column, `max-width: 2560px`, with a fluid gutter `{spacing.gutter}` and 64px of
foot. Everything stacks vertically: masthead (2px ink rule, red on live) → service nav (1px rule,
three tabs) → page title + deck → status line → sections.

Sections (`.sect`) are separated by `{spacing.section}` of top margin and opened by a `.sect-head`
that flexes its `h2` and `.sect-note` to opposite baselines over a 2px ink rule.

Measured figures use `.measure`: an auto-fit grid of `minmax(150px, 1fr)` cells divided by 1px
vertical rules, closed by a 1px bottom rule. The first cell has no left rule and no left padding,
so the grid aligns flush with the page's text edge.

Tables are fixed-layout (`table-layout: fixed`) with explicit per-table column-width classes
(`.t-books`, `.t-strat`, `.t-period`, `.t-pos8`, `.t-pos7`) and `min-width: 860px`, wrapped in a
horizontally scrollable `.sheet`. Column widths are pinned so a long strategy name cannot swallow
the slack and strand the figures at the far edge of a 2500px sheet. First and last cells lose
their outer padding to keep the flush edge. Column heads are sticky to the top of the viewport
and repaint the current stock behind themselves.

**Breakpoints**
- **≤ 640px** — `.stack` tables restack: `thead` is visually hidden, each `tr` becomes a block
  with a `rule-2` bottom border, and each `td` becomes a labelled row printing `attr(data-lab)`
  in 11px uppercase Narrow on the left with the value right-aligned. Row hover is disabled.
  The status line drops to 15px.
- **≤ 860px** — `.measure` collapses to two columns with the vertical rule only on even cells;
  `.sheet` bleeds to the full device width by negative gutter margins; column heads unstick.
- **≥ 1500px** — `.plates` becomes a two-column grid (12px gap) with the first plate spanning
  full width.
- **≥ 2200px** — `.plates` becomes three columns and the first plate rejoins the flow.
- **Print** — white background; service nav and buttons are removed.

### Named Rules

**The One Dominant Answer Rule.** Each page opens with exactly one status line stating what the
system is doing right now; every section below is supporting evidence. On a phone that line owns
the first viewport.

**The Flush-Edge Rule.** The leftmost column of any measure grid or table drops its padding and
its rule so figures align to the same vertical as the page title. Nothing is indented into a box.

## Elevation & Depth

**There are no shadows in this system.** Not one `box-shadow`, gradient, blur, or backdrop-filter
exists in the build, and none may be added. Depth is printed: it is carried entirely by rule
weight and by four stock tints.

The rule hierarchy is the elevation scale:
- **2px solid ink** — masthead bottom and section head. The strongest division on the page.
- **2px solid signal** — the same rule on the live masthead; **2px dashed signal** when a section
  is stale.
- **1px `rule-2`** — under a column head, and around inputs and chips.
- **1px `rule`** — row dividers, measure cell dividers, plate borders, service nav bottom.

Tonal layering does the rest: `stock-raised` lifts a chart plate, an input, or a hovered row one
step off the page; `stock-sunk` recesses a scrollbar track. On the live surface the plate
inverts — `body.live-service .plate` uses `{colors.stock}` — so the plate still separates from a
rose page.

### Named Rules

**The Printed-Depth Rule.** If something needs to separate, rule it or tint it. Never lift it.
A shadow, gradient, or glass panel anywhere in this world is a defect.

## Shapes

Rectangles, everywhere, at zero radius. The only radius token is `{rounded.hairline}` (3px), and
it appears only on small inset objects: marks, chips, buttons, inputs, selects, and the tint
field behind a money figure. Sections, plates, notices, tables, and the page shell are hard
rectangles.

Borders are hairlines (1px) except the two structural 2px rules. The one non-rectangular form in
the system is the pair of authored 24×24 status glyphs — a circled check and a warning triangle —
drawn inline as SVG at `stroke-width: 1.6`, `stroke-linecap: round`, with `stroke: currentColor`
so they inherit ink or signal from the status line. They are authored rather than pulled from a
glyph set, which is what keeps one stroke weight across the page.

### Named Rules

**The Hairline-Nick Rule.** 3px radius on inset objects, 0 everywhere else. There is no medium
or large radius step, and adding one would break the printed register.

**The Drawn-Icon Rule.** Icons are inline SVG strokes at 1.6 drawn to match the type's weight,
using `currentColor`. No icon font, no glyph package, no emoji.

## Components

### Buttons
- **Shape:** Hard rectangle with a 3px nick (`{rounded.hairline}`); 1px ink border, transparent fill.
- **Primary:** Narrow 600, 11.5px, `0.1em`, uppercase, padding `6px 13px 5px`.
- **Hover:** Fills ink, text knocks out to `{colors.stock-raised}`, over 160ms
  `cubic-bezier(.16,1,.3,1)` on background and colour only.
- **Active:** `translateY(1px)`. Nothing else moves.
- **Disabled:** Border and text drop to `{colors.rule-2}` / `{colors.ink-3}`, cursor `not-allowed`.
- **Danger:** Signal border and text; fills signal with `{colors.signal-ink}` on hover. Used for
  arming or halting live trading only.
- **Small:** 11px, padding `4px 10px 3px`.

### Chips
- **Style:** Narrow 600, 11.5px, `0.07em`, uppercase; `{colors.ink-2}` on transparent with a 1px
  `{colors.rule-2}` border and a 3px nick. Laid out as an unstyled `ul.chips` with 7px gaps.
- **Hover:** Border and text go to ink. There is no selected state; chips are navigation.

### Marks (status pills)
The state vocabulary. Narrow 600, 11px, `0.09em`, uppercase, `2px 7px 1px`, 3px nick.
- **Default:** `{colors.ink-2}` on transparent, `{colors.rule-2}` border — e.g. OFF.
- **`.on`:** Solid ink with knocked-out text — the affirmative, permanent state.
- **`.armed`:** Signal text on `{colors.signal-wash}` with a signal border.
- **`.halt`:** Solid signal with `{colors.signal-ink}` text — the loudest object in the system.
- **`.quiet`:** `{colors.ink-3}`, for a state that is true but uninteresting.

### Containers
There are no cards. The two container forms are:
- **Section (`.sect`)** — an unfilled region opened by a ruled head. No border, no background.
- **Plate (`.plate`)** — the only filled container: 1px `{colors.rule}` border, `{colors.stock-raised}`
  fill (inverted to `{colors.stock}` on the live surface), padding `10px 12px 6px`, zero radius.
  Holds a chart canvas and its `.keys` legend (14px-gapped Narrow 12px entries, each with a 14px
  `border-top: 2px` rule swatch in `currentColor`).

### Inputs / Fields
- **Style:** `{colors.stock-raised}` fill, 1px `{colors.rule-2}` border, 3px nick, padding `6px 9px`,
  full width, tabular figures. Wrapped in `.field` (column flex, 3px gap, `min-width: 104px`) under
  a `.lab` micro-label.
- **Hover:** Border to `{colors.ink-3}`.
- **Focus:** Border to ink, background to `{colors.stock}`, native outline removed. The caret is
  `{colors.signal}` — the one place the reserved colour is decorative rather than alarming.
- **Global focus:** Everything else gets `:focus-visible { outline: 2px solid ink; offset 2px }`.
- **Disclosure (`details > summary`):** Narrow 12px `{colors.ink-3}`; the native marker is removed
  and replaced with a `+` / `−` prefix in `{colors.rule-2}`; text goes to ink on hover.

### Navigation
- **Masthead:** Wordmark (`KALSHI BTC 15M / <service>`) at the left baseline, `.asof` read-clock
  at the right in Narrow 12px uppercase `{colors.ink-3}` with the time itself in ink 600. Bottom
  rule 2px ink, or 2px signal on the live surface, where the service label also turns signal.
- **Service links:** Three uppercase Narrow 12.5px `0.1em` tabs in a 1px-ruled strip. Hover raises
  the stock and darkens the text. `[aria-current="page"]` goes ink with a 2px ink bottom border
  pulled up by `-1px` to overlap the strip rule — signal on the live surface.
- **Mobile:** The strip wraps; no hamburger, no drawer.

### Status Line (signature)
`.statusline` is the page's one dominant answer: an authored 17px SVG mark plus a Narrow 600
clamp(16–20px) sentence, capped at 104ch, closed by a 1px rule. Segments are joined by a
`{colors.rule-2}` middot separator. In calm state the check glyph shows in `{colors.ink-3}` and
`em` segments read `{colors.ink-3}`. Adding `.needs` swaps to the warning triangle and turns both
the glyph and the `em` segments `{colors.signal}`. `em` is reset to `font-style: normal` — the
alarm is colour plus glyph, not italics.

### As-of Rule (signature)
The system's defining component: `.sect` + `.sect-head` (h2 + `.sect-note`) over a 2px ink rule.
The note reads `as of <n>s ago` in Narrow 12px `{colors.ink-3}`, recomputed against each writer's
expected cadence (`age_sec > expect_sec × 6` is stale; an unknown writer reads `never written`).

Adding `.stale` to the section breaks the rule in four coordinated ways:
1. The 2px ink head rule becomes **2px dashed signal**.
2. The note turns `{colors.signal}` and goes 600.
3. The note is prefixed by a `.stale-mark` — uppercase, letterspaced `0.09em`, signal, 600 —
   reading `STALE 13D`, followed by a sentence-case clause naming the writer that stopped.
4. Every figure and table cell inside is struck through (`line-through`, 1px, `{colors.rule-2}`)
   and dropped to `{colors.ink-3}`. The numbers remain readable but are visibly disowned.

### Charts
Canvas drawn at device pixel ratio, axis labels in `11px "Archivo Narrow"` `{colors.ink-3}`,
outer gridlines `{colors.rule-2}`, inner gridlines `#D7DBD0`, zero line 1px ink. Series cycle the
five trace colours paired with five dash patterns. The live cutoff is a dashed signal vertical
labelled `LIVE`. Band charts fill at 7–10% alpha of their own trace colour.

## Do's and Don'ts

### Do:
- **Do** separate with a rule or a stock tint. The rule scale is 2px ink / 2px signal / 1px
  `rule-2` / 1px `rule`; the tint scale is `stock-sunk` → `stock` → `stock-raised`.
- **Do** put every new figure block on a `.measure` grid and every new dataset in a `.sect` with
  a `.sect-head` and a live `.sect-note`, so its freshness is always on the page.
- **Do** tell money direction with a `.fig.tint.pos` / `.fig.tint.neg` field behind an ink figure.
- **Do** keep `font-variant-numeric: tabular-nums lining-nums` on anything numeric.
- **Do** reserve uppercase for short labels and write every sentence in sentence case, including
  empty-state copy, notes, and legends.
- **Do** give every new table a `.stack` class and `data-lab` on each `td` so it restacks into
  labelled rows under 640px.
- **Do** pin column widths on any new table via a `colgroup` and a `.t-*` width class.
- **Do** pair colour with a word or a shape for every state.
- **Do** draw icons inline as 1.6-stroke SVG with `currentColor`.
- **Do** honour `prefers-reduced-motion`; the global reduce block collapses all animation and
  transition to 0.001ms.

### Don't:
- **Don't** add a shadow, gradient, glass/backdrop-filter, or a card. Containers are sections and
  plates only.
- **Don't** use a monospace font anywhere, for any reason, including identifiers and chart axes.
- **Don't** spend `{colors.signal}` on anything but attention or the live-money boundary. Never on
  a losing number, a heading, a link, or decoration.
- **Don't** colour a P&L figure itself; the field behind it carries direction.
- **Don't** introduce a third font family, a third weight, or a radius other than 3px.
- **Don't** uppercase a sentence, a model identifier, or anything longer than a few words.
- **Don't** add a second animation. `.washed` (180ms, `cubic-bezier(.16,1,.3,1)`, `{colors.rule-2}`
  fading to transparent, fired only when a figure's value actually changed) is the system's one
  authored moment; transitions are limited to the 160ms button colour change.
- **Don't** add a build step, a framework, an icon package, or a runtime dependency. The surface
  is plain CSS and vanilla JS inside Python string literals.
- **Don't** let the live surface and the paper surfaces converge. `body.live-service` must keep
  its own stock, its red head rule, and its red active tab.
