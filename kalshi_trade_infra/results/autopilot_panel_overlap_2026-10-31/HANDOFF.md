# Autopilot panel overlap — October 31, 2026, Asia/Shanghai

Status: in progress. Workstream: tau-autopilot-panel-overlap-20261031. Isolated checkout from current main 8c15996c; the older shared checkout and its existing changes remain untouched.

Owned paths: the two theme stylesheets, a synthetic browser regression, PLAN.md, root mvp.md, and this evidence directory. No-touch: trading, billing, account state, API/control handlers, providers, services, deployment, and other worktrees. No commit or production action is part of this repair.

Diagnosis: the desktop feed uses its full content height as its flex basis. A long conversation therefore consumes the panel and collapses the independently scrolling controls area. Check a zero feed basis while preserving mobile whole-sheet scrolling.

Project AGENTS references historical /impeccable and /devlog-sync workflows, which are not installed in available skill/command locations. Existing .impeccable design/surface notes are available; use their current theme and interaction constraints for this bounded layout correction. Public shipped entries remain unchanged until a release actually ships.

Acceptance: render actual application assets with synthetic responses only; demonstrate the long-feed failure before the patch, controls/composer accessibility after it, independent desktop feed scrolling, and preserved phone sheet behavior. Record desktop, short-height, narrow, and both-theme results.

## Result

Implemented and locally verified; release pending. In both theme stylesheets, desktop `.apf.open .apf-session` now uses an explicit zero flex basis (`flex: 1 1 0`). Feed content no longer determines the panel’s height allocation. The actual controls viewport stayed 408.609375px before and after adding long history, versus 62.78125px with the original CSS at 1280×900. The existing control scrollport and phone whole-sheet scroll rules remain intact. No JavaScript/control handler or trading behavior changed.

Added `tests/browser/autopilot_panel_layout.mjs`: actual app builders and styles, intercepted synthetic GET responses, and forbidden writes. It covers both themes at 1280×900, 1024×768, 1280×600, 760×600, and 390×844, with empty versus long history and expanded preferences. Assertions cover stable control height, lower-selector focus/hit testing, independent desktop feed scrolling, composer/viewport containment, and mobile single-sheet history access.

## Verification

- Ten browser cases pass with zero page errors: `after/LAYOUT_REPORT.json`. The before report/screenshot reproduces the reported collapse. The early baseline harness also sampled smooth scrolling too early; the final harness waits for scrolling to settle.
- Full existing frontend suite: 2,130 passed, two skipped, zero failures (`frontend-tests.log`).
- Public changelog checks: 29 passed (`devlog-tests.log`). The queue and public planned entry reflect local verification; no shipped claim was added. The unavailable historical devlog-sync command was replaced with a narrow manual planned-entry synchronization.
- Independent read-only review found no actionable issue. Coverage is Chromium with synthetic paper/credits-paused fixtures, not Safari, actual accounts, or every live-confirmation combination. No actual broker/account/provider operation occurred.
- Diff whitespace check passes. No commit or deployment was performed. Existing dirty shared-checkout files were not edited.

Reproduce from `kalshi_trade_infra/` with Node and Playwright available:

```bash
TAU_PLAYWRIGHT_MODULE=/path/to/playwright TAU_LAYOUT_OUTPUT=results/autopilot_panel_overlap_2026-10-31/recheck node tests/browser/autopilot_panel_layout.mjs
node --test tests/test_*.mjs
python -m pytest tests/test_devlog.py -q
git diff --check
```

This run used the bundled Node/Playwright under `/Users/jonathanzhang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/` and the existing infra venv only as the Python test runner. All tested source came from the isolated checkout.

## Handoff

Worktree: `/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-autopilot-panel-overlap-20261031`. Branch: `codex/fix-autopilot-panel-overlap-20261031`. Code is ready for review/publication and normal release; the live site has not changed. Advisory ownership released. Remaining gate: publish and deploy through the project’s normal release workflow when authorized.

## Release authorization — October 31, 2026, Asia/Shanghai

The user explicitly requested release and deployment. This supersedes the earlier local-only scope for this fix. Publication/merge and the existing guarded release workflow are authorized; financial settings and unrelated changes remain out of scope. Workstream is active through live verification.

Moved the explicitly run browser harness into tests/browser/ so the standard CI tests/*.mjs command does not require an uninstalled browser dependency. Its actual-asset regression remains independently runnable. Main is unchanged at the validated base. Re-run the actual CI frontend command and the repository-required full offline Python suite before committing.

Release preparation: the browser regression now lives under tests/browser/ and is intentionally run separately from CI’s root tests/*.mjs glob. The exact CI frontend glob passes 2,189 tests with two skips; all ten moved-browser cases pass. The full offline Python run completed with 4,820 passed, 184 skipped, and one failure in test_catalog_markets.py::test_generated_market_builds_backtest_and_settles. That exact failure was reproduced against untouched main 8c15996c in a separate temporary worktree; no trading/test logic was changed to suppress it. GitHub main CI is green at the base, and the new PR’s GitHub CI must pass before merge. Local full-suite failure remains recorded rather than being described as a pass.

The public changelog entry has been prepared for this release artifact. It will become visible with the fix when that artifact is deployed; this is not yet a live-deployment claim. Full local logs are retained in this evidence directory but are not all included in the publication; the verification receipt summarizes them.
