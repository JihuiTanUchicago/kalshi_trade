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

Fresh pressure evidence must show own-worker constrained OOM, with no ancestor,
global or unclassified constraint evidence. Host MemTotal must be at least 12 GiB
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

Every private worker property projection restricted to the original guard.PROPERTIES
must fingerprint to the corresponding guard snapshot's worker properties hash,
before and after. Complete privately parsed systemd properties must agree across
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
