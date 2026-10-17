# Teammate deployment handoff

Workstream: tau-broker-oauth-teammate-handoff-20261017; 2026-10-17T23:24:33+08:00, Asia/Shanghai.
Status: preparing GitHub source publication and stable deployment runbook.

User chose that their teammate will deploy. No further request for this desktop's AWS/SSH access is needed. Scope: publish the reviewed existing OAuth source/tests and selected small evidence on a review branch/PR; add an operator-facing canonical runbook, exact migration/verification commands and secure credential-transfer guidance; synchronize trackers. No direct teammate messaging authorized.

Owned: app/BROKER_OAUTH_DEPLOYMENT.md, narrow broker/deployment/README/tracker updates; branch/commit/PR publication of previously implemented local feature and selected evidence. No-touch: private env bytes, existing GitHub secret values, production/DB/service state, live/data flags, sibling source, prior evidence facts and unrelated worktrees. Source publication does not deploy or merge main.

Current main a5d5528 matches GitHub main; no openPR exists. Seven GitHub Secret names include the two OAuth values, but a teammate cannot download the values through the UI/API. Manual SSH needs original credentials through an approved private channel or direct provider account access; a trusted deployment workflow can reference existing GitHub Secrets. Do not publish plaintext secrets/artifacts.
