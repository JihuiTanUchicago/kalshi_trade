---
version: 1
slug: "app-static-index-html"
primary_target: "app/static/index.html"
related_targets: ["app/static/app.css","app/static/app.js","app/static/session-data.js","app/static/session-chat.js","app/static/research-artifacts.js"]
---

# Tau customer app

Scope: the whole customer web app (`app/static/`): sign-in, Dashboard, Research
(idea form/history, session conversation and strategy artifacts), Position (deployment
board, open positions and agent chat), Explore/Hot Markets, Community, Account
(funding and Kalshi connection), Billing and public System.
Visitor mode: **Operate**. Desktop and phone are both first-class.

Audience: retail traders, non-quants, who judge strategies by money. Job: dispatch research,
deploy what passed, watch it trade, steer it with the agent. Constraints: vanilla HTML/CSS/JS,
no build step; paper and live money must never be confused.

## Direction contract

Compact Meridian is the current customer presentation: neutral light surfaces,
charcoal navigation, local DM Sans/Georgia, compact rows/panels and readable data.
Overview uses existing session/account reads and period-based closed P&L; it never
substitutes mocked balances. The Hot Markets header control preserves the drawer.

Research holds conversation/activity/all-status candidates on the left and full
strategy artifacts in closable tabs on the right. Preserve rules/spec, data dates,
trades, saved backtests versus scenarios, gates and deployment decisions. One
session state/count and grouped source targets avoid redundant instructions;
individual source records and timestamps remain. Mobile switches panes, opening
selects evidence and last-tab close returns to conversation. Preserve keyboard
selection, independent tabs/drafts and stale-response protection.

The filtered library and old strategy URLs stay reachable under Research; Position
retains deployment/position controls and account-wide chat/autopilot. Explore,
Community, Billing, Account, System and Admin authorization remain. Scoped session
chat uses [the backend contract](../../app/SESSION_CHAT_API.md); its endpoints
remain unimplemented, with drafts retained and sends/actions disabled on missing
routes. No account-wide chat fallback or financial gate relaxation is introduced.

[Review evidence](../../results/meridian_frontend_pr_2026-10-15/HANDOFF.md).
The visual 9/10 gate remains open; latest independent score is 7/10.
