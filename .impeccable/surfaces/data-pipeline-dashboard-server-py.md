---
version: 1
slug: "data-pipeline-dashboard-server-py"
primary_target: "data_pipeline/dashboard_server.py"
related_targets: []
---

# Kalshi Trade control room

Scope: the whole dashboard served by `data_pipeline/dashboard_server.py` — Live Trading, Simulated
Trading, Data Pipeline, and the table browser. Visitor mode: **Operate**.

Audience: one operator, the system's own author. No second audience. Job, in priority order: watch
real money move; judge whether a paper strategy earned promotion; confirm the pipeline is alive.
Read on ultrawide, laptop, and phone — all first-class. Hard constraint: plain CSS + vanilla JS
inside Python strings, no build step, no framework.

## Direction contract

THESIS: A station timetable, not a terminal. The densest numbers anyone ever had to read fast,
standing up, under pressure — solved on paper a century before the trading screen existed. It
refuses the category's near-black-plus-neon arrangement and its equal-weight wall of identical
cards, where every panel shouts at the same volume and nothing tells you where to look.

OWN-WORLD: Warm uncoated stock (#F2F0EA), ink that is never pure black (#16130E), hairline rules at
one weight, one reserved signal red (#C8102E) that appears nowhere but "this needs you". Archivo and
Archivo Narrow only, two weights, tabular lining figures everywhere and no monospace anywhere.
Ruled rows instead of cards; no shadows, no glass, no gradients — ink does not glow. Money direction
rides a desaturated tint field behind the figure, never the reserved red. The live surface prints on
a different stock (#F6EDE0) with a red head rule, the way a timetable tints a different service.

STORY: He arrives asking "what is it doing right now." One ruled status line answers in words before
any number is read. Cash, exposure and risk follow as a single measured row. Strategies are rows in a
service table with their switches inline. He leaves knowing the state, or he acts, in seconds.

FIRST VIEWPORT: Head rule with product name left, live as-of clock right. Immediately beneath, a
full-width STATUS LINE setting the single dominant fact in words ("LIVE TRADING OFF · 3 ARMED · NO
OPEN POSITIONS · ALL WRITERS CURRENT"), red only if it needs him. Then the account row — cash,
equity, today, risk — four measured figures on one ruled line, no card around any of them. Then the
strategies table, each row carrying its live record, its sim record, prob/edge/signal, and its
on/off switch at the right. On phone, the status line and account row own the first screen and the
tables demote to a reachable index. Primary action, the strategy switch, always sits at row end.

FORM: Kursbuch — the Swiss station timetable — candidate 4 of seven on my grounded list, assigned by
seed key abd048b8. Raised by six named donations: literal naming with units and as-of (industrial
quote grammar), one dominant answer on phone (gravity-rain garden), one reserved signal colour by law
(CRT arcade), bar length as true duration (Labanotation), one face / two weights / one rule / one
radius / never pure black as law (civic prospectus), and all five strategies overlaid on one ruled
field at a known scale (oscilloscope signal bench).

Signature interaction — **the as-of rule**: every panel header carries a hairline rule and its own
"as of HH:MM:SS". When the writer behind that panel stops, the rule breaks to dashed, the figures go
struck and muted, and a red STALE mark states the age. No toast, no modal, no banner: the page tells
the truth in its own typography. This is the direct answer to two writers being dead for 13 days
while the old UI rendered their last values as current.

Motion grammar: 150–250ms, exponential ease-out. Exactly one authored moment — a figure's tint field
washes once, 180ms, when its value actually changes, so "what moved since I looked away" is answered
physically. Nothing else animates. Honours `prefers-reduced-motion`.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the
verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Unresolved

- Whether the Data Pipeline tab should fold into the control room as a single health rule rather
  than remain a separate tab. Built as a separate tab for now, with its health surfaced in the
  status line so the operator never has to visit it to learn something is wrong.
