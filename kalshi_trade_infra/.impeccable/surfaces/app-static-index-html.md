---
version: 1
slug: "app-static-index-html"
primary_target: "app/static/index.html"
related_targets: ["app/static/app.css","app/static/app.js","app/static/session-data.js","app/static/session-chat.js","app/static/research-artifacts.js"]
---

# Tau customer app

Scope: the whole customer web app (`app/static/`): sign-in, Dashboard, Research
(idea form/history, session conversation and strategy artifacts), Position (deployment
board, open positions and agent chat), Explore/Hot Markets, Community and Settings
(Account funding/Kalshi connection, Billing and public System), plus Dev Logs.
Visitor mode: **Operate**. Desktop and phone are both first-class.

Audience: retail traders, non-quants, who judge strategies by money. Job: dispatch research,
deploy what passed, watch it trade, steer it with the agent. Constraints: vanilla HTML/CSS/JS,
no build step; paper and live money must never be confused.

## Direction contract

October16 Overview: use the shared page title without the subtitle or bottom rule.
Keep New research and the existing body/Hot Markets. Live P&L/history warnings remain
with account details; deployment rows retain status. Verification (local archive: `../../results/overview_heading_cleanup_2026-10-16/HANDOFF.md`).

October16 current refinement: reuse Position's compact Hot Markets heading on all
pages, including Dashboard. Remove Overview-height stretching and its extra
measurements. Both toggles remain removed. Panel width, navigation, data and phone
flow remain. This supersedes the previous divider alignment request and historical
toggle guidance below. Verification (local archive: `../../results/hot_markets_compact_heading_2026-10-16/HANDOFF.md`).

October 15 current placement: one full-width black header sits above a shared row
of Hot Markets and page content. Their top edges meet the header's lower edge and
the panel uses matching neutral rules. At narrow widths the quote panel stacks
between header and page. Retain the chevron-only control, reserved width, chart
fitting, quotes, persistence and page actions. This supersedes earlier placement
beside the header. Handoff (local archive: `../../results/hot_markets_header_2026-10-15/HANDOFF.md`).

October 15 toggle refinement: replace the black-header Hot markets label/trend
icon with double chevrons pointing right when closed and left when open. Remove
RIGHT NOW and its decorative dot; retain the quote-panel title. Keep accessible
action/state labels, a matching native tooltip, desktop/coarse targets and all
dock/phone behavior. Handoff (local archive: `../../results/hot_markets_toggle_2026-10-15/HANDOFF.md`).

October 15 Hot Markets dock: put its toggle first on the left of the header and
reserve 248–306px beside the whole app above 600px. At narrower widths the bounded
panel stacks above the app in document flow. Opening/closing adjusts available
space together with panel visibility; chart sizing follows. Preserve quote data,
refresh, saved state, navigation and closing focus. GPT-6.1 Sol approved this
integration at **9.2/10**, independently of broader visual design acceptance.
Verification and handoff (local archive: `../../results/hot_markets_dock_2026-10-15/HANDOFF.md`).

October 15 copy cleanup: remove repetitive page decks, workflow tutorials,
promotional payment copy and explanatory empty-state paragraphs across customer
tabs/detail/settings views. Retain useful labels/states/errors, actual user/agent
content and evidence, costs, risk/consent, provenance and saved/scenario meaning.
GPT-6.1 Sol reviewed each revision and approved the final copy at **9.2/10**.
This satisfies the copy gate, independently of overall visual design acceptance.
Review history and verification (local archive: `../../results/frontend_copy_cleanup_2026-10-15/HANDOFF.md`).

October 15 Dashboard layout: paper portfolio/open positions lead, followed by
paper performance and recent research; complete deployed and settled data remain
below. Account panels stack at 760px and below. The user retained the current
Hot Markets header trigger and drawer, declining the proposed rolling banner.
Other pages, the shell and all existing data/actions remain unchanged.
Verification and handoff (local archive: `../../results/dashboard_layout_2026-10-15/HANDOFF.md`).

October 15 Settings consolidation: one Settings main-navigation entry with
horizontal Account/Billing/System section links. Keep the native forms, balances,
ledger, payment/card/auto-reload controls and complete system graph. Remove repeated
page introductions and headings; collapse Kalshi setup help and restricted operator
tools. Keep financial meaning, errors, access guards and legacy deep links. Operator
mode is a distinct visibility control, not another navigation entry. Canonical
handoff (local archive: `../../results/settings_integration_2026-10-15/HANDOFF.md`).

October 15 current presentation: selected Meridian/Catalyst design is integrated
into local main with tighter whitespace. Charcoal navigation, neutral light
surfaces, local DM Sans and Georgia research titles replace the previous warm
stock/Archivo customer-app theme. Overview pairs actual recent sessions with paper
portfolio and deployment data. Compact evidence/conversation panes preserve all
controls, data, state and guards. The operator console and historical design
receipts are unaffected. Current evidence (local archive: `../../results/meridian_main_integration_2026-10-15/ITERATIONS.json`).


Approved October 15 copy/control cleanup: apply C1–C11/B1–B2 without removing
strategy information or distinct actions. Show one session state/count, compact
message-group targets, accessible hidden composer labels and retained direction.
Position uses compact cards with saved stakes and a single platform notice;
strategy-specific gates and the two requested deployment entrypoints remain.
Label fixture replies Sample conversation; show one current demo revision with
its history in messages. Cleanup handoff (local archive: `../../results/research_ui_cleanup_2026-10-15/HANDOFF.md`).


Current direction (October 15, 2026, started October 14): restoration completed
before the user requested Research conversations with strategy artifacts. Chat,
source activity and all-status strategy links occupy the left panel; opened
strategies become closable tabs over full evidence on the right. Preserve saved
backtests versus scenarios, artifact identity and keyboard/focus behavior. Mobile
uses Conversation/Strategies panes and returns to conversation on last-tab close.

Full Tau has Strategy between Research and Explore, using the existing
URLs/library filters. Strategy selections still open Research artifacts.
Position exposes eligible strategies through the
same paper/live deployment controls; preserve all other account/financial gates,
existing Position chat/autopilot and Billing/Community/Admin/System features.
Session chat uses the [scoped contract](../../app/SESSION_CHAT_API.md); backend
endpoints remain unimplemented and disconnected drafts stay available. Canonical
workspace handoff (local archive: `../../results/research_artifact_workspace_2026-10-14/HANDOFF.md`).

Earlier restoration (local archive: `../../results/separate_research_strategies_2026-10-14/HANDOFF.md`),
session layout (local archive: `../../results/session_chat_ui_2026-10-14/HANDOFF.md`) and
cleanup (local archive: `../../results/frontend_cleanup_2026-10-14/HANDOFF.md`) are preserved history.
The current workspace direction above supersedes their active presentation rules.

The original Tote Slip contract below is historical. It predates the upstream
Tau rebrand; current assets and the workspace decision above take precedence.

THESIS: Every strategy is a printed slip: numbered, staked and stamped, hanging under a live tote board. We refuse the dark neon trading terminal and the white brokerage card grid.

OWN-WORLD: Tote green (#0F3A2C) owns the top band of every screen as one committed field, with amber (#FFB31A) figures on it. Slips are cool thermal white (#F6F7F4) with perforated top edges, ink #23262B, and numbered serials. Rubber-stamp marks carry state: PASSED is green ink, VOID is #C23B4E, PAPER is grey, LIVE is amber. One grotesque family (Barlow, with Barlow Condensed for board figures) carries everything. Labels use no monospace.

STORY: The visitor sees their money first, then the slips working for them. They dispatch an agent and watch it print hypothesis slips that get stamped PASSED or VOID. They read a slip's homework (thesis, in-sample, out-of-sample, number of tries), drag the what-if dials, and post it to the board as PAPER or LIVE. Then they talk to the agent beside the board.

FIRST VIEWPORT: The Dashboard. Full-width tote board in green: the account balance in large amber condensed figures, with Today P&L, ROI and open positions as smaller board cells. The PAPER/LIVE service plate sits at the board's right edge. Below it is a row of deployed slips at registered scale, each with a sparkline on one shared axis. The primary action, "Dispatch an agent", is a slip-shaped button at the board's lower edge. On a phone the board shows the balance plus one cell, slips stack, and a bottom tab bar holds the five sections.

FORM: The Tote Slip, my ordered list position 5, seed key 1b367926. Raises: one dominant field per screen (from Zoo Map), registered scale (Botanical Folio), one control redraws the sheet for what-if (Type Specimen), one grotesque family (Design Annual). Signature interaction: research slips feed out of the board slot as the agent proposes them, then the backtest stamps them PASSED or VOID in place.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
