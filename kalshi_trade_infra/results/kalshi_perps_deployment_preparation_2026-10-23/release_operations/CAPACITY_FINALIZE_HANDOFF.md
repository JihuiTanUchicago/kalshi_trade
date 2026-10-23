# Finalize the already applied worker memory repair

Workstream: bitcoin_perps_data / 2026-10-23 / Asia/Shanghai.
Status: implemented and offline verified; frozen for independent review.
No operations performed by this workstream.

Own only capacity_finalize.py, test_capacity_finalize.py and this handoff. Root owns
all existing modules, integration, pins, approval/publication/dispatch and shared
trackers. Development-progress is recorded here.

Actual capacity run39904624559 applied the one approved 1GiB limit and exact
override; its verification stopped on NeedDaemonReload=yes. Read-only inventory
39904754786 confirmed the expected partial state and no process/source/private-file
drift. This module requires those exact receipts and the current reviewed partial
baseline before one bounded manager daemon-reload. No property write, restart,
retry, lower limit or file deletion exists. Separate perps deployment remains
subject to all original idle/admission gates and the later stability review.

The required eight approval fields bind capacity39904624559 receipt SHA256
98811b3c603173748498043827bd457441ec28056dcd60a3869300b7c4742e7a and
inventory39904754786 receipt SHA256
ed13fb6e54b85c2804dd60433b43d9f936346b491cbd36b3cfcd8035c18b0572,
PID509844/start50358518, the original worker properties fingerprint
6655e1ab35e68436fc8f202ea7266f8e00bb92ec9c44c024676bf5ca04f669f1,
and exact override SHA256
8714f37da811546b5c7bc1babb7172cc7a42b27eb0cea820a323ef1b6d07eb44.
The file must still be152bytes/root:root/0644 and pass capacity's complete-byte
validation and fixed-path reader. All fields and types must match; no adoption of
new production state or automatic pin refresh is allowed.

`run(backend, pins, *, command=None)` returns `capacity_finalize_verified` only
after a successful one-shot `systemctl daemon-reload` with timeout8 and complete
state proof. Failures return `capacity_finalize_requires_inspection` and a fixed
error code. A command timeout/error still triggers one post-command inspection;
even an exact resulting state cannot turn that ambiguous command into success.
No recovery mutation or retry exists.

Before the command, two strict inventories must match all reviewed source,
unit-file, protected-config and process maps plus private actual environments.
The only reported conflict must be pending_daemon_reload, and only the worker may
need reload. Current1GiB configured/kernel/effective limits, cgroup/parent/physical
identity, PID/start and raw-property generation must match both reads. Fresh typed
host headroom and current kernel evidence are required; zero current events is
accepted after this already applied repair, with no historical-cause fallback.
Busy all-kind job counts and legitimate completion are observed without writes.

The original raw-property proof changes only MemoryMax back to400MiB,
NeedDaemonReload to no, and removes the one exact override path while preserving
the other paths' order. Its hash must equal the original6655… receipt. Actual
present properties alone enter the guard hash; omitted EnvironmentFiles and
EffectiveMemoryMax are never fabricated. This proof prevents silently accepting
unrelated settings with the reviewed resource change.

After the command, the entire source/private-env/process/unit-file/config maps
must remain exact. Only worker NeedDaemonReload yes→no, its corresponding bound
property hash, and ordering of the identical unique DropInPaths set may differ.
Every other raw property, optional-property presence, kernel hierarchy and
physical-memory value must remain exact. Full credential-free observed_controls,
source_fingerprint, fixed override metadata and after-health are emitted only
after all proofs and command outcome pass. All receipts retain property attempts0,
restart operations0 and stability_observation_completed=false.

Verification, using the existing isolated product venv from the operations
worktree root:

```
/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/kalshi_trade/kalshi_trade_infra/.venv/bin/python -B -m unittest discover -s kalshi_trade_infra/results/kalshi_perps_deployment_preparation_2026-10-23/release_operations -p 'test_capacity_finalize.py' -q
```

Result:24 tests passed. Cases cover successful exact-state reload, busy/completing
jobs, exact approval/hash/type gates, every source/control conflict, current
headroom/kernel validity, original-property reconstruction and order, duplicate
paths, mandatory/optional property changes, private-environment drift, ancestor
identity changes, before/after command timeouts, changed after-state, and fixed
error redaction. All fixtures and broker-free observations are synthetic; no
systemd, database, provider or network operation was executed. Both new Python
files compile in memory, and git diff --check passed.

Frozen Python SHA256:

- capacity_finalize.py:195ce7d4c4c3e72f3b45d93c217c625996aaefdbb837d2ed26dc84824d0e321a
- test_capacity_finalize.py:8bfbc9642a0c1d6cb48bb86b0223d58de4d50e02c7fbad194b830087c6f1ba6c

Remaining owner gates: independent source/control review, integration and combined
tests, immutable publication review and explicit single finalization dispatch by
root; then an actual15-minute no-restart/no-new-OOM observation and explicit
post-repair baseline reconciliation. Root owns shared PLAN/mvp and release
trackers, which this scoped workstream did not edit. The separate perps rollout
still requires its original idle/admission checks; nothing here enables it.

Primary implementation context: systemd v249 unit_write_setting appends the new
drop-in to the loaded path list, whereas discovery sorts by basename and
unit_need_daemon_reload compares path-list order. This supports the observed
pending reload without proving any unseen state is safe. See official
[unit_write_setting](https://github.com/systemd/systemd/blob/v249/src/core/unit.c#L3994-L4004),
[unit_need_daemon_reload](https://github.com/systemd/systemd/blob/v249/src/core/unit.c#L3353-L3375),
and [drop-in ordering](https://github.com/systemd/systemd/blob/v249/src/basic/conf-files.c#L122-L158).
