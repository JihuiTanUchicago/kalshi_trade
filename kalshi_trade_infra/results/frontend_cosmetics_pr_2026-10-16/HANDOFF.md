# Frontend cosmetic review

Prepared against current GitHub main `a46e1b8`, after the repository’s clean-history
release. This is a presentation-only follow-up: Settings groups Account, Billing
and System; Dashboard places portfolio/positions before performance and recent
research; Hot Markets reserves a compact left panel below the black header without
visibility toggles; repeated descriptions and the Overview subtitle/divider are
removed. Existing account and deployment states remain visible.

Retain main’s Research/Strategies pages, model picker/submission, Kalshi demo
controls and chart overlay, profile menu, System source browser, and Community
filters/reply protection. The earlier unmerged conversation/artifact workspace is
excluded. Existing fonts/theme and backend business behavior remain. The only
server change is the Settings SPA route allowlist, covered by the route test.
No API/auth/billing/trading handler, model, schema, collector or execution change.
Dashboard additionally reads the existing runs endpoint for recent sessions.

Verification: `node --check app/static/app.js`; `APP_TEST_MYSQL=0
AWS_EC2_METADATA_DISABLED=true python -m pytest tests/ -q` reports177 passed,
7 opt-in MySQL skips. Fifteen read-only synthetic browser assertions at1280px
and six actual static-handler checks pass. See VERIFICATION.json,
BROWSER_CHECKS.json, PYTEST.txt and STATIC_HANDLER_CHECKS.txt. Screenshots use sample
data only and were inspected. One case-sensitive label assertion was corrected;
initial transport/import, merge and isolated-preview diagnostics are retained in
the verification record. Authenticated services and phone viewports were not tested.

The user’s dirty checkout and8090 preview remain separate and unchanged. Scope is
limited to the listed presentation/static-routing/test/docs/evidence files. No
merge, deployment, migration, provider/model or financial operation is authorized
or performed by this review work. Next: human PR review. Local publication status
and the GitHub URL are recorded in the preserved main checkout’s PLAN/handoff.
