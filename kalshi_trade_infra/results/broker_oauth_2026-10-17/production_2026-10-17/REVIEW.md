# Deployment review

Read-only independent review by oauth_deploy_review, October 17, 2026.
No actionable source blocker found against a5d5528 + the current OAuth feature.
This was manual review; no named /security-review command or scan engine ran.

Required before install: freshly verify CloudFront origin/web instance, remote
whole-app/source/dependency drift, persistent encryption-key validity/equality,
and exact InnoDB broker table definitions. Execute only the two broker DDLs;
app.schema has unrelated research/waitlist/history mutations. Never invoke the
existing broad secret loader; inject only the OAuth pair/public origin atomically
and preserve APP_SECRET_KEY and all flags. Keep protected app/env rollback copies,
restart only web, invalidate only Tau /*. Anonymous protected broker routes should
return 401, missing CSRF 403, actual assets/health 200; real consent must use the
human's browser session, without forging users/sessions. Roll back app/env on
failure while retaining additive broker tables/data.

Whole-app candidate and two-table SQL packaging fit this approach. Production
compatibility cannot be certified without access. Root subsequently recorded all
requirements in DEPLOYMENT_RUNBOOK.md. No infrastructure mutation/read or secret
access by the reviewer.
