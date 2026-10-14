---
name: Tau
description: >
  Two shipped worlds. The pre-login landing is a calm, white, rounded product page in Rubik
  with one warm accent. The authed app is Kursbuch — a Swiss station-timetable for money: ink
  on warm grey stock, hairline rules, Archivo figures, and one reserved signal red. The
  operator console (dashboard_server.py) is the same Kursbuch world as a secondary surface.
colors:
  landing:
    l-bg: "#FBFBFA"
    l-ink: "#15161A"
    l-ink-2: "#5B5F66"
    l-ink-3: "#8A8E95"
    l-line: "#E7E6E2"
    l-accent: "#F05A28"
  app:
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
    pos: "#D9E7D6"
    neg: "#F0DEDC"
  console:
    kursbuch-stock: "#E9EBE5"
    kursbuch-stock-live: "#EFE4E7"
    kursbuch-stock-sunk: "#DFE2DA"
    kursbuch-stock-raised: "#F1F3ED"
    kursbuch-ink: "#191B16"
    kursbuch-ink-2: "#444841"
    kursbuch-ink-3: "#5F645D"
    kursbuch-rule: "#C9CDC2"
    kursbuch-rule-2: "#B1B6AA"
    kursbuch-signal: "#C8102E"
    kursbuch-signal-wash: "#F8E4E6"
    kursbuch-signal-ink: "#FDF2F3"
    kursbuch-pos: "#D9E7D6"
    kursbuch-neg: "#F0DEDC"
    kursbuch-trace-ink: "#191B16"
    kursbuch-trace-umber: "#7A5C2E"
    kursbuch-trace-slate: "#31566F"
    kursbuch-trace-olive: "#55693F"
    kursbuch-trace-plum: "#6B4257"
typography:
  landing:
    l-hero:
      fontFamily: "Rubik, ui-sans-serif, system-ui, sans-serif"
      fontSize: "clamp(38px, 6.4vw, 68px)"
      fontWeight: 600
      lineHeight: 1.04
      letterSpacing: "-0.03em"
    l-sub:
      fontFamily: "Rubik, ui-sans-serif, system-ui, sans-serif"
      fontSize: "clamp(17px, 2.1vw, 21px)"
      fontWeight: 400
      lineHeight: 1.5
    l-wordmark:
      fontFamily: "Rubik, ui-sans-serif, system-ui, sans-serif"
      fontSize: "20px"
      fontWeight: 600
      letterSpacing: "-0.01em"
    l-pill:
      fontFamily: "Rubik, ui-sans-serif, system-ui, sans-serif"
      fontSize: "15px"
      fontWeight: 500
      lineHeight: 1
    l-line-item:
      fontFamily: "Rubik, ui-sans-serif, system-ui, sans-serif"
      fontSize: "clamp(16px, 2.3vw, 22px)"
      fontWeight: 400
    l-fine:
      fontFamily: "Rubik, ui-sans-serif, system-ui, sans-serif"
      fontSize: "14px"
      fontWeight: 400
      lineHeight: 1.6
  app:
    page-title:
      fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
      fontSize: "clamp(23px, 3vw, 30px)"
      fontWeight: 600
      letterSpacing: "-0.02em"
    said:
      fontFamily: "Archivo Narrow, Archivo, sans-serif"
      fontSize: "clamp(15px, 2vw, 19px)"
      fontWeight: 600
      lineHeight: 1.35
    fig:
      fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
      fontSize: "clamp(21px, 2.6vw, 27px)"
      fontWeight: 600
      letterSpacing: "-0.015em"
      lineHeight: 1.1
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
      fontFeature: "tabular-nums lining-nums"
    lab:
      fontFamily: "Archivo Narrow, Archivo, sans-serif"
      fontSize: "11px"
      fontWeight: 400
      letterSpacing: "0.11em"
    mark:
      fontFamily: "Archivo Narrow, Archivo, sans-serif"
      fontSize: "11px"
      fontWeight: 600
      letterSpacing: "0.09em"
    wordmark:
      fontFamily: "Archivo Narrow, Archivo, sans-serif"
      fontSize: "13px"
      fontWeight: 600
      letterSpacing: "0.16em"
rounded:
  app-nick: "3px"
  pill: "999px"
  landing-pill: "999px"
  landing-notice: "10px"
  landing-window: "12px"
  landing-panel: "18px"
spacing:
  landing-maxw: "1120px"
  landing-gutter: "clamp(20px, 5vw, 40px)"
  app-maxw: "1600px"
  app-gutter: "clamp(14px, 2.2vw, 28px)"
  app-foot: "72px"
  app-section: "32px"
  cell: "15px 18px 14px"
  measure-min: "160px"
components:
  pill:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.landing.l-ink}"
    typography: "{typography.landing.l-pill}"
    rounded: "{rounded.pill}"
    padding: "10px 18px"
    border: "1px {colors.landing.l-line}"
  pill-solid:
    backgroundColor: "{colors.landing.l-ink}"
    textColor: "#FFFFFF"
  linput:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.landing.l-ink}"
    rounded: "{rounded.pill}"
    padding: "13px 18px"
    border: "1px {colors.landing.l-line}"
  btn:
    backgroundColor: "transparent"
    textColor: "{colors.app.ink}"
    typography: "{typography.app.mark}"
    rounded: "{rounded.app-nick}"
    padding: "7px 14px 6px"
    border: "1px {colors.app.ink}"
  btn-primary:
    backgroundColor: "{colors.app.ink}"
    textColor: "{colors.app.stock-raised}"
  btn-danger:
    backgroundColor: "transparent"
    textColor: "{colors.app.signal}"
    border: "1px {colors.app.signal}"
  mk:
    backgroundColor: "transparent"
    textColor: "{colors.app.ink-2}"
    typography: "{typography.app.mark}"
    rounded: "{rounded.app-nick}"
    padding: "2px 8px 1px"
    border: "1px {colors.app.rule-2}"
  mk-live:
    backgroundColor: "{colors.app.signal}"
    textColor: "{colors.console.kursbuch-signal-ink}"
  input:
    backgroundColor: "{colors.app.stock-raised}"
    textColor: "{colors.app.ink}"
    typography: "{typography.app.table}"
    rounded: "{rounded.app-nick}"
    padding: "8px 10px"
    border: "1px {colors.app.rule-2}"
  fig-tint-pos:
    backgroundColor: "{colors.app.pos}"
    textColor: "{colors.app.ink}"
    typography: "{typography.app.fig}"
    rounded: "{rounded.app-nick}"
    padding: "1px 7px"
  fig-tint-neg:
    backgroundColor: "{colors.app.neg}"
    textColor: "{colors.app.ink}"
  panel:
    backgroundColor: "{colors.app.stock-raised}"
    textColor: "{colors.app.ink}"
    rounded: "0px"
    padding: "16px"
    border: "1px {colors.app.rule}"
  sheet-doc:
    backgroundColor: "{colors.app.stock-raised}"
    textColor: "{colors.app.ink}"
    rounded: "0px"
    padding: "24px"
    border: "1px {colors.app.rule}"
  chat:
    backgroundColor: "{colors.app.stock-raised}"
    textColor: "{colors.app.ink}"
    rounded: "0px"
    border: "1px {colors.app.rule}"
  msg-user:
    backgroundColor: "{colors.app.ink}"
    textColor: "{colors.app.stock-raised}"
  msg-agent:
    backgroundColor: "{colors.app.stock}"
    textColor: "{colors.app.ink}"
    border: "1px {colors.app.rule}"
  glossary-pop:
    backgroundColor: "{colors.app.stock-raised}"
    textColor: "{colors.app.ink}"
    typography: "{typography.app.body}"
    rounded: "0px"
    padding: "11px 13px 12px"
    border: "1px {colors.app.ink}"
  info:
    backgroundColor: "transparent"
    textColor: "{colors.app.rule-2}"
    size: "14px"
  run-card:
    backgroundColor: "{colors.app.stock-raised}"
    textColor: "{colors.app.ink}"
    rounded: "0px"
    padding: "16px 16px 14px"
    border: "1px {colors.app.rule}"
  verdict-pass:
    backgroundColor: "#DCEFE3"
    textColor: "#0E5C33"
    typography: "{typography.app.mark}"
    rounded: "{rounded.app-nick}"
    padding: "1px 6px"
  verdict-void:
    backgroundColor: "{colors.app.signal-wash}"
    textColor: "#8A1021"
  seg:
    backgroundColor: "transparent"
    textColor: "{colors.app.ink-2}"
    typography: "{typography.app.mark}"
    rounded: "{rounded.pill}"
    padding: "8px 20px"
    border: "1px {colors.app.rule-2}"
  seg-on:
    backgroundColor: "{colors.app.ink}"
    textColor: "{colors.app.stock-raised}"
  pay-modal:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.landing.l-ink}"
    rounded: "{rounded.landing-panel}"
    width: "940px"
  pay-show:
    backgroundColor: "{colors.landing.l-ink}"
    textColor: "#F1F3ED"
---

# Design System: Tau

Tau ships **two visual worlds in one static app** (`app/static/index.html`, `app.css`,
`app.js`, served by `app/server.py`), plus a third surface that is the owner's private console.

1. **The Landing** — the pre-login Persuade surface (`body.landing-body` / `.landing`, rendered
   by `viewSignin()`). A calm, white, rounded Rubik product page. Tokens are `--l-*`.
2. **The App (Kursbuch)** — everything after sign-in. The station-timetable world: ink on grey
   stock, hairline rules, Archivo figures, dense tables, one reserved signal red. Tokens are the
   unprefixed `--stock / --ink / --signal / …` properties.
3. **Operator console (Kursbuch)** — the owner's control room in
   `data_pipeline/dashboard_server.py`. The same timetable world as the App, recorded as a
   secondary surface with `kursbuch-` tokens. The last section keeps its full record; the App
   world cross-references it rather than duplicating it.

The retired **"Tote Slip"** direction (green tote board, amber figures, thermal slips, stamps) is
**gone from the build** and is not documented here. No `board`, `amber`, `slip`, `counter` or
`stamp` token survives in the shipped CSS.

---

# World 1 — The Landing (Persuade surface)

## Overview

**North Star: "The Calm Product Page."** The pre-login page is copied in spirit from
catalyst.app: a near-white ground, near-black Rubik ink, roomy whitespace, rounded pill buttons,
and exactly one warm accent. It exists to persuade an invited visitor to continue with Google or
join the waitlist. It is deliberately the opposite of the dense timetable waiting behind the
login — nothing here is ruled, tabular, or signal-coded, and this world never displays money
state. The one piece of product proof is a single browser-mock preview on a soft textured panel.

**Key Characteristics:**
- Rubik throughout (400–700); no second family.
- Near-white ground (`{colors.landing.l-bg}`), near-black ink (`{colors.landing.l-ink}`).
- Rounded pill buttons at full `{rounded.pill}`; solid = ink fill, outline = white + hairline.
- One warm accent (`{colors.landing.l-accent}`), spent only on the logo cube's lit face and the
  preview's live-spinner.
- A browser-mock product preview on a textured warm gradient panel is the only ornament.
- No tables, no hairline rules, no signal red, no stock tints.

## Colors

- **Ground** (`{colors.landing.l-bg}` #FBFBFA): the page, applied by `body.landing-body`.
- **Ink** (`{colors.landing.l-ink}` #15161A): headline, wordmark, body, solid-pill fill and its
  text-on-white.
- **Ink 2** (`{colors.landing.l-ink-2}` #5B5F66): the hero deck (`.lsub`) and `.running` preview
  line.
- **Ink 3** (`{colors.landing.l-ink-3}` #8A8E95): fine print (`.lfine`), waitlist hints. *(See
  Defects — fails AA on the ground.)*
- **Line** (`{colors.landing.l-line}` #E7E6E2): pill and input hairline borders, spinner track.
- **Accent** (`{colors.landing.l-accent}` #F05A28): the cube's lit top face, the live-spinner's
  leading edge, the `.wlok` check, and `.landing ::selection`. Nothing else.

**Named Rule — Accent is a spark, not a surface.** `{colors.landing.l-accent}` appears only in
the logo cube and the spinner. It is never a button fill, a large field, or a text colour for
copy. The landing has no signal red; `--signal` (#C8102E) belongs to the App world and never
crosses the login.

## Typography

**Font:** Rubik only (`{typography.landing.l-hero}` through `{typography.landing.l-fine}`),
loaded 400/500/600/700 alongside the app's Archivo faces.

- **Hero** (`.lhero h1`, Rubik 600, `clamp(38px, 6.4vw, 68px)`/1.04, −0.03em, max 14ch): the one
  headline, sentence case ("Intelligence at your fingertips.").
- **Deck** (`.lsub`, Rubik 400, `clamp(17px, 2.1vw, 21px)`/1.5, Ink 2, max 46ch).
- **Wordmark** (`.lbrand`, Rubik 600, 20px, −0.01em) beside the cube.
- **Pill** (Rubik 500, 15px; 16px on `.lg`).
- **Preview line** (`.lline`, Rubik, `clamp(16px, 2.3vw, 22px)`).
- **Fine print** (`.lfine` / `.wlhint`, Rubik 400, 14px/1.6, Ink 3, max 60ch).

Everything on the landing is sentence case. Rubik is never uppercased here.

## Layout

A single centred column: `max-width: {spacing.landing-maxw}` (1120px) with a
`{spacing.landing-gutter}` gutter. Order: a flex nav (`.lnav`: brand left, Sign in + Join
waitlist pills right) → hero (h1, deck, optional error notice, CTA pair, fine print) → the
preview panel. Under 760px the nav and hero tighten and the CTA pills wrap; the preview stacks
naturally. There is no sidebar and no second column.

## Elevation & Depth

Unlike the App world, the landing **uses soft shadows** — this is native to the calm-product-page
world and is not a defect:
- **Pill rest** `0 1px 2px rgba(20,22,26,.04)`, **pill hover** `0 4px 14px rgba(20,22,26,.10)`
  with `translateY(-1px)`.
- **Preview window** `0 30px 60px -30px rgba(30,30,40,.4), 0 2px 6px rgba(30,30,40,.08)` — the
  white window floating over the gradient panel.
- **Input focus** `0 0 0 3px rgba(21,22,26,.08)` halo.

## Shapes

Rounded, everywhere. Pills and the email input are `{rounded.pill}` (999px). The preview panel is
`{rounded.landing-panel}` (18px), the inner window `{rounded.landing-window}` (12px), the error
notice `{rounded.landing-notice}` (10px). The textured panel is a 135° gradient (`#EFE7D8 →
#E7E8E2 → #E3E6EC`) under a multiply dot-screen. The window chrome carries three traffic-light
dots (`#F0635A / #F2BE4B / #64C963`).

Two bespoke SVG marks: the **cube** (filled: `#111` body, `#F05A28` lit face, `#fff` seam) and
the full-colour **Google "G"**. Preview rows reuse the app's 1.8-stroke `check` icon.

## Components

- **Pill** — `{rounded.pill}` button. Outline (`.pill`): white fill, `{colors.landing.l-line}`
  border, rest shadow. Solid (`.pill.solid`): `{colors.landing.l-ink}` fill, white text, hovers
  to `#000`. `.lg` enlarges padding/size.
- **Preview** (`.lpreview` / `.lwin`) — the signature ornament: textured gradient panel holding a
  white browser window with traffic-light chrome and three result lines (done cube line, done
  check line, running spinner line). Decorative, `aria-hidden`.
- **Waitlist** (`.wlbox`) — inline form: pill-radius email input (`#fff`, `l-line` border; focus
  → `l-ink` border + 3px halo) beside a solid pill submit, with `.wlhint` / `.wlok` status.
- **Payment modal** (`.pay-modal` / `.pay-split` / `.pay-show` / `.pay-right`) — the mandatory
  card gate shown over the app to a signed-in user with no card on file (`S.me.needs_card`). A
  blocking `<dialog>` built on the clean-world `.wl-modal` light tokens (white `#FFFFFF` ground,
  Rubik, `{rounded.landing-panel}` 18px radius, `wl-modal::backdrop` 45% ink blur), widened to
  `940px` and capped at `calc(100vh - 24px)`. A `1.04fr / .96fr` split: left `.pay-show` is an
  ink showcase panel (`{colors.landing.l-ink}` ground, `#F1F3ED` text) holding a faux white
  app-window (`.pay-stage-wrap`, 12px radius, soft drop shadow) that auto-rotates the three
  landing SCENE builders every 5.4s with a `.pay-cap` caption and `.pay-dots` progress bars; right
  `.pay-right` scrolls and holds the Stripe Payment Element (`.pay-el`, card + Apple/Google Pay)
  and a `.pay-signout` escape. Esc is suppressed (`cancel` prevented). Carousel is suppressed
  under `prefers-reduced-motion`; `.pay-show` is hidden ≤760px (modal narrows to `460px`).

## Do's and Don'ts

- **Do** keep the ground white and ink near-black; let whitespace carry the calm.
- **Do** use pills (solid primary, outline secondary) at full radius, with the soft shadows.
- **Do** confine the accent to the cube and the spinner.
- **Don't** import hairline rules, stock tints, tables, or signal red onto the landing.
- **Don't** make the accent a button fill or a large field.
- **Don't** uppercase Rubik, and don't add a second type family.

---

# World 2 — The App (Kursbuch, authed)

## Overview

**North Star: "The Station Timetable."** After sign-in the product is the Kursbuch world — a
departures board for money, not a trading terminal. Everything is printed on warm grey stock
(`{colors.app.stock}`), ruled with hairlines, and read top to bottom in a single centred column
of sections. Each page opens with **one status line** stating what the system is doing now; the
sections below are supporting evidence. Figures are tabular lining Archivo and sit on rules, in a
`measure` grid or a dense table — not in cards. **One reserved signal red** (`{colors.app.signal}`
#C8102E) is spent only where the operator must act. This is the same world as the operator
console (World 3); it is applied here to a retail trader, with plain-language leading copy and a
few bordered panels the console forbids.

**Key Characteristics:**
- Archivo + Archivo Narrow at weights 400/600; tabular lining figures everywhere.
- One reserved signal red for attention and the live-money boundary.
- P&L direction told by a tint field behind an ink figure — never a coloured number.
- Dense ruled tables and a `measure` grid, not cards.
- No shadow, gradient, glass, or blur anywhere; depth is rule weight plus stock tints.
- Two stocks: grey paper vs rose (`{colors.app.stock-live}`) for real money.

## Colors

A printed palette identical in value to the console's `kursbuch-*` set.

### Stocks (neutral grounds)
- **Paper Stock** (`{colors.app.stock}` #E9EBE5): the page, masthead, split's shaded half.
- **Live Stock** (`{colors.app.stock-live}` #EFE4E7): the rose page for real money.
- **Raised Stock** (`{colors.app.stock-raised}` #F1F3ED): panels, inputs, row hover, knocked-out
  text on an ink fill.
- **Sunk Stock** (`{colors.app.stock-sunk}` #DFE2DA): scrollbar tracks, skeleton low step.

### Ink
- **Ink / Ink 2 / Ink 3** (`{colors.app.ink}` / `{colors.app.ink-2}` / `{colors.app.ink-3}`):
  figures and section rules; secondary prose and default mark text; labels, column heads,
  sub-figures, hints, captions, chart axes.

### Rules
- **Rule / Rule 2** (`{colors.app.rule}` / `{colors.app.rule-2}`): 1px row and cell dividers;
  the heavier 1px under a column head and around inputs, chips, dashed empties.

### Signal (reserved)
- **Signal Red** (`{colors.app.signal}` #C8102E): the `.needs` status line's `em` segments, the
  armed/live marks, the danger/stop/armed buttons, the `on` switch, the `autopilot.on` border,
  the live run-row pulse dot, the live-row strategy link, the input caret, `error-text`, and
  `notice.bad`. Nothing else.
- **Signal Wash** (`{colors.app.signal-wash}` #F8E4E6): the armed mark and bad-notice fill.

### Direction tints
- **Positive / Negative Tint** (`{colors.app.pos}` #D9E7D6 / `{colors.app.neg}` #F0DEDC):
  desaturated fields laid behind a money figure to tell direction. The figure stays ink.

### Named Rules
**The Reserved Signal Rule.** `{colors.app.signal}` means "this needs you" or "this is real
money." It is never spent on a losing number, a heading, a link, or decoration.

**The Money-Rides-a-Field Rule.** P&L direction is a tint field (`pos` / `neg`) behind an ink
figure, never a coloured figure. In the CSS, `.gain` and `.loss` both resolve to `{colors.app.ink}`
on purpose — a losing number is a number, not an alarm.

**The State-Not-By-Colour Rule.** Every coloured state also carries a word or shape: marks read
PAPER / PASSED / LIVE / PAUSED, stale sections go dashed and strike their figures, the status line
swaps a check glyph for a triangle. Greyscale still reports correctly.

**The Two-Stocks Rule.** Paper sits on `{colors.app.stock}`; real money sits on
`{colors.app.stock-live}` (`body.live-service`), which also turns the masthead rule and active
tab signal red. The two surfaces must never be confusable at a glance.

## Typography

**Display/Body:** Archivo (400/600). **Label:** Archivo Narrow. No third family; no 300/500/700
in app chrome. `font-variant-numeric: tabular-nums lining-nums` is set on `body` and restated on
numeric cells.

- **Page Title** (`h1.page`, Archivo 600, `clamp(23px, 3vw, 30px)`, −0.02em): one per page,
  sentence case. On a strategy sheet (`.sheet-doc h2`) it is `clamp(22px, 2.6vw, 30px)`.
- **Status Line** (`.statusline .said`, Narrow 600, `clamp(15px, 2vw, 19px)`/1.35): the one
  dominant answer.
- **Figure** (`.fig`, Archivo 600, `clamp(21px, 2.6vw, 27px)`, −0.015em; `.fig.sm` 17px; dial
  output 18px).
- **Section Head** (`.sect-head h2`, Narrow 600, 13px, 0.13em, uppercase) over a 2px ink rule.
- **Body** (Archivo 400, 14px/1.45); thesis 16px/1.6, prose capped 70–72ch.
- **Table** (13px; column heads Narrow 600 12px, 0.02em).
- **Micro-label** (`.lab` / `.field > span`, Narrow, 11px, 0.11em, uppercase) above every figure
  and field.
- **Mark / Button / Chip** (Narrow 600, 11–11.5px, 0.08–0.1em, uppercase).
- **Wordmark** (Narrow 600, 13px, 0.16em, uppercase): "RECURSIVE / &lt;service&gt;".

**The Short-Caps Rule.** Uppercase is reserved for short Narrow labels: section/column heads,
micro-labels, marks, chips, buttons, tabs, the wordmark. Sentences — decks, theses, notices,
empty-state copy, chat — are sentence case.

## Layout

A single centred column, `max-width: {spacing.app-maxw}` (1600px), `{spacing.app-gutter}` gutter,
`{spacing.app-foot}` foot. Shell stacks: masthead (2px ink rule; wordmark left, user + Sign out
right) → service nav (`.services`, five uppercase Narrow tabs over a 1px rule; current tab gets a
2px ink bottom border) → page title + deck → status line → sections.

Sections (`.sect`) sit `{spacing.app-section}` apart, each opened by a `.sect-head` that flexes
its `h2` and note to opposite baselines over a 2px ink rule. Measured figures use `.measure`: an
auto-fit grid of `minmax(160px, 320px)` cells split by 1px left rules, the first cell flush-left.
Two-column pages set a fixed rail beside the main column: Dashboard `360px`, Strategy detail
`340px`, Deploy chat `400px`, Research printer a `340px` dispatch form; 24–28px gaps.

**The Flush-Edge Rule.** The leftmost measure/table cell drops its padding and rule so figures
align to the page title's vertical.

A section head that carries a filter toolbar instead of a text baseline uses `.section-head.filters`:
it centres its contents and widens the bottom padding to `14px` so the 30px chips clear the 2px rule.

**Breakpoints**
- **≤ 1080px:** `.dash / .detail / .deploy / .printer / .funds / .split` collapse to one column;
  the chat goes static at `72vh`, and the Deploy page reveals its `.seg` board/chat toggle.
- **≤ 760px:** `.measure` drops to two columns (rule on even cells only); `.sheet` bleeds to the
  device width by negative-gutter margins; `.stack` tables restack into labelled rows printing
  `data-lab` on the left; `.doc-mark` goes static; landing nav/hero/pills tighten.

## Elevation & Depth

**There are no shadows, gradients, glass, or blur in the App world.** Depth is printed: rule
weight and four stock tints.
- **2px solid ink** — masthead and section-head rules (2px signal on the live masthead).
- **1px rule-2** — under column heads, around inputs and chips.
- **1px rule** — row, cell, panel, and nav dividers.
- Tonal layering: `stock-raised` lifts a panel/input/hovered row; `stock-sunk` recesses a
  scrollbar.

**The Printed-Depth Rule.** If something needs to separate, rule it or tint it; never lift it.

## Shapes

Rectangles at zero radius. The only app radius is `{rounded.app-nick}` (3px), on small inset
objects: marks, buttons, inputs, selects, chips' nicks, the `.fig.tint` field, dashed empties.
Chips and the switch track are full `{rounded.pill}` (999px). Borders are hairlines except the
two structural 2px rules.

Icons are inline SVG at 24×24, `stroke-width: 1.8`, round caps/joins, `currentColor` (`I()` in
`app.js`). The wordmark glyph is a single-stroke R at stroke 6. No icon font.

**The Drawn-Icon Rule.** Icons are authored 1.8-stroke SVG in `currentColor`. No glyph package.

## Components

### Buttons
- **Base** (`.btn`): Narrow 600, 11.5px, 0.1em, uppercase, 1px ink border, transparent fill, 3px
  nick, `7px 14px 6px`. Hover fills ink with `stock-raised` text; active `translateY(1px)`.
- **Primary**: ink fill, `stock-raised` text, hovers to `#000`.
- **Danger / Armed**: signal border + text; fills signal with `kursbuch-signal-ink` text on hover
  / when armed. Reserved for arming or stopping live money.
- **Disabled**: `rule-2` border, `ink-3` text, `not-allowed`. **Small** (`.sm`): 11px.
- **Busy** (`.btn.busy`): pointer-events off, 0.7 opacity.

### Status Line (signature)
`.statusline` is the page's one dominant answer: Narrow 600 clamp sentence, `em` segments in
`ink-3`, over a 1px rule, segments joined by a `rule-2` middot. Adding `.needs` turns the `em`
segments `{colors.app.signal}` (e.g. "Backtest history stale 63m").

### Measure grid + Figures
`.measure` auto-fit cells, each a `.lab` micro-label over a `.fig`. `.fig.tint.pos` /
`.fig.tint.neg` wraps the figure in a `pos` / `neg` field (`1px 7px`, 3px nick, `-7px` left
margin to stay flush). A `.sub-fig` caption sits below in `ink-3`.

### Marks (state pills)
`.mk`, Narrow 600 11px, 3px nick. `.mk` default = `ink-2` on transparent with a `rule-2` border
(PAPER, OFF). `.mk.on` = solid ink, knocked-out text (the affirmative permanent state).
`.mk.armed` = signal text on `signal-wash`. `.mk.live` = solid signal, `kursbuch-signal-ink`
text — the loudest object. `.mk.quiet` = `ink-3`. The strategy sheet's `.doc-mark` is the larger
13px variant (PASSED).

### Tables
`.sheet` wraps a hairline-ruled table: Narrow column heads over a `rule-2` divider,
right-aligned tabular `.num` cells, `td.name` bold with underlined links, wrapped `.cellwrap`
at 52ch, `tr:hover` → `stock-raised`. `tr.live-row td.name a` turns signal. `.stack` + `data-lab`
restacks under 760px. `.empty` is a dashed `rule-2` box.

### Panels & the Strategy Sheet
Containers here are **bordered, unshadowed, filled rectangles** — a licence the console denies:
- **Panel** (`.panel`): 1px `rule` border, `stock-raised` fill, 16px pad, Narrow head. Rail
  content (Daily P&L, Open positions, Settled lately).
- **Sheet** (`.sheet-doc`): the strategy detail. 1px `rule` border, `stock-raised` fill, 24px
  pad, an absolute `.doc-mark` (PASSED) top-right, an h2 title, a thesis, a `.rules` list (dash
  bullets), an SVG equity `.chart` with a dashed "UNSEEN BY THE AGENT →" cutoff, a `.split`, and
  a `.gates` list.
- **Split** (`.split`): in-sample vs out-of-sample, two columns, second half shaded `stock`,
  divided by a 1px rule.
- **Gates** (`.gates`): pass list; `.ok svg` ink check, `.no svg` signal cross, value right.
- **Dials** (`.dial`): native `range` with ink `accent-color`, 18px Archivo output; moving a dial
  re-runs the sheet.
- **Exact spec** (`details.raw pre`): the one monospace block — a collapsed raw-JSON code view
  (`ui-monospace`), not a label.

### Inputs / Fields / Chips / Switch
- **Input**: `stock-raised` fill, 1px `rule-2` border, 3px nick, 15px, `8px 10px`, full width.
  Hover → `ink-3` border; focus → ink border + `stock` background, native outline removed; caret
  `{colors.app.signal}`. Wrapped in `.field` under a `.lab`. Error text is `error-text` signal.
- **Choice** (`.choice .opt`): radio cards; Narrow uppercase title over a 12.5px description,
  `rule-2` border; checked inverts to an ink fill with knocked-out text.
- **Chip** (`.chip`): pill filter, Narrow 600 11.5px uppercase, `rule-2` border; `aria-pressed`
  fills ink.
- **Switch** (`.switch`): 42×24 pill track, `rule-2` off / `{colors.app.signal}` on, sliding
  white knob.

### Agent Chat (signature)
`.chat` is a bordered `stock-raised` panel, sticky on desktop (static `72vh` ≤ 1080px), with
head / messages / composer rows. `.msg.user` ink bubbles right; `.msg.agent` `stock` bubbles with
a rule border left; `.msg.system` dashed full-width. The `.autopilot` bar borders signal when on.
`.typing` is three bouncing 5px dots. `.proposal` boxes carry APPROVE / DECLINE.

### Research Printer
`.printer` sets a `340px` dispatch form beside a `.log` feed (52px Narrow time column, hairline
rows, `.error` rows in signal).

### Glossary bubbles (signature)
A drawn info marker plus one shared top-layer popover explains the agent's jargon
(Passed / Void / Rejected / unseen data / in-sample / gates) inline. `.info` is a 14×14 bare
button carrying the 1.8-stroke `ICON.info` ("i" in a circle), `{colors.app.rule-2}` at rest and
`{colors.app.ink}` on hover/focus; it sits beside a term, `cursor: help`. One body-level
`.glossary-pop` serves them all (so it never clips inside a table): `position: fixed`, max 268px,
`{colors.app.stock-raised}` fill, 1px `{colors.app.ink}` border, with an uppercase Narrow 11px
`b` term over a sentence-case 12.5px/1.5 `{colors.app.ink-2}` body. Shown on hover, focus, and
tap; dismissed on Esc, scroll, resize, or outside click; a `.14s` `glopop` rise honors
`prefers-reduced-motion`. *(Carries a drop shadow — see Defects.)*

### Session cards (`.runs` / `.run-card`)
The research index is a responsive card grid (`.runs`, auto-fill `minmax(290px, 1fr)`, 14px gap)
rather than a table — the one place the App world uses cards. Each `.run-card` is a hairline
`1px {colors.app.rule}` rectangle on `{colors.app.stock-raised}` with a **3px outcome-coloured
left border**: `.ok` green (#1A7F4B), `.void` `{colors.app.rule-2}`, `.fail`
`{colors.app.signal}`, `.live` `{colors.app.ink}`. A 3-line-clamped `.run-title`, a Narrow
`.run-meta`, and a `.run-foot` (`.run-state` + Narrow `.run-when`). Hover lifts the border to
`{colors.app.ink-3}` and nudges `translateY(-1px)`. *(The success-green is off-palette — see
Defects.)*

### Working spinner (`.working`)
An in-process indicator beside "Researching" / "Waiting": a `0.7em` ring, `2px`
`{colors.app.rule-2}` track with a `{colors.app.signal}` leading edge, spinning `lspin` at `.8s`
(slowed to `2.4s` under `prefers-reduced-motion`). Scales to 16px inside a `.m dd` figure cell.
*(Signal red on a loading edge is a mild widening of the Reserved Signal Rule — see Defects.)*

### Verdict badges (`.log .verdict`)
Inline agent-log tags marking a hypothesis's result: `.verdict.pass` is green text #0E5C33 on
#DCEFE3; `.verdict.void` is #8A1021 on `{colors.app.signal-wash}`. Narrow, 11.5px, 0.06em, 3px
nick; the `li.verdict` row gets a faint `stock-raised → transparent` wash. *(The pass-green pair
is off-palette — see Defects.)*

### Segmented toggle (`.seg`)
A one-of-two pill switch, `display: none` on desktop and revealed `inline-flex` only ≤1080px, used
on the Deploy page to swap between the board and the agent chat (`.deploy[data-view]`) so the
composer is reachable without scrolling the whole board. Full `{rounded.pill}` track, 1px
`{colors.app.rule-2}` border, Narrow 600 12px uppercase buttons; the `aria-pressed="true"` button
fills `{colors.app.ink}` with `{colors.app.stock-raised}` text.

## Motion

One authored moment plus short state transitions, all collapsed by `prefers-reduced-motion`.
- **wash** (`.washed`, 0.5s `--ease`, `rule-2` → transparent): fired on a figure whose value just
  changed.
- **pulse** (1.6s, signal dot): an active run row. **dot** (1s, typing). **shimmer** (1.4s,
  skeleton). **btn** (0.16s colour), **switch** (0.2s knob).

## Do's and Don'ts

- **Do** open every page with a status line and put the measured result first.
- **Do** tell P&L direction with a `pos` / `neg` tint field behind an ink figure.
- **Do** keep `tabular-nums lining-nums` on anything numeric.
- **Do** give every table `.stack` + `data-lab`; reserve uppercase for short Narrow labels.
- **Do** pair every coloured state with a word or shape.
- **Don't** add a shadow, gradient, glass, or a coloured P&L number.
- **Don't** spend signal red on anything but attention or the live-money boundary.
- **Don't** add a third family, a third weight, or a radius beyond the 3px nick (chip/switch pills
  excepted).
- **Don't** let paper and live stocks converge; live is rose stock plus a signal masthead and tab.
- **Don't** add a build step or framework; the surface is vanilla HTML/CSS/JS from `app/static/`.

---

# World 3 — Operator console (data_pipeline/dashboard_server.py): Kursbuch

Scope: the owner's private control room served by `data_pipeline/dashboard_server.py` (CSS and JS
embedded in Python string literals). **This is the same station-timetable world as World 2 (the
authed App)** — identical token values, Archivo/Archivo Narrow, the reserved signal red, the two
stocks, no shadow. The App world carries these rules onto the customer product; the only
divergence is container licence: this console forbids any filled card (sections plus one `plate`),
while the App permits bordered, unshadowed panels (`.panel`, `.sheet-doc`, `.chat`, `.split`) for
the explanation a retail user needs. Its tokens carry a `kursbuch-` prefix. The sub-sections below
keep the original record, with headings demoted.

**Original name:** Kalshi BTC 15M Control Room. A Swiss station timetable for a single operator
watching real money: ink on stock, hairline rules, one reserved signal colour.

### Overview

**Creative North Star: "The Station Timetable"**

This is a departures board for money, not a trading terminal. Everything is printed on a warm
grey stock, ruled with hairlines, and read top to bottom in a single column of sections. Figures
sit on a rule; they never sit in a card. The page has no shadow, no gradient, no glass, no blur,
and no rounded panel: the only radius in the system is a 3px hairline nick on small inset objects.
Depth is a printing problem, solved by rule weight and by two stock tints, never by lifting
anything off the page.

The world deliberately refuses the terminal look that trading software defaults to. **There is no
monospace anywhere in the console build** — not in tables, not in chart axes, not in identifiers.
Alignment of figures is bought with `font-variant-numeric: tabular-nums lining-nums` set on `body`
and reasserted on every numeric cell. Typography is one family in two cuts (Archivo and Archivo
Narrow) at two weights (400 and 600). The narrow cut carries every label, head, chip, tab and
status line; the normal cut carries sentences and figures.

The page is built to be read by one operator at a glance, so the system spends its scarcity budget
on a single reserved red. Money direction is never told in that red; it rides a desaturated tint
field behind the figure instead. The whole surface is plain CSS and vanilla JS inside Python
string literals — no build step, no framework, no icon package, one Google Fonts import.

**Key Characteristics:**
- Ruled rows on stock; no cards, no shadows, no gradients, no glass.
- One reserved signal red, spent only on attention and on the live-money boundary.
- Two stocks — grey newsprint for paper, rose-tinted for real money.
- Archivo + Archivo Narrow, two weights, tabular lining figures everywhere.
- No monospace, anywhere, ever.
- One authored motion: a 180ms wash on a figure whose value just changed.

### Colors

A printed palette: warm grey-green newsprint, near-black ink in three steps, two rule greys, and
one reserved red that appears on perhaps two percent of any screen.

#### Primary
- **Signal Red** (`{colors.console.kursbuch-signal}`): the reserved colour — the status line when
  the operator is needed, the stale rule and note, the armed/halted marks, the destructive button,
  notices, the caret, the live masthead rule, and the dashed LIVE cutoff on charts. Nothing else.
- **Signal Wash** (`{colors.console.kursbuch-signal-wash}`): the red's only fill, behind an armed
  mark and inside a notice box.
- **Signal Ink** (`{colors.console.kursbuch-signal-ink}`): the near-white on a solid red fill.

#### Secondary
- **Paper Stock** (`{colors.console.kursbuch-stock}`): the grey newsprint page (simulation /
  pipeline).
- **Live Stock** (`{colors.console.kursbuch-stock-live}`): the rose page, via `body.live-service`,
  with a red masthead rule and red active-tab underline.
- **Raised Stock** (`{colors.console.kursbuch-stock-raised}`): chart plates, inputs, row hover,
  knocked-out text on ink.
- **Sunk Stock** (`{colors.console.kursbuch-stock-sunk}`): scrollbar tracks only.

#### Tertiary
- **Positive / Negative Tint** (`{colors.console.kursbuch-pos}` / `{colors.console.kursbuch-neg}`):
  desaturated fields behind a money figure to tell direction; the figure stays ink.
- **Trace Set** (`{colors.console.kursbuch-trace-ink}`, `-umber`, `-slate`, `-olive`, `-plum`):
  the five chart line colours, cycled in order and each paired with a distinct dash pattern (`[]`,
  `[6,3]`, `[2,3]`, `[9,3,2,3]`, `[4,2]`) so a series is identifiable without colour.

#### Neutral
- **Ink / Ink 2 / Ink 3** (`{colors.console.kursbuch-ink}` / `-ink-2` / `-ink-3`): body, figures,
  section rules; secondary prose; labels, column heads, axes.
- **Rule / Rule 2** (`{colors.console.kursbuch-rule}` / `-rule-2`): the hairline system.

#### Named Rules
**The Reserved Signal Rule.** `{colors.console.kursbuch-signal}` means "this needs you" or "this
is real money." A sixth use dilutes the other five.

**The Money-Rides-a-Field Rule.** Direction is a tint field behind an ink figure, never a coloured
figure and never the reserved red.

**The Two Stocks Rule.** Paper on `{colors.console.kursbuch-stock}`; real money on
`{colors.console.kursbuch-stock-live}` via `body.live-service`, which also swaps the masthead rule
and active tab to signal.

**The State-Not-By-Colour Rule.** Every coloured state also carries a word or shape; remove colour
and the page still reports correctly.

### Typography

**Display/Body:** Archivo. **Label:** Archivo Narrow. Two weights (400, 600). No monospace, ever;
`tabular-nums lining-nums` buys column alignment.

#### Hierarchy
- **Page Title** (`h1.page`, 600, `clamp(23px,3vw,30px)`, −0.02em): one per page, sentence case.
- **Status Line** (`.said`, Narrow 600, `clamp(16px,2.1vw,20px)`/1.35).
- **Figure** (`.fig`, 600, `clamp(21px,2.6vw,27px)`, −0.015em); `.fig.sm` 17px.
- **Section Head** (Narrow 600, 13px, 0.13em, uppercase) over a 2px ink rule.
- **Body** (Archivo 400, 14px/1.45); prose 68ch, legends 66ch, status line 104ch.
- **Table** (13px; heads Narrow 600 12px 0.02em).
- **Micro-label** (`.lab`, Narrow 400, 11px, 0.11em, uppercase).
- **Mark / Button / Chip** (Narrow 600, 11–11.5px, 0.07–0.1em, uppercase).
- **Wordmark** (Narrow 600, 13px, 0.16em, uppercase).

#### Named Rules
**The No-Monospace Rule.** No monospace anywhere, including chart axes and identifiers. (The
customer App relaxes this only for the collapsed raw-spec JSON code view.)

**The Short-Caps Rule.** Uppercase for short labels only; sentences are sentence case.
snake_case model names stay lowercase on purpose.

**The Two-Weights Rule.** 400 and 600 only; emphasis is the narrow cut, letterspacing, and case.

### Layout

A single centred column, `max-width: 2560px`, fluid gutter, 64px foot. Masthead (2px ink rule, red
on live) → service nav (1px rule, three tabs) → page title + deck → status line → sections.
Measured figures use `.measure` (auto-fit `minmax(150px,1fr)`, 1px vertical rules). Tables are
fixed-layout with per-table width classes and `min-width: 860px` in a scrollable `.sheet`; column
heads stick.

**Breakpoints:** ≤ 640px `.stack` tables restack to labelled rows; ≤ 860px `.measure` → two
columns and `.sheet` bleeds full-width; ≥ 1500px `.plates` → two columns; ≥ 2200px three; Print →
white, nav/buttons removed.

**The One Dominant Answer Rule.** Each page opens with one status line; sections below are
evidence. On a phone that line owns the first viewport.

**The Flush-Edge Rule.** The leftmost measure/table cell drops its padding and rule.

### Elevation & Depth

**No shadows in this system.** Not one `box-shadow`, gradient, blur, or backdrop-filter. Depth is
rule weight (2px ink / 2px signal / 1px rule-2 / 1px rule) plus four stock tints. On the live
surface the plate inverts to `{colors.console.kursbuch-stock}`.

**The Printed-Depth Rule.** If something needs to separate, rule it or tint it. Never lift it.

### Shapes

Rectangles at zero radius; the only radius is 3px on small inset objects (marks, chips, buttons,
inputs, selects, tint fields). The one non-rectangular form is the authored 24×24 status glyph pair
(circled check, warning triangle), SVG at `stroke-width: 1.6`, `currentColor`.

**The Hairline-Nick Rule.** 3px on inset objects, 0 elsewhere.
**The Drawn-Icon Rule.** Inline 1.6-stroke SVG, `currentColor`. No icon font.

### Components

#### Buttons
Hard rectangle, 3px nick, 1px ink border, transparent fill. Primary Narrow 600 11.5px 0.1em
uppercase; hover fills ink over 160ms; active `translateY(1px)`; disabled drops to rule-2 / ink-3;
danger uses signal; small 11px.

#### Chips
Narrow 600 11.5px 0.07em uppercase, `ink-2` on transparent, 1px rule-2 border, 3px nick; hover →
ink. No selected state; chips are navigation.

#### Marks
Narrow 600 11px 0.09em uppercase, 3px nick. Default `ink-2`/rule-2 (OFF); `.on` solid ink; `.armed`
signal on wash; `.halt` solid signal; `.quiet` ink-3.

#### Containers
No cards. **Section** (`.sect`): unfilled region opened by a ruled head. **Plate** (`.plate`): the
only filled container — 1px rule border, `stock-raised` fill (inverted on live), 10px 12px 6px,
zero radius; holds a chart and its legend.

#### Inputs / Fields
`stock-raised` fill, 1px rule-2 border, 3px nick, `6px 9px`, tabular. Hover → ink-3; focus → ink
border + `stock` background; caret signal. Disclosure `+`/`−` prefix.

#### Navigation
Masthead wordmark + `.asof` read-clock; 2px ink bottom rule (signal on live). Three Narrow 12.5px
tabs; `aria-current` → ink bottom border (signal on live). Mobile: the strip wraps; no drawer.

#### Status Line (signature)
`.statusline`: authored 17px SVG mark + Narrow 600 clamp sentence, capped 104ch, over a 1px rule.
Calm = ink-3 check; `.needs` = signal triangle and signal `em` segments. `em` is reset to normal
style — the alarm is colour + glyph, not italics.

#### As-of Rule (signature)
`.sect` + `.sect-head` (h2 + note) over a 2px ink rule; the note reads `as of <n>s ago`. Adding
`.stale` breaks the rule four ways: 2px dashed signal head rule; note turns signal 600; a
`.stale-mark` ("STALE 13D") prefix; every figure/cell struck through and dropped to ink-3.

#### Charts
Canvas at device pixel ratio; axis labels `11px "Archivo Narrow"` ink-3; zero line 1px ink. Series
cycle five trace colours + five dash patterns. The live cutoff is a dashed signal vertical labelled
LIVE. Bands fill at 7–10% alpha.

### Do's and Don'ts

#### Do:
- Separate with a rule or a stock tint (2px ink / 2px signal / 1px rule-2 / 1px rule).
- Put every figure block on a `.measure` grid and every dataset in a `.sect` with a live note.
- Tell money direction with a `.fig.tint.pos` / `.neg` field behind an ink figure.
- Keep `tabular-nums lining-nums` on anything numeric.
- Reserve uppercase for short labels; write sentences in sentence case.
- Give every table `.stack` + `data-lab`; pin column widths via `colgroup` + `.t-*`.
- Pair colour with a word or shape; draw icons inline as 1.6-stroke SVG.

#### Don't:
- Add a shadow, gradient, glass, or a card. Containers are sections and plates only.
- Use a monospace font anywhere.
- Spend `{colors.console.kursbuch-signal}` on anything but attention or the live-money boundary.
- Colour a P&L figure itself.
- Introduce a third family, a third weight, or a radius other than 3px.
- Uppercase a sentence or an identifier.
- Add a second animation beyond `.washed` and the 160ms button colour change.
- Add a build step, framework, icon package, or runtime dependency.
- Let the live surface and paper surfaces converge.

---

# Defects observed (carried by the build, not canonized)

These are recorded so future surfaces do not inherit them as rules, and are **not** fixed in code
here:

- **Landing Ink 3 fails AA.** `{colors.landing.l-ink-3}` #8A8E95 on `{colors.landing.l-bg}`
  #FBFBFA is ~3.18:1, below WCAG 2.2 AA 4.5:1 for the 14px `.lfine` fine print and 13.5px
  `.wlhint`. PRODUCT.md sets AA as the floor; this is a contrast defect, not a token to reuse.
- **Un-tokenized landing one-offs.** The sign-in error banner `.lnotice` (`#FDECE8` / `#8a2a12` /
  `#F3C9BB`), `.wlhint.bad` (`#b4310f`), the preview gradient stops, and the traffic-light dots
  are hard-coded off the `--l-*` palette. They are carried as-is; new landing surfaces should
  introduce real tokens rather than copy these hexes.
- **Landing cube uses `#111`, not `{colors.landing.l-ink}`** (#15161A). A minor hard-coded
  divergence inside the logo SVG; not a palette rule.
- **App `.gain` / `.loss` resolve to ink by design** — this is correct (money rides a field), noted
  only so it is not mistaken for a missing colour.

- **Product name is "Tau" everywhere user-facing and in this record.** Wordmark, logo (`TAU_MARK`),
  UI copy, `name: Tau` frontmatter, and the `.impeccable/` title all read **Tau**. Only deployed
  infrastructure keeps the old **Recursive** codename on purpose — the `X-Recursive` CSRF header,
  the `recursive-*` systemd units, the `/recursive/*` SSM parameters, and the `Recursive*` IAM
  policy names — because renaming live identifiers is a migration, not a doc edit. The old landing
  "cube" mark is also gone: `cube` now resolves to
  `TAU_MARK` (a 15px-radius `#15161A` tile with a stroked T and an `#F05A28` dot), so the Landing
  Shapes "cube" description is stale.
- **`.glossary-pop` carries a drop shadow** (`0 12px 26px -14px rgba(25,27,22,.42)`), as does the
  payment modal's faux app-window (`.pay-stage-wrap`). The App (Kursbuch) world's Printed-Depth
  Rule forbids shadows; these top-layer/overlay surfaces carry one anyway. Recorded as a
  divergence, not promoted into the depth system — ruled/tinted surfaces stay flat.
- **`.working` spends signal red on a loading edge.** The in-process spinner's leading edge is
  `{colors.app.signal}`, not ink. This widens the Reserved Signal Rule (attention / live money)
  to a progress indicator. Carried as shipped; not canonized as a new signal use.
- **Off-palette success greens.** `.run-card.ok` (#1A7F4B), `.log .verdict.pass` (#0E5C33 on
  #DCEFE3) introduce a green that is not a Kursbuch token and sits outside the world's "no
  green-for-good; money rides a field" discipline. They are legible and reused, so recorded in the
  frontmatter as literal component values, but they are **not** a palette token — future surfaces
  should not treat green-for-good as a system colour without a decision.
- **Landing scene eyebrows (kickers).** The redesigned landing ships three accent-wash pill
  eyebrows (`.scene-copy .eyebrow`: "See the homework", "Deploy & monitor", "RSI agent mode"). An
  eyebrow/kicker is a craft-floor refusal; it is recorded here as a defect the build carries and is
  **not** written into the Landing world as a reusable label style. The broader landing redesign
  (`.lhero` two-column grid, `.demo`, `.scenes`, `.section-band`, `.steps3`, `.fgrid`, `.faq`,
  `.lfoot`, `.wl-modal`) is pre-existing drift from this record's single-column Landing world and
  was left unrepaired this pass.

Both app-world surfaces (World 2 and World 3) share identical token values; they are documented
separately only because they are reached by different scopes and differ in container licence. No
drift between them was repaired.
