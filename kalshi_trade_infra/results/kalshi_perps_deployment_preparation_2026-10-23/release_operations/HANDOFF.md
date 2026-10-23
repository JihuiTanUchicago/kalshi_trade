# Guarded manual Bitcoin perpetual release operation

Workstream: bitcoin_perps_data / October 23, 2026, Asia/Shanghai.
Status: implemented and offline verified; handed off for immutable operations review.
No commit, push, workflow dispatch, production/schema/service change, provider call,
or account/order call was performed by this workstream.

Ownership is this `release_operations` directory and this operations branch's
`.github/workflows/deploy.yml`. The frozen release checkout, runtime sources,
private configuration, installed services, shared PLAN/mvp and release publication
remain root-owned. Development-progress is applied through this scoped handoff.

## Exact source and acceptance pins

The archive contains the complete `app/` and `data_pipeline/` packages from candidate
`0bfb7482ae15d542868556d8a038dd5cfa28f64b`, never the operations checkout. Its Git tree
is `6f75cf6d58d363c4a7e8e69e6546a0dd9df9c1f9`. Local Git objects independently prove
that candidate and merged main `e372a6e54faa2b71e3e00b24e97eb6b1ff252175` have this
same tree. Root's GitHub git-commits API verification proves the hosted synthetic
merge `744bf900006923984abc8f81c6b6745e66d35e5b` has the same tree and parents main33
and candidate0bfb. The runner verifies the candidate tree and refuses apply when
the checkout's `origin/main` differs from the pinned merged main. Root must still
freshly verify actual GitHub main and the exact operations head before dispatch.

Root confirmed exact candidate CI `39892409518`, hosted staging `39892409572`
(19 native synthetic-broker checks plus 14 paper checks), and both immutable
runtime security reviews clean. Merged-main CI `39893020446` and hosted staging
`39893020498` also passed. `candidate_ready=true` means those runtime gates passed;
it does not authorize operations publication or dispatch. Candidate58 remains
explicitly rejected: its earlier hosted test found proposal-kind width 12 could
not hold the new 17-character kind. Full schema must verify width at least 32.

Installed source/control pins reconstruct capture `39888106069` against readiness
`39884723368`; their receipt hashes and reconstruction proof are in `pins.json`.
The original combined expected installed fingerprint was
`4a96e23734af4890bc8acf5f06e21b599d1b7189eb9945591f5be6531f4e8015`.
After explicit review of inventory39896649873 and capture39896944153, the current
expected fingerprint is
`e664c1fc4851566e21516be5285fe84ad8417c070f5bbe572cd6679327872b99`.
Only the agents worker PID/start and opaque environment/property hashes changed;
all source/configuration files, commands, visible settings, resources and other
services matched. Historical environment equality is not inferred from hashes.
Fresh complete actual environments must still match before/after apply; no
preservation, idle or trading guard is relaxed. See BASELINE_REFRESH_REVIEW.json.
The inventory now emits the already-sanitized unit/process projection for future
drift review. Whole-state fingerprints include a mutable omitted-cache counter;
the reviewed source/control comparison excludes only that diagnostic count.
All 120 installed source paths are pinned with hashes and metadata. The 128-file
candidate retains these three extra installed diagnostic paths:

- `data_pipeline/research_expiry_resolution.py`
- `data_pipeline/research_expiry_resolution_sensitivity.py`
- `data_pipeline/research_fee_sensitivity.py`

Every shared data-pipeline file matches installed bytes. Installed source hashes
do not prove which bytes an already-running worker loaded. No fresh source,
unit, process, resource or protected-configuration drift is automatically repinned.

## Guarded sequence

1. Inventory only if any kind of run is queued, running or paused, any source or
   control pin conflicts, the two service vault keys differ, or the new flag paths
   already exist. Aggregate counts contain no user, prompt, account or order data.
2. Require at least 30 seconds of quiescence and a fresh matching inventory. Make
   a root-private whole-package backup, stage complete candidate packages plus the
   three installed extras, preserve existing ownership/modes, verify full source
   hashes, and prove atomic directory exchange works before stopping services.
3. Compile the full staged packages and validate imports with networking blocked.
   Run the complete candidate `app.schema` from the candidate CWD with verified
   import origins, filtered environment, bounded lock waits/read timeouts, and
   class/numeric-code-only diagnostics. Verify all four native tables and proposal
   kind width at least 32. Additive DDL may already have committed at this point.
4. Open a dedicated bounded connection and acquire
   `LOCK TABLES app_agent_runs WRITE, app_kalshi_perps_settings WRITE,
   app_kalshi_perps_orders WRITE`. Re-read all-kind counts under the lock; require
   zero active runs and both native policy/order tables entirely empty. Missing
   privilege, a lost session or a late proof is an inspection gate, never a grant,
   reconnect or lockless fallback. No DDL/transaction runs on the locked session.
5. While holding the admission barrier, stop only idle `recursive-web` and
   `recursive-agents`, exchange the complete packages, publish the new fixed
   root-owned 0600 environment/drop-ins, and start those two services. Existing
   engine/history processes, unit resources and private config remain pinned.
6. Prove actual target process flags, full source hashes, preserved resource and
   environment values, local HTML/asset hashes and unauthenticated native HTTP401,
   and canonical public HTML/assets while locked. Only then release admission.
   No acceptance HTTP check reads the locked tables or calls a provider.
7. Independently invalidate CloudFront `/*` and verify public HTTP200 plus asset
   hashes after success. A failure after unlock is partial acceptance requiring
   inspection; the runner never restarts or rolls back once new work can exist.

The only new environment contents are
`TAU_KALSHI_PERPS_LIVE_ENABLED=1` and
`TAU_KALSHI_PERPS_LIVE_ENVIRONMENT=production`, for web/agents only. APP_SECRET_KEY,
old binary flags and the research-data enable flag are preserved. Each user's
manual native policy stays off by default. This is capability activation, not
provider/order acceptance or a research-history/replay acceptance claim.

## Recovery and timing

The hard admission ceiling is 120 seconds. Forward work has at most 30 seconds;
its cutoff is also bounded by the actual lock deadline less the 74-second
recovery budget and five seconds for the largest in-flight forward HTTP/proof.
Thus `30 + 5 + 74 = 109 <= 120`, and post-LOCK inventory time reduces the forward
allowance instead of spending recovery reserve.

| Recovery component | Maximum budget in seconds |
| --- | ---: |
| Up to 28 SQL ownership proofs (0.5-second write + 0.5-second read each) | 28 |
| Stop and inactive/process checks | 10 |
| Original non-target control checks | 3 |
| Daemon reload | 3 |
| Start and startup health | 11 |
| Complete control/source snapshot | 6 |
| Final local health | 2 |
| Unlock | 1 |
| Local file/exchange reserve | 10 |
| Total | 74 |

Local filesystem calls use the stated reserve; a stalled filesystem is not a
tested latency guarantee. Every recovery mutation, start and final health has
fresh ownership/deadline checks, including checks after bounded operations and
after the proof query itself. Partial new flag files use a journal of owned
device/inode identities, atomic no-overwrite publication and owned cleanup. A
replacement inode or foreign hard link is preserved and stops automatic recovery.
Failed controls, ownership or deadline proofs retain the backup and require
inspection. Source rollback does not undo committed additive schema changes.

SSM preparation execution/poll ceilings are 480/540 seconds; apply 420/480 seconds;
inventory 180/240 seconds. Each CDN wait is at most 180 seconds. The workflow is
bounded to 30 minutes. These transport ceilings do not extend admission or forward
work and avoid the previous 180-second apply ceiling killing bounded recovery.

MySQL's existing LOCK TABLES/SELECT privileges are required; table locks release
on connection loss, and DDL/transaction statements can release them. See the
[MySQL lock contract](https://dev.mysql.com/doc/refman/8.4/en/lock-tables.html).
The fixed EnvironmentFile/drop-in loading follows
[systemd's documented contract](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#EnvironmentFile=).

## Verification and remaining gates

Initial focused verification: **38 offline unittest cases passed**. Cases cover
all-kind busy/conflict inventory, arrivals during quiescence, full-schema ordering
and width, locked BUSY races, native existing-state rejection, partial swaps,
rollback, deadline-crossing proofs, reserve exhaustion before stop, ownership loss
after seven recovery boundaries, real partial write/fsync/chown/chmod/link/unlink
faults, foreign flag replacement, source/main pin drift, quiet sanitized receipts,
public failure after unlock, cleanup failure and absence of provider/order paths.
Root separately reported the unchanged existing app suite: 1899 passed, 10 skipped.
No production lock privilege, filesystem latency, service activation or actual
provider/account/order acceptance was tested by this workstream.

Reproduce from this operations worktree using the project Python:

```text
python -B -m unittest discover -s kalshi_trade_infra/results/kalshi_perps_deployment_preparation_2026-10-23/release_operations -p 'test_*.py' -q
git diff --check
```

`VERIFICATION.json` binds the final focused result and per-file SHA256 values.
The collector retains only deliberate sanitized JSON markers. Raw SSM/Actions
stdout/stderr stays transient in memory. The uploaded bundle contains public
candidate source only and is encrypted; cleanup verifies the current S3 object is
empty. Historical object versions are explicitly not claimed deleted.

Next owner: root verifies this exact operations range, completes its immutable
security review, publishes the operations-only branch, rechecks main/source pins,
and authorizes any one dispatch. Inventory may safely return waiting while the
remaining research runs. Apply remains blocked until all counts are zero and all
fresh pins, schema, privilege, admission and health gates pass. No standard
unconditional deploy script is called.

Root follow-up: original operations review dff976ef-82c2-4191-bf78-ecbb4e0d12e6
completed all10changed files with no findings. Its inventory39896649873 waited on
the worker-state mismatch, with zero active jobs and no application/schema/service
mutation; cleanup passed. Existing read-only capture39896944153 confirmed the
four-field agents-only difference and cleaned its encrypted temporary output.
The explicit baseline/projection delta requires fresh focused/full-suite checks,
an immutable incremental review and an exact-head all-kind inventory before apply.

Root baseline-delta verification:39focused cases passed; existing app1,899passed/10skipped in26.28s; whitespace and owned Python syntax pass. No application, schema, service or real provider/account/order operation has occurred. Incremental immutable review is next.

Restart-diagnosis gate: inventory39898387856 at586d051 again reported zero all-kind jobs and unchanged source/unit-file/private-config pins, but a newer agents process(PID506113). No apply, migration, restart or source installation occurred. Do not repeatedly repin. Added a fixed read-only systemd counter and PID1 service-manager journal projection to inventory; raw messages/errors are discarded and only typed counters/event totals survive.43focused tests and1,899app tests/10skipped in25.79s pass. Read-only health diagnosis requires immutable review before dispatch. Current pins remain at the previously reviewed worker505078; mismatches still block all application changes.
