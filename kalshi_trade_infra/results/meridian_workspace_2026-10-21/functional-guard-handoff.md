# Meridian functional guard restoration

Workstream: meridian_theme_functional_review_20261021, October 21, 2026, Asia/Shanghai. In progress; root assigned exclusive temporary ownership of `app/static/app.meridian.js` and `tests/test_meridian_workspace.mjs`. Evidence is confined to `functional-guard*` files here. Root owns all other source, records, CI and deployment; no external calls or browser work are authorized by this subtask.

Restore the shipped Meridian generation checks for Billing and System while preserving the compact HTML, existing API payloads and business guards. Add visible current System errors and clearing after recovery. Offline regressions must demonstrate delayed initial success/error, a System poll finishing after departure, and Stripe loading/payment callbacks finishing after departure.

Pre-edit SHA-256: `app/static/app.meridian.js` = `05c10ab05aaba58bd2d1899a19f6b51af7607845c47168e04e642e449148cbbc`; `tests/test_meridian_workspace.mjs` = `e903a25f5e0a0db082e116da8253d0af6245d0ce646d2242302727e15796fc74`.

The initial read-only review reproduced stale System and Billing success responses throwing TypeError against absent current-page hosts. Existing 77 Meridian tests and 8 current-behavior tests passed before adding the missing regressions. Bounded comparison against `production-before-app.meridian.js` also found dropped Funds write-continuation and Admin guards, reported to root for scope confirmation. No publication occurred.

The development-progress skill was read. The root agent confirmed `/impeccable` was independently searched across installed roots/plugins and unavailable, with manual review recorded in the root handoff. This subtask changes no backend code and does not use Ponytail. Canonical tracker/roadmap changes remain root-owned.

## Frozen handoff — offline verified

Root authorized restoring all confirmed dropped guards, including Funds and Admin. Implemented only in `app/static/app.meridian.js`:

- `viewFunds` (line2568): restored guards on demo/paper reloads, live/demo key save/removal continuations and error notices, including connection flags. Prevent departed initial errors from escaping into the active route's render handler. Success notices after a subsequent read are also generation gated.
- `viewBilling` (line3400): restored guards on the initial read, topup, auto-reload notices, remove-card follow-up, Stripe loading, setup-intent completion, confirmation and card-added continuations/errors. Prevent departed initial errors from escaping. Payloads, eligibility and the existing Stripe return URL remain unchanged.
- `viewAdmin` (line3525): restored former operator-tool read/grant guards in the compact Admin page, added the same guards to its existing waitlist follow-ups, and suppressed departed initial errors.
- `viewSystem` (line3626): restored initial/poll response generation checks, current error notice host and clearing on recovery, and generation-gated poll registration.

The bounded comparison covered every shipped function containing `S.gen`: poll, render, Settings wrapper, Dashboard, Funds, Billing, operator tools and System. Existing poll/Dashboard guards remain; the former Settings wrapper's stale-error behavior is preserved in each directly routed asynchronous Funds/Billing/Admin page. The former operator-tools guard is represented in Admin. Shipped System's extra comparison belonged to its former operator disclosure; all three System read/error/poll checks are restored. Compact Explore already has additional guards. No other dropped shipped generation check was found. This was a bounded compatibility review, not an exhaustive asynchronous-code audit.

`tests/test_meridian_workspace.mjs` retains the original77 cases and adds22 offline regressions. The harness exposes the real render/Admin functions and substitutes only a synthetic Stripe loader. The initial-response tests exercise navigation through the real router; payment/action tests retain duplicate host IDs on a later synthetic page to catch wrong-page notices as well as unexpected follow-up reads/actions. All provider and payment data is synthetic.

Verification and evidence:

- Before source edits: `node --test --test-name-pattern='System|Billing|Funds departed|Funds demo|Admin' tests/test_meridian_workspace.mjs` — exit1, 22 cases,21 failed/1 passed; `functional-guard-red.tap` records the actual failures.
- After source edits: `node --test tests/test_meridian_workspace.mjs` — exit0,99 passed/0 failed; `functional-guard-green.tap`.
- `TAU_TEST_THEME=meridian node --test tests/test_production_ui_reconciliation.mjs` — exit0,8 passed/0 failed; `functional-guard-current-behavior.tap`.
- `node --check app/static/app.meridian.js` and `git diff --check` — passed.
- Affected-page API endpoint sequences match the immutable compact source. Default `app.js`, `app.css`, `boot.js` and `index.html` still match2223751 byte-for-byte (`git diff --quiet` passed). No source beyond the assigned Meridian JS and test was edited by this subagent.

Frozen SHA-256:

- `app/static/app.meridian.js`: `d898ab44b8125d2bd076bbe19a82c33d921ca02bc7980a23f99377331778a0d8`
- `tests/test_meridian_workspace.mjs`: `2e6d8c53b7c8cda35e1edc75923a5fd7ca230bfe3f5ab61d3ba31204e8a32b55`

Both source/test files are frozen and released to root. Root owns remaining CI/full-suite/security review, canonical records and deployment, including preserving unpublished production default bytes. No browser, production, provider, order, model, Git mutation or publication action was performed in this subtask.
