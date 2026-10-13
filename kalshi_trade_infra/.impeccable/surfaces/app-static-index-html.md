---
version: 1
slug: "app-static-index-html"
primary_target: "app/static/index.html"
related_targets: ["app/static/app.css","app/static/app.js"]
---

# Recursive customer app

Scope: the whole customer web app (`app/static/`): sign-in, Dashboard, Research hub, Strategies,
Strategy detail (thesis, backtest, what-if), Deploy (live board + agent chat), Funds.
Visitor mode: **Operate**. Desktop and phone are both first-class.

Audience: retail traders, non-quants, who judge strategies by money. Job: dispatch research,
deploy what passed, watch it trade, steer it with the agent. Constraints: vanilla HTML/CSS/JS,
no build step; paper and live money must never be confused.

## Direction contract

THESIS: Every strategy is a printed slip: numbered, staked and stamped, hanging under a live tote board. We refuse the dark neon trading terminal and the white brokerage card grid.

OWN-WORLD: Tote green (#0F3A2C) owns the top band of every screen as one committed field, with amber (#FFB31A) figures on it. Slips are cool thermal white (#F6F7F4) with perforated top edges, ink #23262B, and numbered serials. Rubber-stamp marks carry state: PASSED is green ink, VOID is #C23B4E, PAPER is grey, LIVE is amber. One grotesque family (Barlow, with Barlow Condensed for board figures) carries everything. Labels use no monospace.

STORY: The visitor sees their money first, then the slips working for them. They dispatch an agent and watch it print hypothesis slips that get stamped PASSED or VOID. They read a slip's homework (thesis, in-sample, out-of-sample, number of tries), drag the what-if dials, and post it to the board as PAPER or LIVE. Then they talk to the agent beside the board.

FIRST VIEWPORT: The Dashboard. Full-width tote board in green: the account balance in large amber condensed figures, with Today P&L, ROI and open positions as smaller board cells. The PAPER/LIVE service plate sits at the board's right edge. Below it is a row of deployed slips at registered scale, each with a sparkline on one shared axis. The primary action, "Dispatch an agent", is a slip-shaped button at the board's lower edge. On a phone the board shows the balance plus one cell, slips stack, and a bottom tab bar holds the five sections.

FORM: The Tote Slip, my ordered list position 5, seed key 1b367926. Raises: one dominant field per screen (from Zoo Map), registered scale (Botanical Folio), one control redraws the sheet for what-if (Type Specimen), one grotesque family (Design Annual). Signature interaction: research slips feed out of the board slot as the agent proposes them, then the backtest stamps them PASSED or VOID in place.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
