# Production readiness interpretation

October 23, 2026, Asia/Shanghai. **Hold the standard deployment.** The new
read-only preflight succeeds, resolves the server-side public-feed timeout
question, and provides useful installed-state evidence. It does not establish a
safe whole-Git-package replacement or authorize interrupting the running research.
This review changes only this evidence document; no scripts, dispatch, AWS,
provider, database, service, job, receiver or configuration operation occurred.

## Fresh observed state

Canonical receipt: [READINESS_39884723368.json](/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-bitcoin-perps-research-20261023/kalshi_trade_infra/results/kalshi_bitcoin_perps_2026-10-23/publication/READINESS_39884723368.json).
Workflow completed successfully at exact operations head
`0e2e79c30d13bab8dec41081ef4d273d826b127c`; native candidate is exact
`b7cf7c754e09a50e8f0bc6278dbf275f0f0f2a8b`.

- Observation: `2026-10-23T01:34:19.718793+00:00`.
- Installed fingerprint:
  `9b9472457a13a08993dcd7e87fce2115925df674a0db94c74df28344e74db6f5`.
  All 120 inspected source files and stable service/configuration controls were
  unchanged across this operation; diagnostic temporary source was cleaned.
- Actual active-service perps flags are effectively off and not explicitly set.
  Web/agents have no configured explicit perps proxy. The house live-engine
  service is inactive, PID zero; this is not a claim about database live settings.
- Aggregate research state is one running, zero queued, zero paused. This is a
  point-in-time count, not permission to stop/requeue that work.
- Both new perps tables are absent. The four requested market-column signatures
  are already `varchar(48) NOT NULL`, collation `utf8mb4_0900_ai_ci`.
  No migration or full-schema convergence check occurred.
- The actual candidate client/collector on the server completed five anonymous
  production HTTP200 requests directly: 2,761 candles, six funding records,
  four observations. Funding coverage is complete; candle coverage has 120
  missing minutes. No prices were persisted. Provider routing is resolved for
  this check; **do not retry it merely to obtain a clean candle window**.
  Replay, full DB integration and release acceptance remain false.

## Facts supported by accepted receipts

The relevant current header evidence is the **October23 restoration**, rather
than the October22 historical acceptance:

- [RESTORE_20261023_ACCEPTANCE.json](/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-header-alignment-20261022/kalshi_trade_infra/results/header_alignment_2026-10-22/RESTORE_20261023_ACCEPTANCE.json)
  records accepted apply `39877613855` from exact operations `b6ec2bf6…`, with
  candidate source `04c7eabc…`.
- [DEPLOYMENT_39877470521.json](/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-header-alignment-20261022/kalshi_trade_infra/results/header_alignment_2026-10-22/DEPLOYMENT_39877470521.json)
  records its strict final inventory.
- [DEPLOYMENT_39877613855.json](/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-header-alignment-20261022/kalshi_trade_infra/results/header_alignment_2026-10-22/DEPLOYMENT_39877613855.json)
  records the successful whole-package archive/atomic exchange, changing only CSS
  while preserving backend bytes and service/configuration state during apply.
- [RESTORE_20261023_PRE_APPLY_REVIEW.json](/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-header-alignment-20261022/kalshi_trade_infra/results/header_alignment_2026-10-22/RESTORE_20261023_PRE_APPLY_REVIEW.json)
  records the independently observed agent PID change before that apply; its
  cause was not inspected or attributed.

The fresh readiness hashes equal the restoration's accepted/preserved pins:

| File | Current and accepted SHA256 |
| --- | --- |
| app/static/app.css | 24392a8f61da64a9db002e471f4dbf516a09d83f701007f8db0cb5b616b5a2d7 |
| app/static/app.js | 6d290678e2b9b96887f83a7f0fd8a095d95c3df002846c656f58c6febd1742e7 |
| app/static/app.meridian.js | b457ecf5d4720adaf27635712f4e2c7745e72b8ca3c02c4efa8c457423046b77 |
| app/static/app.meridian.css | 1e7978ec34364065b51e61dcdf8a5099085dc8ab5f8da72009166d4596059c0e |
| app/static/boot.js | 69f63b1ea54da1c91897fb10b1a5199cb5d583f26eee1e592f8988d307a3717f |
| app/static/index.html | e0be2fb9c644388399da2a2e50ab06564ec4b8dd45c8106b01aa456b0bf5585f |

Current installed schema is
`6738460234b7e46ff230cb64e287354e2e3e0f46a548f8fb504ef17c476c1084`.
It matches the restoration inventory and the older accepted Meridian inventory
[DEPLOYMENT_39462684515.json](/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-bitcoin-perps-research-20261023/kalshi_trade_infra/results/meridian_workspace_2026-10-21/DEPLOYMENT_39462684515.json).
The schema difference from current Git predates this perps work. Accepted schema
execution is historical evidence of that operation, not proof that running it
again with active research is free of locks or writes.

All six reported protected-config owner/group/mode triples match the restoration
inventory. That older receipt does not expose each config-content hash, so
cross-operation equality of those content hashes is unproven. The old aggregate
controls hash and the new fingerprint use different data/serialization and must
not be compared as equivalent structures.

Web `463708`, engine `463706`, history `463707`, and house live-engine `0` match
the restoration. Agents changed from restoration PID `492984` to current
`497190` (current start ticks `49028718`). **Cause and worker-loaded source
provenance are unproven.** Neither unchanged non-agent PIDs nor today's file
hashes prove which Python modules a resident process imported at startup.

## Recoverable source material and its limits

The accepted restoration retained a private **server-side** whole-package backup:

```text
/opt/tau-frontend-releases/header-alignment-mmm1fv4p/installed-whole-package.tar
/opt/tau-frontend-releases/header-alignment-mmm1fv4p/candidate/app/
```

The reviewed archive builder captures the entire installed `app/` and
`data_pipeline/` with hashes/metadata verified before extraction. After the CSS
exchange, `candidate/app/` holds the prior app. These paths are evidenced by the
accepted receipt and code; **this review did not contact the server to prove
they still exist or that their bytes match every fresh hash**. A future
read-only recovery could verify selected public source members against the new
120-file manifest and provide the actual installed variants for offline review.
Do not restore that backup or treat its entire contents as current without those
hash checks.

Local audit searched `.runtime`/`.runtime/github-export` archive filenames,
immediate `*/kalshi_trade_infra` whole-package working copies, and 165 same-named
product source files including retained before/after snapshots, while excluding
Git internals, virtual environments and node_modules. No complete local copy of
the current installed package was found. The closest whole working copy was
`tau-main-production-20261019/kalshi_trade_infra` with 101/120 matching current
files, 16 differences and three missing files. This is a bounded local search,
not a claim about every external disk, Git object or remote backup.

One current drifted backend **is locally recoverable byte-for-byte**:

```text
app/broker_oauth.py
SHA256 a92b71ddf2e97487d5f6423fdc12e2f872cf11569ac007d4b456e8824550ef26
```

Matching loose copies exist in:

- `/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/kalshi_trade/kalshi_trade_infra/app/broker_oauth.py`
- `/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-workspace-refinement-20261018/kalshi_trade_infra/app/broker_oauth.py`

It also matches the `app/broker_oauth.py` member of retained local
`/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/kalshi_trade/kalshi_trade_infra/results/broker_oauth_2026-10-17/production_2026-10-17/tau-broker-oauth-app.tgz`.
That archive has only 38 current-manifest matches, 30 different current-manifest
members and 52 current paths absent. Its agent, billing, llm, repository, schema
and server bytes **do not** match. The same six current backend hashes were not
found among the 165 loose same-named product sources checked. Thus the archive
can recover this one OAuth source file, not the installed whole backend or a
release candidate. Data-agent mapping to published Git history is separate.

## Minimal next release gates

1. **Reconcile the actual installed variants before constructing a release.**
   Against `aa3664e…` there are 21 drifted installed files. The perps delta
   intersects seven: `app/agent.py`, `app/schema.py`, `app/server.py`, both
   `app/static/app{,.meridian}.js` bundles, `app/README.md`, and `app/devlog.py`.
   Obtain exact matching bytes from verified local/history material or a bounded
   read-only recovery of the accepted server backup/current source. Review the
   perps delta applied to those bytes; a clean textual patch is not sufficient.
   Preserve every unrelated installed variant, including billing, llm,
   repository, OAuth, broker connections, restored CSS/Meridian CSS/raw index,
   and the three extra data-pipeline research scripts. Never overwrite them with
   the whole main/b7 package. Eight other modified feature files do match the
   reviewed base: backtest, engine, gatekeeper, market_history, markets,
   partitions, research_repository and spec. All five new feature paths are
   absent. These facts reduce reconciliation scope; they are not release approval.
2. **Resolve the active-worker boundary.** One research run is active, and the
   current agent's startup source is not tied to a reviewed package manifest.
   Obtain compatible startup/deployment provenance or wait for a controlled idle
   boundary before upgrading workers. Preserve agents/engine/history while
   research is active. Any proposal to exchange shared source while preserving
   resident workers still needs review of later imports/read-from-disk behavior
   against the actual installed variant. Do not infer compatibility from the
   Git-only b7 CI or worker-PID equality.
3. **Validate the reconciled complete candidate and full schema plan.** Existing
   48-character columns do not remove unconditional ALTER metadata-lock risk.
   Perps tables are absent, and required full `app.schema.main()` includes more
   than their additive DDL. Review locks/quiet-window/recovery against the
   reconciled candidate; do not run old installed schema, silently narrow the
   required migration, or use a live research run as a schema test. Full-schema
   isolated staging on b7 does not validate a different reconciled package.
4. **Only after those gates, review a dedicated disabled-feature operation.**
   It needs fresh exact source/control pins, whole-package private recovery,
   candidate-schema identity, atomic package exchange, web-only restart if
   required, unchanged non-web services/configuration/resources, origin and
   canonical asset/version checks, and research progress evidence without row
   identifiers. Standard `deploy_web.sh` remains unsuitable: it replaces the Git
   package, restarts workers, and has an all-worker rollback path. Keep perps off;
   activation still requires contiguous replay/data/database/queued-run acceptance.

No release, source retrieval, provider retry or further dispatch is authorized or
performed by this interpretation. Root owns the release decision and canonical
project tracker/handoff updates; this new evidence document records the bounded
review and is ready for that handoff.
