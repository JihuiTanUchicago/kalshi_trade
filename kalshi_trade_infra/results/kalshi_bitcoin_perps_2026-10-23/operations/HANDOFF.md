# Bitcoin perpetual readiness operation

Workstream: `tau-kalshi-perps-readiness-operations-20261023`, October 23, 2026,
Asia/Shanghai. Status: **implemented and offline verified; handed to root for
review/publication; not dispatched**. Advisory ownership is handed off.

Owned paths are this operations directory and this operations branch's
`.github/workflows/deploy.yml`. The feature worktree, installed application,
private files, services, jobs, settings, schema, receiver and execution gates are
no-touch. Root owns shared PLAN/mvp/roadmap records, publication and dispatch.

The operation inspects installed source hashes, unit/resource/configuration
metadata, actual active-service perps flags and aggregate research counts through a
bounded read-only DB session. It runs the exact b7cf7c754e09a50e8f0bc6278dbf275f0f0f2a8b
anonymous public client and collector once for a 48-hour production window in a
temporary directory with the server interpreter and actual worker proxy setting.
It must not install, migrate, restart, reload, write settings/jobs/environments,
activate perps, read private provider keys, or call accounts/orders/models.

Only deliberate sanitized JSON receipts are retained. Temporary diagnostic source
is cleaned on normal unwind. The readiness workflow has its own concurrency group
and no apply path. An enabled or invalid perps flag in any active inspected service
fails before DB/feed checks. The required web and agents processes are also
checked for exact interpreter, module command and installed working directory.

Development-progress skill applied; named project ponytail/security-review skills
were searched and unavailable. Manual control review and focused offline tests
are recorded below. Production and replay acceptance remain separate gates.

## Boundary and receipt

The workflow replaces `deploy.yml` only on this operations branch. **Never merge
this operations branch into main.** It checks out its own exact dispatch SHA and
has no inputs, install, migration, release, restart, reload, environment-write,
receiver, CDN or apply path. It does not require main to remain at the old base;
main has independently merged PR21 as `33bfc957cd8443924f65776e5a744835caa5eaea`.

The candidate and baseline source references are fixed in code. `pins.json`
contains SHA256 for the four exact candidate native modules. The runner reads
both references with Git, verifies the fixed candidate files, and stages only
those public source files plus the two reviewed diagnostic helpers and source
hash maps in the existing encrypted `bundle/*` S3 namespace. The remote verifies
bucket, key, whole payload hash, allowed paths and native module hashes before
writing a private temporary directory. It runs the existing server interpreter,
without installing anything or importing the installed app package.

Installed inspection includes every regular non-private/cache file under `app/`
and `data_pipeline/`: SHA256, size, owner and mode, with baseline/candidate matches,
missing candidate paths, and explicit installed `app/schema.py` hash. Recognized
private/cache paths and key/log/database suffixes are excluded before reading
content. Symlinks, hardlinks, unsupported file types, unsafe ownership/write
permissions and source-size bounds fail closed. Stable file metadata is checked
during each read; full source/control snapshots before and after diagnostics must
match. Five unit states report PIDs, restart state, configured memory/CPU/task
limits, property hashes, unit-file hashes, process-environment/cmdline hashes and
protected config hashes/modes. Dynamic memory usage is not a stability condition.

Process environments and the known protected config files are read privately.
Only effective perps enabled/configured/proxy-present booleans and hashes leave
the process; key values, proxy URLs and raw environment/config/command content do
not. The database child receives only the actual agent process's five MYSQL
configuration fields. Its SQL stays in `readiness_repository.py`; it uses 5-second
connect / 8-second read bounds, session-only 3-second SELECT/metadata-lock limits,
`START TRANSACTION READ ONLY`, rollback and close. It queries table presence,
research queued/running/paused aggregate counts, perps table counts, and only the
four `market` column signatures for `app_experiments`, `app_fdr_state`,
`app_holdout_ledger`, `app_data_partitions`. No rows, prompts, job/user identifiers,
settings values, keys or account data are selected. No spot-bootstrap backlog
scan or full-schema convergence claim is made.

The public child receives only the actual worker's explicit perps proxy setting
if present. A temporary diagnostic `Config(True, "production")` object invokes
the pinned client and collector once over one 48-hour window, capped at 15 HTTP
attempts and a 100-second child timeout. This changes no service flag. Ambient
auth, `.netrc`, cookies, proxies and TLS overrides stay disabled by the actual
candidate client. Only counts, coverage/status, endpoint categories, HTTP codes,
timestamps and hashes survive. Partial-candle warning remains explicit. Funding
retrieval success is not schedule coverage or continuous replay acceptance.

`read_only` describes the application boundary. GitHub/AWS transport uses the
existing GitHub secrets and creates ordinary SSM/audit records. Diagnostic source
and current encrypted S3 object are temporary writes. Existing documented IAM has
Put/Get, not DeleteObject: the runner clears the current public-source object
with an empty encrypted Put in `finally` rather than expanding IAM. Historical
S3 versions are not inspected or claimed deleted. Forced runner/host termination
can prevent cleanup; failures report this instead of claiming acceptance.

## Invocation and sanitized collection (root-owned)

Root must freeze/review/publish and check the exact operations branch head before
one dispatch. No dispatch occurred during implementation.

```bash
gh workflow run deploy.yml --repo JihuiTanUchicago/kalshi_trade \
  --ref codex/kalshi-perps-readiness-operations-20261023
```

Identify the new workflow_dispatch run on that branch and verify its `headSha` is
the reviewed operations commit. From this product directory:

```bash
python3 -B results/kalshi_bitcoin_perps_2026-10-23/operations/collect.py \
  RUN_ID EXACT_REVIEWED_OPERATIONS_SHA OUTPUT_DIRECTORY
```

The collector checks head before obtaining Actions logs, handles those logs only
in memory, and saves only fixed `TAU_PERPS_READINESS_{PREFLIGHT,PHASE,INVENTORY,CLEANUP,ERROR}`
JSON plus run metadata in `READINESS_RUN_ID.json`. Never save/print raw Actions or
SSM logs. Receipt transport is compressed and hash-checked to fit the SSM inline
limit; the runner emits the decoded deliberate inventory JSON.

Require workflow completed/success, exact PREFLIGHT operations/candidate pins,
INVENTORY status inspected with all active perps off, source/control equality,
temporary-source cleanup and CLEANUP current-object cleared, with no ERROR.
`inspected` means these bounded diagnostics completed. The receipt always keeps
full DB integration, replay and production-release acceptance false. Missing
perps tables are reported without migration. Counts are a point-in-time aggregate
and do not authorize interrupting active research.

## Offline evidence

Prepared Python 3.12 interpreter, from this operations worktree's product root:

```text
<prepared .venv/bin/python> -B -m pytest results/kalshi_bitcoin_perps_2026-10-23/operations/test_readiness.py -q
33 passed in 4.58s; final result is recorded in VERIFICATION.json.

Root's independent full source regression: 1899 passed, 10 skipped (31.30s).
No application source changed in this operations workstream.
```

Focused tests use fake AWS/process/DB responses and disposable files. They cover
actual pinned native client/collector with synthetic public responses, gap
warnings and credential isolation; read-only SQL/session bounds and corrected
schema signatures; whole-source hashes and symlink/private-file guards; enabled
flags blocking all checks; source drift; separate child environments and actual
temporary cleanup; exact real Git bundle construction and bounded compressed SSM
transport; exception sanitization; failed-inspection S3 clearing; exact-head log
collection and workflow scope. Initial tests caught and fixed cwd-dependent Git
tree enumeration plus a test path error (26 passed / 2 failed); later passing
runs supersede those failures. No real AWS, DB, provider, model or account call
was made by the delegated implementation task. Root owns remaining independent
review, full-regression-before-commit, commit/push, single dispatch and shared
project tracker/roadmap updates; none is implied by these offline results.

Final manual independent data-agent review found no concrete preflight blocker.
The real Git diagnostic bundle is 91,420 bytes, the SSM command is 7,342 characters,
and the baseline/candidate maps contain 117/122 files. All operations Python
sources compile in memory; `git diff --check` passes. Changes are frozen and
handed off to root. No feature source or shared progress record was edited in
this operations workstream.
