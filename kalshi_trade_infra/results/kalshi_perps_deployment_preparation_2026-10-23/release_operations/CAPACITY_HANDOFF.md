# Approved online worker capacity operation

Workstream: bitcoin_perps_data / 2026-10-23 / Asia/Shanghai.
Status: implemented and offline verified; frozen for root integration/review.
No commit, push, dispatch, production read/write or provider/account call was
performed by this workstream.

Own only capacity.py, test_capacity.py and this handoff. Root owns remote/runner,
guard/pins/collector/workflow integration and all publication/dispatch. Shared
trackers remain root-owned. Development-progress is recorded here.

User approved one online increase of recursive-agents MemoryMax from 400 MiB to
1 GiB, with no restart. Existing work may continue; the separate source release
still requires zero jobs and all existing idle/admission gates. No job, source,
schema, provider, billing, trading flag or other service change is authorized here.

## Contract and gates

`install_guard_exception(guard)` returns validated `{sha256, bytes, uid, gid, mode}`
for the exact new file, or `None` while absent. Root calls it after loading the
original guard and before every phase. Capacity calls it again after the one
command, including uncertain command outcomes. The exception adds only
`/etc/systemd/system.control/recursive-agents.service.d/50-MemoryMax.conf` as a
regular-file entry in the original guard's UNIT_ROOTS. It never adds its directory.
The wrapped reader revalidates complete bytes/metadata on each exact-path read and
rejects every descendant, including a replacement directory masquerading as a root.
All other reads still pass through the unchanged original guard. Parent directories
must be root-owned non-writable directories; symlinks, hard links, executable files
and group/other-writable files are rejected. File mode is root-owned 0600 or 0644,
matching generated systemd configuration rather than a secret-bearing env file.

Full bytes must equal the known systemd two-comment header followed by only
`[Service]` and `MemoryMax=1073741824`, with one or two final line feeds. Unknown
comments, directives, sections, values, duplicate directives and other encodings
fail closed. This format is based on upstream
[unit_write_setting](https://github.com/systemd/systemd/blob/main/src/core/unit.c)
and its fixed 50-property drop-in naming. The helper emits only hashes and metadata.

`run(backend, pins, command=None)` calls strict `remote.inventory` twice. Any
source/unit/unit-file/process/private-file conflict blocks the operation. Worker
PID rollover is not automatically accepted or repinned. All-kind job counts are
recorded immediately before the command; active work and legitimate completion
are allowed under the user's online increase approval. No idle guard in existing
prepare/apply is edited or relaxed.

Cause evidence must show own-worker constrained OOM, either in the successful
current projection or in the exact explicitly approved prior receipt described
below when current records are zero. Current ancestor/global/unclassified records
or unavailable evidence block the operation. Host MemTotal must be at least 12 GiB
and MemAvailable at least 8 GiB. The active worker's configured cap, actual fixed
cgroup memory.max and computed effective cap must all be exactly 400 MiB. The
fixed worker path is `/system.slice/recursive-agents.service`, and the PID's proc
cgroup must agree. The fixed system.slice parent must already permit 1 GiB.

Older systemd may omit EffectiveMemoryMax or return it empty. Effective capacity
is independently computed as the minimum of worker memory.max, finite parent
system.slice memory.max, and physical MemTotal. A present nonempty systemd value
must match that result; malformed values are rejected. Parent limit and identity,
worker cgroup identity and physical MemTotal must remain unchanged. The after-read
obtains physical memory freshly from bounded /proc/meminfo. Receipts identify
`kernel_hierarchy` when the optional systemd property is unavailable; no unsupported
property is assumed to exist. Its presence/absence cannot change during the operation.

Every private worker property projection restricted to actually emitted original
guard.PROPERTIES must fingerprint to the corresponding guard snapshot's worker
properties hash, before and after. Only the explicitly optional EnvironmentFiles
and EffectiveMemoryMax may be omitted; no empty keys are fabricated. Complete
privately parsed systemd properties must agree across
the command except MemoryMax, optional EffectiveMemoryMax, and exactly one new
DropInPaths entry. Whole actual private environments, PID/start times, every
non-target process/unit/resource, source hashes and protected files must be identical.

The single mutation is fixed and bounded to eight seconds:

```text
systemctl set-property recursive-agents.service MemoryMax=1073741824
```

No stop/start/restart/reload, retry, deletion, lower-cap restoration, job write,
schema/source mutation, new instance, provider/account call or trading-flag change
exists in this module. `resource_property_commands` records this one attempted
property operation. An attempt reports `service_operations=1` and
`service_restart_operations=0`; it does not claim no service mutation occurred.
The command's output and any raw errors stay transient in memory.

## Outcomes and ownership boundary

Success is `capacity_verified`, with `override_added`, `resource_change_verified`
and `no_service_restart` true, safe observed controls and numeric limits. It does
not activate perps or complete stability acceptance. Failures are
`capacity_requires_inspection` with fixed error codes. `mutation_may_have_applied`
is set before the single command. A timeout still triggers validated persistent
and effective-state reads; even apparently complete application after a timeout
requires inspection. No error body, raw environment or private property values
enter a receipt. Existing work is never canceled or stopped to accommodate a failure.

Fifteen-minute stability remains a later owner gate: no manufactured jobs/model
calls, repeated safe observations, no restart or new confirmed OOM, followed by
explicit review of the new complete release baseline. One GiB is not claimed
sufficient for future load. No automatic second increase or decrease is allowed.

## Verification

Focused capacity suite: **23 unittest cases passed**, including older-systemd
compatibility, false/malformed effective values, ancestor restrictions and drift,
all strict preflight conflicts, online active work, legitimate job completion,
private-property generation mismatch, timeout before/after mutation, post-read
failure, concurrent source/env/process/resource/flag changes, exact complete-body
validation, inode replacement and directory/descendant rejection. One case executes
the unchanged original guard's actual unit_state implementation: the normal guard
rejects system.control, the exact exception permits only the approved file, and an
adjacent control file or descendant still fails.

Reproduce from the operations worktree:

```text
python -B -m unittest discover -s kalshi_trade_infra/results/kalshi_perps_deployment_preparation_2026-10-23/release_operations -p 'test_capacity.py' -q
```

Root owns integration tests/full-suite execution, immutable security review,
publication, fresh baseline review, any dispatch, resource acceptance and the later
idle-only perps deployment. Shared trackers/pins/workflow/runner/collector/remote
are intentionally unchanged by this workstream. This handoff is the scoped
development-progress evidence record.

## Read-only compatibility addendum after run 39902392787

Actual capacity run 39902392787 at operations commit 9d25f3c81e427360b9a369c0e8c240c30a654359
stopped before the property command with capacity_projection_invalid. Its canonical
release receipt reports zero command attempts, no possible mutation, no override,
matching source/control pins, all job counts zero, host headroom and positive own
worker OOM evidence. This does not prove which compatibility gate rejected the host.
No property retry, baseline change or runtime guard relaxation was performed here.

New `compatibility_probe(guard, command=None)` is read-only. It issues exactly one
fixed three-second systemctl show request using the original PROPERTIES plus
ControlGroup/EffectiveMemoryMax, without adding --all. Only static whitelisted
property presence/row-validity booleans and validated numeric PID/limits are returned.
Raw Environment/ExecStart values, unknown property names/values, systemd output,
kernel mapping text and exception bodies never enter the receipt.

The probe also reads only the fixed worker/parent cgroup limit files and the
validated numeric worker PID's proc cgroup file. It projects existence, type,
root ownership, parent safety, bounded read/format and mapping booleans, including
v1 memory versus unified membership. Diagnostic reads can report non-root proc
ownership without altering the strict observer's owner requirement. File opens
are read-only/no-follow/nonblocking and bounded to 4096 bytes; systemd output is
bounded to 1 MiB. The physical-memory helper retains its existing bounded numeric
read. All errors use fixed codes; every mutation/provider/job counter remains zero.

Focused capacity suite now passes **32 tests**, including nine probe regression
cases for omitted required versus optional properties, one unchanged show request,
read-only file flags, non-root proc ownership, unified/v1/hybrid mapping, private
malformed/unknown/duplicate rows, invalid PID/path, missing/symlink/bad-format files,
bounded response/error redaction, and effective-limit disagreement. Root owns the
inventory-only bootstrap integration, immutable review and any read-only dispatch.
At this diagnostic-only milestone the original capacity write implementation and
every acceptance gate were unchanged. The evidence-based compatibility change
below supersedes the earlier strict missing-EnvironmentFiles requirement.

## Evidence-based omission and approved cause receipt

Read-only inventory 39903498965 at e692f7d735f54c4fa792c3232ca6233c303a6c80
confirmed that only EnvironmentFiles and EffectiveMemoryMax were absent from the
actual show output. Every other requested field was present and row-valid. The
fixed worker/parent/proc metadata was accepted; proc mapping was exactly unified;
worker memory.max was 419430400, parent unlimited and physical memory 16537710592.
No property mutation occurred. This diagnosis supports only the explicit
EnvironmentFiles omission, not generic acceptance of missing properties.

The observer now permits exactly EnvironmentFiles plus the already optional
EffectiveMemoryMax to be absent. It keeps the raw present-key dictionary and
hashes only actual emitted guard.PROPERTIES, matching the unchanged guard's
query without --all. Missing Environment, ExecStart, identity/resource fields,
DropInPaths or any other requested mandatory field still fails before mutation.
EnvironmentFiles appearing or disappearing between before/after projections is
rejected, even when the new value is empty and the new guard hash is otherwise
valid. No blank value is synthesized for hashing or equality.

The approved prior-cause pin has exactly this public metadata shape:

```json
{
  "run_id": 39901486782,
  "receipt_sha256": "510b943f8b0f0b03cae635d10406839d7479fea9b96633ae2e2a4771c4f0abb4",
  "worker_pid": 507858,
  "kernel_events_last_30m": {
    "worker_limit": 2,
    "cgroup_constraint": 2,
    "ancestor_limit": 0,
    "global_constraint": 0,
    "unclassified_memcg": 0
  }
}
```

Root owns placing this reviewed proof under pins.capacity_approved_oom_evidence
and the narrow interpretation of a successful journal no-entry result. Capacity
does not turn unavailable/error evidence into zero records. Prior evidence is used
only when all five current kernel counts are typed, nonnegative and zero, there
are no current host/kernel error markers, current actual PID and baseline pinned
PID both equal 507858, and every prior run/hash/PID/count matches the approved
values with strict types. Missing/extra fields, invalid counts, stale worker PID,
bad current scopes or any current source/control conflict block the command.
The two prior records are constraint evidence, not a claim of two distinct kills.

Receipts preserve current kernel_events_last_30m separately from
approved_prior_oom_evidence and identify cause_source as current_kernel_window or
approved_prior_receipt. Both pre-command checks still require fresh host headroom;
the prior receipt never supplies current capacity or process acceptance.

Focused capacity verification now passes **38 tests**. New regressions cover a
full synthetic run with the actual omitted-key shape, raw hashes differing from
fabricated empty fields, every other mandatory omission, either EnvironmentFiles
presence transition, exact approved prior evidence with current zero events,
invalid/missing prior metadata, stale PID, current errors/bad scopes and conflicts.
The fixed property command, no-restart/no-retry policy, complete private-env/source
checks and every unrelated mutation limit remain unchanged. No commit, publication,
dispatch, new production read, property retry or pin edit was performed here.
