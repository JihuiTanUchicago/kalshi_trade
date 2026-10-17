# Teammate deployment handoff

Workstream: tau-broker-oauth-teammate-handoff-20261017; 2026-10-17T23:24:33+08:00, Asia/Shanghai.
Status: source published for review / operator handoff complete; advisory reservation handed off.

User chose that their teammate will deploy. No further request for this desktop's AWS/SSH access is needed. Scope: publish the reviewed existing OAuth source/tests and selected small evidence on a review branch/PR; add an operator-facing canonical runbook, exact migration/verification commands and secure credential-transfer guidance; synchronize trackers. No direct teammate messaging authorized.

Owned: app/BROKER_OAUTH_DEPLOYMENT.md, narrow broker/deployment/README/tracker updates; branch/commit/PR publication of previously implemented local feature and selected evidence. No-touch: private env bytes, existing GitHub secret values, production/DB/service state, live/data flags, sibling source, prior evidence facts and unrelated worktrees. Source publication does not deploy or merge main.

At workstream start, main a5d5528 matched GitHub main and no open PR existed. Seven GitHub Secret names include the two OAuth values, but a teammate cannot download the values through the UI/API. Manual SSH needs original credentials through an approved private channel or direct provider account access; a trusted deployment workflow can reference existing GitHub Secrets. Do not publish plaintext secrets/artifacts.

## Publication and verification — 2026-10-17T23:29:41+08:00

[PR #10](https://github.com/JihuiTanUchicago/kalshi_trade/pull/10) is open against
main from codex/broker-oauth-20261017. Initial source commit `473d6249f5dfd0f6e464d9ffaaf9467513a6fd99`
and tree `9c5ee5b650360da41aa141b3bf1c3733f6674bed` were reproduced exactly through
Git Data API; the branch head was read back. Fifty-one allowlisted source/test/
small-evidence/synthetic-screenshot files were published. Private envs, key
material, local bundles and access/baseline/source-manifest files were excluded.
New broker links resolve inside the selected commit. PR attached to the chat.
No main merge or server/database/activation operation occurred.

Full checks immediately before feature commit: **1,020 Python passed / 9 skipped
in 8.28s; 55 frontend passed**. No runtime change followed. Independent read-only
handoff review found no blocker after safe SQL/receipt links were explicitly
selected for publication. Bash snippets pass syntax checks and the embedded
Python passes AST parsing (not executed against a DB). The initial archive
command failed because git applied the package-directory prefix; the corrected
`git -C .. archive ... HEAD:kalshi_trade_infra app` command was exercised
successfully before publication. This failure and correction are retained here.

Canonical operator guide: [BROKER_OAUTH_DEPLOYMENT.md](../../../app/BROKER_OAUTH_DEPLOYMENT.md).
It includes a source checkout/whole-app build, manual private credential delivery
or existing workflow injection, preserved APP_SECRET_KEY/configuration, scoped
DDL, web-only restart, Tau cache invalidation, public status checks, rollback
and genuine user paper consent. GitHub Secrets do not let a collaborator download
values; a manual deployment requires the original pair through the team's
private vault/provider access. No workflow was added or teammate message sent.

The user has explicitly assigned execution to their teammate. Desktop AWS/SSH
access is no longer requested. Production compatibility, migration/configuration,
installation and actual account/consent acceptance remain teammate-owned.
Final exact GitHub head/publication receipt is local-only PUBLICATION_RECEIPT.json
to avoid a self-referential commit hash. Prior baseline/preservation receipts
remain local; source/test/evidence commits are reviewable on GitHub.
