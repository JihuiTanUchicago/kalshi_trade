# Initial disabled-feature release review

October 23, 2026 / Asia/Shanghai. **Plan only; no production request, schema run,
service/job/configuration change or deployment was performed by this review.**
Root owns approval, installed-state evidence and dispatch. This file does not
authorize activation, an agent/engine/history restart or an unreviewed release.

Recommendation: **hold for fresh installed-state evidence**. A narrowly guarded
web-only release can preserve running binary research under the conditions below.
Do not run the standard deployment script while interruption is prohibited.

## Source and available evidence

- Reviewed immutable range: `aa3664e420fe4fdf538cd434e4c91e73ee0875cf` →
  `b7cf7c754e09a50e8f0bc6278dbf275f0f0f2a8b`; exact `git diff --binary` SHA256
  `f1f6ee4e079ae8186557071d89bddd0b323169112f3cfa3695fa1cc47be1c11c`.
- Root's `publication/PUBLICATION.json` records source, staging merge `b2f93c1f`
  and main merge `33bfc957` sharing tree `fde9305a181f24815d8099ea3671f3db0a93ee79`;
  CI `39883215379` and isolated MySQL/HTTP staging `39883215499` succeeded.
  Staging used a disposable database and synthetic broker; it does not prove
  production lock behavior, running-worker compatibility or perps replay readiness.
- `app/worker.py`, `app/sandbox.py`, `app/research_brief.md`, all `data_pipeline/`,
  requirements and source systemd units are unchanged in this Git range.
- The locally available header-operations method at `094382a` clones installed
  packages, preserves ownership/modes, fences complete source/control snapshots,
  runs bounded schema and exchanges the whole app atomically. Its CSS-only
  assumptions do not establish safety for this backend release. Root reports a
  later `b6ec2bf6` operations revision; review the final operation before dispatch.

## Running binary workers: what source establishes

`app.worker` eagerly imports `agent` and `engine`. `agent` eagerly imports
`backtest`, `gatekeeper`, `partitions`, `research_repository`, `spec` and `markets`.
These cover the changed binary-research modules. Existing Python functions and
their module globals remain resident when source directories are exchanged;
replacing files does not upgrade those workers.

Later loads remain material: sandbox, broker/Alpaca, reconciliation and execution
modules can be imported during a run, and `agent._brief()` reads
`research_brief.md` from disk. These paths are unchanged in the reviewed range.
Sandbox subprocesses execute the unchanged inline `_RUNNER` with scratch files,
not a new `-m app.backtest` or worker process. The history process eagerly imports
its market registry; it can continue its existing binary loop without restart.

This is a compatibility argument, **not evidence of actual worker-loaded bytes**.
Python package paths still resolve through the shared installed directory after
an atomic exchange. Require release/startup receipts tying each active worker's
PID/start ticks to its prior compatible package, plus fresh installed hashes.
Unchanged PIDs or hashes of today's files alone cannot prove what was loaded.
Any unreviewed worker entrypoint, source drift or changed later-loaded file stops
the active-job release. Paused and run-forever research also count as active.

## Minimal candidate and release conditions

1. Obtain fresh read-only full inventories of installed `app/` and
   `data_pipeline/`, effective feature flags, unit/drop-in/resource settings,
   PID/start ticks and research counts/status/heartbeat metadata. Reconcile them
   with prior accepted receipts. Require perps effectively disabled in the new
   web startup context and no existing perps work needing upgraded workers.
   Do not print private environments, account data or raw logs. Public native
   feed availability is an activation gate, not a prerequisite for a disabled release.
2. Archive both complete installed packages privately, preserving metadata.
   Build a complete candidate by cloning that installed snapshot. Overlay only
   the reviewed feature delta. For each modified existing file, either prove its
   installed bytes equal the reviewed base or review and test the feature delta
   applied to its installed variant. New paths must be absent or exactly approved.
   Reject unexplained collisions; never substitute Git's whole app for installed
   drift. Preserve all non-target bytes, especially default/Meridian CSS,
   bootstrap, raw index, manual styles, unrelated assets and every data-pipeline
   file. Both JS bundles change intentionally: preserve any installed extras in
   their reviewed candidates. Exclude stale bytecode from executable candidates.
3. Validate the resulting complete package, including imports, both JS bundles,
   API/static versions and the preserved bootstrap. Its runtime manifest must
   match the reviewed candidate exactly. A candidate containing reconciled
   installed drift needs its own validation; source CI is not that proof.
4. Run **full candidate** `app.schema.main()` before exchange. Its interpreter,
   working directory and module path must resolve the candidate package and its
   unchanged captured data pipeline. Copying header-operations `cwd=ROOT`
   unchanged would run the old installed schema and omit new perps tables.
   Keep existing configuration private and unchanged; do not run only the new
   table DDL or `data_pipeline.init_schema`.
5. Recheck the source/control snapshot immediately before exchange. Exchange the
   complete `app/` on the same filesystem; keep data-pipeline bytes unchanged.
   Only `recursive-web` may restart, with its existing unit/resources/configuration.
   Keep agent, engine, history and house trading processes untouched. A brief
   web request interruption is possible; do not describe this as zero-downtime
   HTTP service. Do not mutate research states, install a collector or enable perps.
6. Require origin and canonical public page/health checks, both changed JS hashes,
   unchanged CSS/bootstrap/index-related behavior, correct rendered build versions
   and CloudFront invalidation. Compare non-web PID/start ticks, unit/configuration
   fingerprints and source manifests again. Existing research must continue with
   healthy heartbeats and no deployment-induced failure/requeue. Natural task
   completion may change counts, so compare progress rather than count equality.

## Schema locks and recovery

Full schema is not merely two additive tables. Existing code unconditionally
modifies `market VARCHAR(48)` in `app_experiments`, `app_fdr_state`,
`app_holdout_ledger` and `app_data_partitions`; it also performs waitlist cleanup,
missing-username assignment and a BTC-to-spot `INSERT IGNORE ... SELECT`.
Inspect installed schema convergence and relevant lock/transaction pressure.
The header operation's 3-second session metadata/InnoDB lock waits, 60-second I/O
and 120-second process bounds are useful ceilings, not proof of non-interference.
A queued DDL metadata lock can briefly block research even when it later times out.
If strict uninterrupted research cannot tolerate that risk, defer full schema
until an agreed quiet/drained window; do not silently weaken its required scope.

DDL may commit before a later failure. Timeout/disconnect does not certify that
every server statement stopped or rolled back. On failure retain receipts and
inspect database state; do not retry blindly, drop tables or claim zero DB change.
Retain the old whole package until acceptance and recovery retention are complete.
Rollback requires a fresh exact-state check and a reviewed app exchange plus
web-only restart. Never use the standard script's all-worker rollback. New empty
perps tables may remain after a source rollback; source rollback is not schema rollback.
Post-exchange drift requires inspection with both package versions retained.

The standard script extracts over shared paths in place, restarts web/agents/
engine/history and deletes its backup before public acceptance. Overriding its
`SERVICES` variable fixes only one of those properties. If worker provenance,
installed drift, candidate/schema identity or resource/lock safety cannot be
established, **wait**. Upgrade workers later at a separately controlled idle
boundary; perps activation still needs its own data, database, replay and queued
research acceptance.
