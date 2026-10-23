# Selected installed-source review capture

October 23, 2026, Asia/Shanghai. Workstream
`tau-kalshi-perps-source-review-operations-20261023`; **implemented and offline
verified; frozen and handed to root; not published or dispatched**.
Development-progress skill applied. Named project backend and
security-review skills remain unavailable; no named security scan is claimed.

Owned only: this new directory and this worktree's `.github/workflows/deploy.yml`.
Base `0e2e79c30d13bab8dec41081ef4d273d826b127c`. Root owns all other source,
private key material, shared records, publication, dispatch, local decryption,
deployment and activation decisions. Never merge this operations branch.

Prepare one bounded read-only capture of exactly eight unresolved installed app
files pinned by size and SHA256 in the prior source comparison. Reuse the prior
snapshot/read_regular guards and aggregate read-only DB helper. No public feed,
model, account/order, restart/reload, DDL, persistent settings/job/config/env,
receiver or installed-package change. Unexpected perps enablement or source
drift fails closed. Protected environment files and private key files are never
read; actual process environments are inspected privately for flags and filtered
worker MYSQL fields for the bounded DB helper.

Source bytes are compressed and encrypted in memory with random AES-256-GCM;
the AES key is wrapped to root's pinned RSA public key using OAEP-SHA256. Only
the ciphertext envelope may enter SSM/Actions output or a private temporary
server file. Transfer is limited to a fixed number of inline pages with cleanup.
The private key stays outside Git and the workflow; root alone supplies it to a
local collector writing under the approved ignored private root.

## Exact scope and encryption

`transfer.py` hard-codes all eight approved application paths, exact lengths and
SHA256 from the prior feature publication's `SOURCE_COMPARISON_REVIEW.md`:
agent, billing, devlog, llm, repository, schema, server and the default app.js.
Their total is 842,077 bytes. No path/ref/source selection is exposed as workflow
input. Protected config/env files, credentials, logs, data and the two preserved
diagnostic scripts are not exported. No app source is executed by this operation.

The sole recipient public PEM has SHA256
`24746c869bcda8ae3c177a0c0a355939a7504f3a795443492696acf0317ccec8`.
It is root's supplied 3072-bit RSA public key. No real private key was read during
implementation. The remote program contains encryption definitions only; the
local decryption function is omitted from its generated source.

Encryption uses a random 256-bit AES-GCM key and 96-bit nonce. RSA-OAEP uses
SHA256 for both OAEP and MGF1. AES-GCM authenticates the fixed file manifest,
capture ID, exact operations SHA, recipient hash and sanitized inspection
metadata. File content is base64-structured, compressed and encrypted entirely
in memory. The remote writes only the ciphertext envelope in a newly created
root-owned mode0700 `/tmp/tau-perps-selected-source-<random32hex>/` directory,
file0600. The maximum envelope is 768,000 bytes, transferred in at most64 fixed
12,000-byte pages; each carries its index, whole-envelope and per-page SHA256.
No S3 or public artifact upload is used.

## Read-only inspection and bounds

The runner reuses `snapshot`/`read_regular` and the aggregate read-only repository
helper from immutable base `0e2e79c30d13bab8dec41081ef4d273d826b127c` through Git.
It explicitly empties the reused guard's CONFIG tuple before invoking it:
protected environment files are not opened. Existing public-source hashes,
unit/PID/resources and process-environment/cmdline hashes are inspected privately.
Actual process environments are used only for effective flag/control inspection
and filtered worker MYSQL fields for the DB child. No key-file path is opened.
All active-service perps flags must remain off; invalid flags, unsafe paths,
changed expected source bytes or any before/after source/control drift fail
before encrypted staging. The source snapshot reads public source to hash it;
only the eight pinned file bodies enter the encrypted payload.

The DB helper runs from the temporary parent with only five allowlisted MYSQL
fields and a minimal process environment, a 35-second child timeout, bounded
read-only transaction/session SQL, rollback and close. It selects aggregate
counts/table/column metadata, no user/job identifiers or records. Database
unavailability is explicit in authenticated metadata; it does not turn a source
capture into a database/release acceptance claim. No public/native/provider,
account/order, model or network-proxy helper is invoked.

The capture target command is bounded to180s; page/cleanup commands to30s, with
a ten-minute runner transfer deadline and a separate bounded cleanup attempt in
`finally`. The workflow has its own concurrency group and cannot replace or
cancel a pending deploy. It has no install/migration/restart/reload/flag/receiver
or apply path. Normal completion requires temporary ciphertext directory removal.
Hard host/runner termination or transport ambiguity can prevent cleanup; retained
data would still be encrypted, and the run must be inspected rather than claimed
complete. Snapshot fingerprints omit protected config content here and must not
be compared directly to the earlier readiness operation's differently scoped hash.

## Root-owned invocation and local collection

Root owns independent review, full required checks, exact-head commit/publication
and a single selected-source dispatch. Recheck the branch head immediately before
dispatch, and verify the resulting run uses that exact reviewed commit:

```bash
gh workflow run deploy.yml --repo JihuiTanUchicago/kalshi_trade \
  --ref codex/kalshi-perps-source-review-operations-20261023
```

Only `TAU_PERPS_SOURCE_{PREFLIGHT,PHASE,CAPTURE,PAGE,CLEANUP,ERROR}` JSON is
emitted. PAGE data is ciphertext-envelope content only, base64 encoded. Ordinary
GitHub/SSM audit retention still exists; no source body, environment, DB credential,
private key, raw app log or provider body is printed. No plaintext source is
published as an Actions artifact.

From this product directory, root alone invokes the local collector with their
outside-Git private-key path and a new direct child of the approved private root:

```bash
<prepared .venv/bin/python> -B \
  results/kalshi_perps_deployment_preparation_2026-10-23/source_review/collect.py \
  RUN_ID EXACT_REVIEWED_OPERATIONS_SHA PRIVATE_KEY_PATH PRIVATE_OUTPUT_DIRECTORY
```

Both key parent and output parent must be exactly
`/Users/jonathanzhang/Desktop/Polygon/.runtime/private/kalshi-perps-source-review-20261023`.
That existing directory must be owned by the local user with mode0700; the
private key must be a regular non-symlink/non-hardlinked mode0600 file. Output
must be new; the collector never overwrites a prior capture. It checks successful
workflow/exact head before fetching logs or reading the local private key,
handles Actions logs in memory, requires complete unique authenticated pages
and cleanup, then decrypts and checks all eight paths, sizes and hashes before
creating output. Source files are mode0600 under mode0700 directories. The saved
`SOURCE.encrypted.json` and `CAPTURE_RECEIPT.json` contain encrypted source and
deliberate metadata, respectively; raw Actions/SSM logs are never saved. The
collector prints only status, counts and hashes. Private output stays outside Git
until root reviews the source and prepares an intentional reconciled patch.

Require completed/success, exact PREFLIGHT head/public-key/source pins,
CAPTURE status captured with perps off/source-control equality metadata, all
bounded PAGE indices and hashes, CLEANUP status cleaned with directory removed,
and no ERROR. Successful source recovery establishes these exact captured
bytes, not worker-loaded source, source safety, release, schema-lock, replay or
trading/activation acceptance. The user's later real-money scope does not change
this operation's read-only boundary.

## Verification and handoff

Prepared runtime is Python3.12 with cryptography44.0.2. Focused command:

```text
<prepared .venv/bin/python> -B -m pytest results/kalshi_perps_deployment_preparation_2026-10-23/source_review/test_source_review.py -q
31 passed in1.83s
```

Tests use generated synthetic RSA keys, fake process/DB/AWS receipts and disposable
source files. They exercise real RSA-OAEP/AES-GCM roundtrip/randomness/tampering,
fixed recipient/pins, eight-file capture, plaintext omission, flags/source drift,
symlink and page/size bounds, private staging/cleanup, DB environment isolation,
SSM-only transport, exact-head log collection, multi-page assembly and actual
local private-file permissions. The actual root private key was never read.
All scoped Python compiles in memory; `git diff --check` passes. Generated target
commands are capture13,118/page10,602/cleanup10,586 characters, all below24,000.

An intentionally over-broad combined run included the prior operation's test
that asserts its old workflow concurrency group; that assertion fails after
this authorized branch-only workflow replacement (1failed/1962passed/10skipped,
34.44s). Its other32 tests pass. The prior test is left unchanged outside scope.
The applicable full application suite plus new capture tests passes:

```text
<prepared .venv/bin/python> -B -m pytest tests/ results/kalshi_perps_deployment_preparation_2026-10-23/source_review/test_source_review.py -q
1930 passed, 10 skipped in29.38s
```

Final results and frozen status are recorded in VERIFICATION.json. All owned
runtime files are frozen; no further feature change is planned in this capture.

Root owns remaining independent review, commit/push/one dispatch, local
decryption, source reconciliation and shared project records. No commit, push,
dispatch, actual DB/provider/model/account/order call, source installation or
service/job/flag change occurred in this delegated implementation task.
